# core/retrieval.py
from __future__ import annotations
import os
import re
import time
from typing import Dict, Any, List, Tuple

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from core.vectorstore_factory import get_vectorstore

MIN_SCORE = float(os.getenv("MIN_SCORE", "0"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "60"))

_llm = None


def _get_llm():
    global _llm
    if _llm is None:
        _llm = ChatOpenAI(model=os.getenv("LLM_MODEL", "gpt-4o-mini"), temperature=0)
    return _llm

_SYSTEM_PROMPT = (
    "Eres un asistente técnico. Usa EXCLUSIVAMENTE el CONTEXTO para responder en español. "
    "Si la respuesta no está en el contexto, responde: 'No encuentro esa información en la base.'"
)

PROMPT = ChatPromptTemplate.from_template(
    """{system}\n\nCONTEXTO:\n{context}\n\nPREGUNTA:\n{question}\n\nRESPUESTA (clara y en pasos si aplica):"""
)

_fw_re = re.compile(r"^\s*(system:|assistant:|user:)", re.IGNORECASE | re.MULTILINE)
_code_fw_re = re.compile(r"```\s*(system|html)[\s\S]*?```", re.IGNORECASE)
_html_fw_re = re.compile(r"<script[\s\S]*?>[\s\S]*?</script>|on[a-zA-Z]+\s*=\s*\"[\s\S]*?\"", re.IGNORECASE)


def _content_firewall(text: str) -> str:
    text = _fw_re.sub("", text)
    text = _code_fw_re.sub("", text)
    text = _html_fw_re.sub("", text)
    return text


def build_context(docs: List[Tuple[Any, float]] , max_snippet_len: int = 400) -> str:
    lines = []
    for doc, score in docs:
        snippet = doc.page_content[:max_snippet_len]
        lines.append(f"- {snippet}")
    return "\n\n".join(lines)


def retrieve(tenant_id: str, query: str, k: int) -> List[Tuple[Any, float]]:
    vs = get_vectorstore(tenant_id)
    # similarity_search_with_score devuelve pares (Document, score)
    res = vs.similarity_search_with_score(query, k=k)
    if MIN_SCORE > 0:
        res = [(d, s) for (d, s) in res if s is None or s >= MIN_SCORE]
    return res


def rag_answer(tenant_id: str, query: str, k: int) -> Dict[str, Any]:
    t0 = time.perf_counter()
    hits = retrieve(tenant_id, query, k)
    context = build_context(hits)
    context = _content_firewall(context)

    llm = _get_llm()
    prompt_value = PROMPT.invoke({
        "system": _SYSTEM_PROMPT,
        "context": context or "(vacío)",
        "question": query,
    })
    ai_msg = llm.invoke(prompt_value)
    answer = (ai_msg.content or "").strip()

    citations = []
    for doc, score in hits:
        meta = doc.metadata or {}
        citations.append({
            "source": meta.get("source", "unknown"),
            "score": float(score) if score is not None else None,
            "snippet": doc.page_content[:220] + ("..." if len(doc.page_content) > 220 else ""),
            "chunk_id": meta.get("id") or meta.get("_id"),
        })

    took_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "answer": answer if context.strip() else "No encuentro esa información en la base.",
        "citations": citations,
        "metrics": {"latency_ms": took_ms, "k": k, "hits": len(hits)},
    }