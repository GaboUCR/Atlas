# observability/tracing.py
from __future__ import annotations
import os
import uuid

LANGFUSE_ENABLE = os.getenv("LANGFUSE_ENABLE", "false").lower() == "true"

_langfuse_handler = None
def _init_langfuse():
    global _langfuse_handler
    if not LANGFUSE_ENABLE:
        return None
    if _langfuse_handler is not None:
        return _langfuse_handler
    try:
        from langfuse import Langfuse
        from langfuse.callback import CallbackHandler
        lf = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST"),
        )
        _langfuse_handler = CallbackHandler(langfuse=lf)
    except Exception:
        _langfuse_handler = None
    return _langfuse_handler

def new_trace_id() -> str:
    return uuid.uuid4().hex

def get_callbacks():
    cbs = []
    h = _init_langfuse()
    if h:
        cbs.append(h)
    # LangSmith se activa por env (LANGCHAIN_TRACING_V2=true, LANGCHAIN_API_KEY, LANGCHAIN_PROJECT)
    return cbs
