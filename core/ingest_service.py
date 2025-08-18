# core/ingest_service.py (reemplaza por esta versión)
from __future__ import annotations
import hashlib
import time
from typing import Dict, Any, List, Tuple, Optional

from pydantic import BaseModel

from core.chunking import normalize_text, split_into_chunks
from core.vectorstore_factory import get_vectorstore
from core.raw_store import save_raw

class IngestDoc(BaseModel):
    text: str
    source: str | None = None
    metadata: Dict[str, Any] | None = None
    doc_id: Optional[str] = None
    force_reindex: bool = False

class IngestResult(BaseModel):
    tenant_id: str
    ingested: int
    duplicates_skipped: int
    errors: int
    chunks_total: int
    raw_saved: int
    raw_bytes: int
    doc_ids: List[str]
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

    raw_saved = 0
    raw_bytes_total = 0
    doc_ids: List[str] = []

    # 1) Guardar RAW (y decidir si reindexar)
    for d in docs:
        text_norm = normalize_text(d.text)
        if not text_norm:
            continue
        raw_info = save_raw(
            tenant_id,
            text=d.text,  # raw original
            source=d.source,
            metadata=d.metadata,
            doc_id=d.doc_id,
            force_reindex=d.force_reindex,
        )
        doc_id = raw_info.get("doc_id")
        doc_ids.append(doc_id)
        if not raw_info.get("duplicate", False):
            raw_saved += 1
            raw_bytes_total += int(raw_info.get("bytes") or 0)
        # si es duplicado y no force_reindex → saltar chunking
        if raw_info.get("duplicate", False) and not d.force_reindex:
            continue

        # 2) Chunking + preparación de lote para vectorstore
        chunks = split_into_chunks(text_norm, chunk_size, overlap)
        for i, c in enumerate(chunks):
            cid = _chunk_id(tenant_id, d.source or "", c, i)
            meta = {
                "tenant_id": tenant_id,
                "source": d.source or "unknown",
                "doc_id": doc_id,
                "chunk_index": i,
                "total_chunks_hint": len(chunks),
                "id": cid,
                "_id": cid,
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

    # 3) Insertar en vectorstore
    if to_add_texts:
        try:
            vs.add_texts(texts=to_add_texts, metadatas=to_add_meta, ids=to_add_ids)
            ingested = len(to_add_ids)
        except Exception:
            for txt, meta, cid in zip(to_add_texts, to_add_meta, to_add_ids):
                try:
                    vs.add_texts(texts=[txt], metadatas=[meta], ids=[cid])
                    ingested += 1
                except Exception:
                    duplicates += 1
                    continue

    took_ms = int((time.perf_counter() - t0) * 1000)
    return IngestResult(
        tenant_id=tenant_id,
        ingested=ingested,
        duplicates_skipped=duplicates,
        errors=errors,
        chunks_total=total_chunks,
        raw_saved=raw_saved,
        raw_bytes=raw_bytes_total,
        doc_ids=doc_ids,
        metrics={"latency_ms": took_ms},
    )