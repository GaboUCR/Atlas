import os
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException, status, Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

import api.security as sec
from api.security import RateLimiter 
from core.tenancy import TenantRegistry

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

class IngestDocsRequest(BaseModel):
    documents: List[IngestDoc]

class AskRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    top_k: int = Field(8, ge=1, le=50)

class AskResponse(BaseModel):
    answer: str
    citations: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {}

# --- Rutas ---
@app.get("/health")
def health():
    return {"status": "ok", "tenants": len(sec.REGISTRY._tenants) if sec.REGISTRY else 0}

@app.post("/tenants", response_model=CreateTenantResponse, tags=["Tenants"], dependencies=[Depends(sec.admin_auth)])
def create_tenant(req: CreateTenantRequest):
    api_key = sec.REGISTRY.create_tenant(tenant_id=req.tenant_id, name=req.name)
    return {"tenant_id": req.tenant_id, "api_key": api_key}

@app.post("/tenants/{tenant_id}/docs", tags=["Documents"], dependencies=[Depends(sec.rate_limit)])
def ingest_docs(
    tenant_id: str = Path(..., description="Tenant destino"),
    auth_tenant_id: str = Depends(sec.resolve_tenant_id),
    req: IngestDocsRequest = ...,
):
    if tenant_id != auth_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")
    # TODO MS2.5: conectar con VectorStoreFactory → chunking/embeddings/upsert por tenant
    count = len(req.documents)
    return {"tenant_id": tenant_id, "ingested": count, "status": "accepted", "note": "stub - falta indexado"}

@app.post("/tenants/{tenant_id}/ask", response_model=AskResponse, tags=["Chat"], dependencies=[Depends(sec.rate_limit)])
def ask(
    tenant_id: str = Path(...),
    auth_tenant_id: str = Depends(sec.resolve_tenant_id),
    req: AskRequest = ...,
):
    if tenant_id != auth_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")
    # TODO MS2.5: usar retriever per-tenant; por ahora stub
    return AskResponse(
        answer="[stub] Motor de retrieval aún no conectado para este tenant.",
        citations=[],
        metrics={"note": "ms2 stubs"},
    )

@app.get("/tenants/{tenant_id}/metrics", tags=["Metrics"], dependencies=[Depends(sec.rate_limit)])
def metrics(
    tenant_id: str = Path(...),
    auth_tenant_id: str = Depends(sec.resolve_tenant_id),
):
    if tenant_id != auth_tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant mismatch")
    # TODO: devolver métricas reales; por ahora stub
    return {"tenant_id": tenant_id, "qps": 0, "latency_p95_ms": None, "requests": 0}