# core/raw_store.py
from __future__ import annotations
import base64
import json
import os
import time
import hashlib
from typing import Dict, Any, List, Tuple, Optional
from datetime import datetime, timezone

DATA_DIR = os.getenv("DATA_DIR", ".data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
CLEAN_DIR = os.path.join(DATA_DIR, "clean")
RAW_FORMAT = os.getenv("RAW_FORMAT", "jsonl").lower()
PERSIST_CLEAN = os.getenv("PERSIST_CLEAN", "false").lower() == "true"
ALLOW_CLIENT_DOC_ID = os.getenv("ALLOW_CLIENT_DOC_ID", "false").lower() == "true"

# ---- Utilidades ----

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def gen_ulid() -> str:
    """ULID-like: 48 bits de tiempo (ms) + 80 bits aleatorios, base32 crockford."""
    ts_ms = int(time.time() * 1000)
    ts_bytes = ts_ms.to_bytes(6, "big", signed=False)
    rand = os.urandom(10)
    enc = base64.b32encode(ts_bytes + rand).decode("ascii").rstrip("=").lower()
    return enc


def compute_sha256(text: str) -> str:
    h = hashlib.sha256()
    h.update(text.encode("utf-8"))
    return "sha256:" + h.hexdigest()


def _tenant_dirs(tenant_id: str) -> Tuple[str, str]:
    raw_tenant = os.path.join(RAW_DIR, tenant_id)
    clean_tenant = os.path.join(CLEAN_DIR, tenant_id)
    os.makedirs(raw_tenant, exist_ok=True)
    os.makedirs(clean_tenant, exist_ok=True)
    return raw_tenant, clean_tenant


def _index_paths(tenant_id: str) -> Tuple[str, str]:
    raw_tenant, _ = _tenant_dirs(tenant_id)
    idx_path = os.path.join(raw_tenant, "index.json")  # doc_id -> meta
    sha_path = os.path.join(raw_tenant, "sha_index.json")  # sha256 -> [doc_id]
    # inicializar si no existen
    if not os.path.exists(idx_path):
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump({}, f)
    if not os.path.exists(sha_path):
        with open(sha_path, "w", encoding="utf-8") as f:
            json.dump({}, f)
    return idx_path, sha_path


def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_json(path: str, obj: Dict[str, Any]) -> None:
    # escritura atómica simple
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---- API de almacenamiento ----

def save_raw(
    tenant_id: str,
    *,
    text: str,
    source: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    doc_id: Optional[str] = None,
    persist_clean: Optional[bool] = None,
    force_reindex: bool = False,
) -> Dict[str, Any]:
    """Guarda un documento raw (y opcional clean). Devuelve doc_id, bytes, duplicate.
    Si detecta duplicado (mismo sha + misma fuente) y no force_reindex, marca duplicate=True.
    """
    persist_clean = PERSIST_CLEAN if persist_clean is None else persist_clean
    source = source or "unknown"

    raw_tenant, clean_tenant = _tenant_dirs(tenant_id)
    idx_path, sha_path = _index_paths(tenant_id)

    # cargar índices
    idx = _read_json(idx_path)
    sha_idx = _read_json(sha_path)

    # preparar registro
    created_at = utc_now_iso()
    sha = compute_sha256(text)

    # checar duplicado por sha+source
    duplicate = False
    existing_docs = sha_idx.get(sha, [])
    for did in existing_docs:
        meta = idx.get(did) or {}
        if meta.get("source") == source:
            duplicate = True
            existing_doc_id = did
            break
    else:
        existing_doc_id = None

    if duplicate and not force_reindex:
        # no sobre-escribimos raw; devolvemos info mínima
        return {
            "doc_id": existing_doc_id,
            "bytes": len(text.encode("utf-8")),
            "sha256": sha,
            "duplicate": True,
            "saved": False,
            "date": (idx.get(existing_doc_id) or {}).get("date"),
        }

    # asignar doc_id
    if not doc_id or not ALLOW_CLIENT_DOC_ID:
        doc_id = gen_ulid()

    # archivo por día
    date = created_at.split("T", 1)[0]
    raw_file = os.path.join(raw_tenant, f"{date}.jsonl")

    # registro en jsonl
    record = {
        "doc_id": doc_id,
        "tenant_id": tenant_id,
        "source": source,
        "text": text,
        "metadata": metadata or {},
        "created_at": created_at,
        "sha256": sha,
    }
    line = json.dumps(record, ensure_ascii=False)
    with open(raw_file, "a", encoding="utf-8") as f:
        f.write(line + "\n")

    # clean opcional
    if persist_clean:
        clean_file = os.path.join(clean_tenant, f"{date}.jsonl")
        clean_record = {k: v for k, v in record.items() if k != "text"}
        # marcamos que es clean y quitamos diferencias
        clean_record["variant"] = "clean"
        with open(clean_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(clean_record, ensure_ascii=False) + "\n")

    # actualizar índices
    idx[doc_id] = {
        "date": date,
        "source": source,
        "sha256": sha,
        "bytes": len(text.encode("utf-8")),
        "created_at": created_at,
    }
    sha_list = sha_idx.get(sha, [])
    if doc_id not in sha_list:
        sha_list.append(doc_id)
    sha_idx[sha] = sha_list

    _write_json(idx_path, idx)
    _write_json(sha_path, sha_idx)

    return {
        "doc_id": doc_id,
        "bytes": len(text.encode("utf-8")),
        "sha256": sha,
        "duplicate": False,
        "saved": True,
        "date": date,
    }


def get_raw(tenant_id: str, doc_id: str, variant: str = "raw") -> Dict[str, Any]:
    idx_path, _ = _index_paths(tenant_id)
    idx = _read_json(idx_path)
    meta = idx.get(doc_id)
    if not meta:
        raise FileNotFoundError("doc_id no encontrado")
    date = meta["date"]
    folder = RAW_DIR if variant == "raw" else CLEAN_DIR
    path = os.path.join(folder, tenant_id, f"{date}.jsonl")
    # escaneo lineal del archivo del día
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("doc_id") == doc_id:
                return rec
    raise FileNotFoundError("Registro no hallado en el archivo del día")


def list_raw(
    tenant_id: str,
    *,
    limit: int = 50,
    cursor: Optional[str] = None,
    source: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Lista documentos usando el índice por doc_id (orden lexicográfico)."""
    idx_path, _ = _index_paths(tenant_id)
    idx = _read_json(idx_path)
    doc_ids = sorted(idx.keys())
    if cursor:
        # avanzar hasta el elemento siguiente al cursor
        try:
            pos = doc_ids.index(cursor) + 1
        except ValueError:
            pos = 0
    else:
        pos = 0

    items: List[Dict[str, Any]] = []
    count = 0
    while pos < len(doc_ids) and count < limit:
        did = doc_ids[pos]
        meta = idx[did]
        if source and meta.get("source") != source:
            pos += 1
            continue
        items.append({
            "doc_id": did,
            "source": meta.get("source"),
            "created_at": meta.get("created_at"),
            "bytes": meta.get("bytes"),
            "sha256": meta.get("sha256"),
        })
        count += 1
        pos += 1

    next_cursor = doc_ids[pos - 1] if pos < len(doc_ids) else None
    return items, next_cursor