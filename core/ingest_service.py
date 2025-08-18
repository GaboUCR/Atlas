# core/ingest_service.py
from __future__ import annotations
import hashlib
import time
from typing import Dict, Any, List, Tuple

from pydantic import BaseModel

from core.chunking import normalize_text, split_into_chunks
from core.vectorstore_factory import get_vectorstore

class IngestDoc(BaseModel):
    text: str
    source: str | None = None
    metadata: Dict[str, Any] | None = None

class IngestResult(BaseModel):
    tenant_id: str
    ingested: int
    duplicates_skipped: int
    errors: int
    chunks_total: int
    metrics: Dict[str, Any]


def _chunk_id(tenant_id: str, source: str | None, chunk_text: str, idx: int) -> str:
    h = hashlib.sha1()
    h.update(tenant_id.encode("utf-8"))
    h.update(b"|")
    if source:
        h.update(source.encode("utf-8"))
    h.update(b"|")
    h.update(str(idx).encode("utf-8"))
    h.update(b"|")
    h.update(chunk_text.encode("utf-8"))
    return "sha1:" + h.hexdigest()


def ingest_texts(tenant_id: str, docs: List[IngestDoc], *, chunk_size: int = 1200, overlap: int = 200) -> IngestResult:
    t0 = time.perf_counter()
    vs = get_vectorstore(tenant_id)

    total_chunks = 0
    to_add_texts: List[str] = []
    to_add_meta: List[Dict[str, Any]] = []
    to_add_ids: List[str] = []

    # construye lote
    for d in docs:
        text_norm = normalize_text(d.text)
        if not text_norm:
            continue
        chunks = split_into_chunks(text_norm, chunk_size, overlap)
        for i, c in enumerate(chunks):
            cid = _chunk_id(tenant_id, d.source or "", c, i)
            meta = {
                "tenant_id": tenant_id,
                "source": d.source or "unknown",
                "chunk_index": i,
                "total_chunks_hint": len(chunks),
                "id": cid,     # <- agregado
                "_id": cid,    # <- agregado
            }
            if d.metadata:
                meta.update(d.metadata)
            to_add_texts.append(c)
            to_add_meta.append(meta)
            to_add_ids.append(cid)
        total_chunks += len(chunks)

    ingested = 0
    duplicates = 0
    errors = 0

    # inserta; si hay duplicados, intenta uno por uno para contarlos
    try:
        vs.add_texts(texts=to_add_texts, metadatas=to_add_meta, ids=to_add_ids)
        ingested = len(to_add_ids)
    except Exception:
        # inserción granular para distinguir duplicados (IDs ya existentes)
        for txt, meta, cid in zip(to_add_texts, to_add_meta, to_add_ids):
            try:
                vs.add_texts(texts=[txt], metadatas=[meta], ids=[cid])
                ingested += 1
            except Exception:
                duplicates += 1
                # si no es duplicado podría ser otro error, pero lo contamos como duplicado en MVP
                continue

    took_ms = int((time.perf_counter() - t0) * 1000)
    return IngestResult(
        tenant_id=tenant_id,
        ingested=ingested,
        duplicates_skipped=duplicates,
        errors=errors,
        chunks_total=total_chunks,
        metrics={"latency_ms": took_ms},
    )