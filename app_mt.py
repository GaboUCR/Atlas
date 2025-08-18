import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, status, Path, Query
from pydantic import BaseModel, Field
from dotenv import load_dotenv
load_dotenv()

import api.security as sec
from api.security import RateLimiter 
from core.tenancy import TenantRegistry

from core.ingest_service import IngestDoc as IngestDocModel, ingest_texts
from core.raw_store import list_raw, get_raw
from core.retrieval import rag_answer

import time, logging
from fastapi import Request, Response, Query
from fastapi.responses import JSONResponse

from observability.logging import setup_logging, safe_preview
from observability.tracing import new_trace_id
from observability.metrics import metrics_endpoint, REQUEST_LATENCY_MS, REQUESTS_TOTAL, FEEDBACK_TOTAL



app = FastAPI(title="Atlas API — MS2 Multi-tenant", version="0.2.0")

setup_logging()
log = logging.getLogger("atlas")


# --- Inicialización tenancy + rate limit ---
DATA_DIR = os.getenv("DATA_DIR", ".data")
API_KEY_SALT = os.getenv("API_KEY_SALT", "dev_salt")
sec.REGISTRY = TenantRegistry(data_dir=DATA_DIR, salt=API_KEY_SALT)

rps = float(os.getenv("RATE_LIMIT_RPS", "5"))
burst = int(os.getenv("RATE_LIMIT_BURST", "10"))
sec.RATE_LIMITER = RateLimiter(rps=rps, burst=burst)

# --- Modelos ---
class CreateTenantRequest(BaseModel):
    tenant_id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9_-]{1,62}[a-z0-9]$")
    name: str

class CreateTenantResponse(BaseModel):
    tenant_id: str
    api_key: str

class IngestDoc(BaseModel):
    text: str = Field(..., min_length=1, max_length=200_000)
    source: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    doc_id: Optional[str] = None
    force_reindex: bool = False

class IngestDocsResponse(BaseModel):
    tenant_id: str
    ingested: int
    duplicates_skipped: int
    errors: int
    chunks_total: int
    raw_saved: int
    raw_bytes: int
    doc_ids: List[str]
    metrics: Dict[str, Any]

class IngestDocsRequest(BaseModel):
    documents: List[IngestDoc]

class AskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(8, ge=1, le=50)

class AskResponse(BaseModel):
    answer: str
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    metrics: Dict[str, Any] = Field(default_factory=dict)

class ListDocsResponse(BaseModel):
    items: List[Dict[str, Any]]
    next_cursor: Optional[str] = None

# --- Rutas ---
@app.get("/health")
def health():
    return {"status": "ok", "tenants": len(sec.REGISTRY._tenants) if sec.REGISTRY else 0}


@app.post("/tenants", response_model=CreateTenantResponse, tags=["Tenants"], dependencies=[Depends(sec.admin_auth)])
def create_tenant(req: CreateTenantRequest):
    api_key = sec.REGISTRY.create_tenant(tenant_id=req.tenant_id, name=req.name)
    return {"tenant_id": req.tenant_id, "api_key": api_key}

@app.post("/tenants/{tenant_id}/docs", response_model=IngestDocsResponse, tags=["Documents"], dependencies=[Depends(sec.rate_limit)])
def ingest_docs(
    tenant_id: str = Path(..., description="Tenant destino"),
    auth_tenant_id: str = Depends(sec.resolve_tenant_id),
    req: IngestDocsRequest = ...,
):
    if tenant_id != auth_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")

    docs_internal = [
        IngestDocModel(
            text=d.text,
            source=d.source or "payload",
            metadata=d.metadata or {},
            doc_id=d.doc_id,
            force_reindex=d.force_reindex,
        )
        for d in req.documents
    ]

    import os
    chunk_size = int(os.getenv("CHUNK_SIZE", "1200"))
    chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "200"))

    res = ingest_texts(tenant_id, docs_internal, chunk_size=chunk_size, overlap=chunk_overlap)
    return res.model_dump()


@app.get("/tenants/{tenant_id}/docs", response_model=ListDocsResponse, tags=["Documents"], dependencies=[Depends(sec.rate_limit)])
def list_docs_endpoint(
    tenant_id: str = Path(...),
    auth_tenant_id: str = Depends(sec.resolve_tenant_id),
    limit: int = Query(50, ge=1, le=200),
    cursor: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
):
    if tenant_id != auth_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")
    items, next_cursor = list_raw(tenant_id, limit=limit, cursor=cursor, source=source)
    return {"items": items, "next_cursor": next_cursor}


# --- GET /docs/{doc_id} (lectura raw/clean) ---
@app.get("/tenants/{tenant_id}/docs/{doc_id}", tags=["Documents"], dependencies=[Depends(sec.rate_limit)])
def get_doc_endpoint(
    tenant_id: str = Path(...),
    doc_id: str = Path(...),
    auth_tenant_id: str = Depends(sec.resolve_tenant_id),
    variant: str = Query("raw", pattern=r"^(raw|clean)$"),
):
    if tenant_id != auth_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")
    try:
        rec = get_raw(tenant_id, doc_id, variant=variant)
        return rec
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/tenants/{tenant_id}/ask", response_model=AskResponse, tags=["Chat"], dependencies=[Depends(sec.rate_limit)])
def ask(
    tenant_id: str = Path(...),
    auth_tenant_id: str = Depends(sec.resolve_tenant_id),
    req: AskRequest = ...,
    request: Request = None,
):
    if tenant_id != auth_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")

    result = rag_answer(tenant_id, req.query, req.top_k)

    # ← leer el trace_id del middleware
    trace_id = getattr(request.state, "trace_id", None) or request.headers.get("X-Trace-Id")
    result["metrics"]["trace_id"] = trace_id

    log.info(
        "ask",
        extra={"extra": {
            "trace_id": trace_id, "tenant_id": tenant_id, "k": req.top_k,
            "hits": result["metrics"].get("hits"),
            "tokens_in": result["metrics"].get("tokens_in"),
            "tokens_out": result["metrics"].get("tokens_out"),
            "cost_usd": result["metrics"].get("cost_usd"),
            "preview_q": safe_preview(req.query),
        }},
    )
    return AskResponse(**result)

 
@app.get("/tenants/{tenant_id}/metrics", tags=["Metrics"], dependencies=[Depends(sec.rate_limit)])
def metrics(
    tenant_id: str = Path(...),
    auth_tenant_id: str = Depends(sec.resolve_tenant_id),
):
    if tenant_id != auth_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")
    # TODO: devolver métricas reales; por ahora stub
    return {"tenant_id": tenant_id, "qps": 0, "latency_p95_ms": None, "requests": 0}


@app.middleware("http")
async def tracing_and_metrics_mw(request: Request, call_next):
    start = time.perf_counter()
    trace_id = request.headers.get("X-Trace-Id") or new_trace_id()
    request.state.trace_id = trace_id
    tenant_id = "unknown"
    try:
        x_api = request.headers.get("X-API-Key")
        if x_api and sec.REGISTRY:
            tid = sec.REGISTRY.resolve_tenant(x_api)
            if tid:
                tenant_id = tid
    except Exception:
        pass

    try:
        response: Response = await call_next(request)
    except Exception as e:
        # Siempre devuelve una Response para evitar AssertionError
        log.exception("unhandled", extra={"extra": {
            "trace_id": trace_id, "tenant_id": tenant_id, "route": request.url.path
        }})
        response = JSONResponse({"detail": "internal error", "trace_id": trace_id}, status_code=500)

    took_ms = int((time.perf_counter() - start) * 1000)
    route = request.url.path

    # métricas
    REQUEST_LATENCY_MS.labels(route=route, tenant_id=tenant_id).observe(took_ms)
    REQUESTS_TOTAL.labels(route=route, tenant_id=tenant_id, status=str(response.status_code)).inc()

    # header con trace
    response.headers["X-Trace-Id"] = trace_id

    # log
    log.info("req", extra={"extra": {
        "trace_id": trace_id, "tenant_id": tenant_id, "route": route,
        "method": request.method, "status": response.status_code, "latency_ms": took_ms
    }})
    return response


class FeedbackRequest(BaseModel):
    trace_id: str = Field(..., min_length=8, max_length=64)
    rating: str = Field(..., pattern=r"^(up|down)$")
    comment: Optional[str] = Field(None, max_length=1000)

@app.post("/tenants/{tenant_id}/feedback", tags=["Feedback"], dependencies=[Depends(sec.rate_limit)])
def feedback(
    tenant_id: str = Path(...),
    auth_tenant_id: str = Depends(sec.resolve_tenant_id),
    body: FeedbackRequest = ...,
):
    if tenant_id != auth_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")

    # persistir en data/feedback/<tenant>/YYYY-MM-DD.jsonl
    import os, json
    from datetime import datetime, timezone
    data_dir = os.getenv("DATA_DIR", ".data")
    folder = os.path.join(data_dir, "feedback", tenant_id)
    os.makedirs(folder, exist_ok=True)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(folder, f"{date}.jsonl")
    rec = {
        "trace_id": body.trace_id,
        "rating": body.rating,
        "comment": body.comment,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    FEEDBACK_TOTAL.labels(tenant_id=tenant_id, label=body.rating).inc()

    log.info("feedback", extra={"extra": {"tenant_id": tenant_id, **rec}})
    return {"ok": True}


@app.get("/metrics")
def metrics_http():
    return metrics_endpoint()
