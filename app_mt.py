import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, status, Path, Query
from pydantic import BaseModel, Field
from dotenv import load_dotenv

import api.security as sec
from api.security import RateLimiter 
from core.tenancy import TenantRegistry

from core.ingest_service import IngestDoc as IngestDocModel, ingest_texts
from core.raw_store import list_raw, get_raw
from core.retrieval import rag_answer

load_dotenv()

app = FastAPI(title="Atlas API — MS2 Multi-tenant", version="0.2.0")

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
    citations: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {}

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
):
    if tenant_id != auth_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")

    result = rag_answer(tenant_id, req.query, req.top_k)
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