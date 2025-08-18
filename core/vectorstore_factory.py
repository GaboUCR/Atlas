# core/vectorstore_factory.py
from __future__ import annotations
import os
import re
from functools import lru_cache
from typing import Dict

from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma

COLLECTION_PREFIX = os.getenv("COLLECTION_PREFIX", "kb_")

_name_re = re.compile(r"[^a-zA-Z0-9._-]")

def _sanitize_collection_name(name: str) -> str:
    name = name.strip().lower()
    name = _name_re.sub("-", name)
    # fuerza longitud mínima 3 y que empiece/termine con [a-z0-9]
    base = f"{COLLECTION_PREFIX}{name}"
    if len(base) < 3:
        base = f"{COLLECTION_PREFIX}tenant"
    if not base[0].isalnum():
        base = f"kb{base}"
    if not base[-1].isalnum():
        base = f"{base}0"
    return base

@lru_cache(maxsize=1)
def get_embeddings_model():
    model = os.getenv("EMBEDDINGS_MODEL", "text-embedding-3-small")
    return OpenAIEmbeddings(model=model)

_vectorstores: Dict[str, Chroma] = {}

def get_vectorstore(tenant_id: str) -> Chroma:
    """Devuelve/crea un Chroma por tenant (cacheado)."""
    if tenant_id in _vectorstores:
        return _vectorstores[tenant_id]
    persist_dir = os.path.join("chroma_db", tenant_id)
    os.makedirs(persist_dir, exist_ok=True)
    collection_name = _sanitize_collection_name(tenant_id)
    vs = Chroma(
        collection_name=collection_name,
        persist_directory=persist_dir,
        embedding_function=get_embeddings_model(),
    )
    _vectorstores[tenant_id] = vs
    return vs