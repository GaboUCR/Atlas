# core/retrieval.py
from __future__ import annotations
import os, re, time
from typing import Dict, Any, List, Tuple

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from core.vectorstore_factory import get_vectorstore
from core.pricing import estimate_cost_usd
from observability.metrics import RETRIEVAL_LATENCY_MS, LLM_LATENCY_MS, LLM_TOKENS_TOTAL, COST_USD_TOTAL
from observability.tracing import get_callbacks

MAX_DISTANCE = float(os.getenv("MAX_DISTANCE", "inf"))

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
    """{system}

CONTEXTO:
{context}

PREGUNTA:
{question}

RESPUESTA (clara y en pasos si aplica):"""
)

_fw_re = re.compile(r"^\s*(system:|assistant:|user:)", re.IGNORECASE | re.MULTILINE)
_code_fw_re = re.compile(r"```\s*(system|html)[\s\S]*?```", re.IGNORECASE)
_html_fw_re = re.compile(r"<script[\s\S]*?>[\s\S]*?</script>|on[a-zA-Z]+\s*=\s*\"[\s\S]*?\"", re.IGNORECASE)

def _content_firewall(text: str) -> str:
    text = _fw_re.sub("", text)
    text = _code_fw_re.sub("", text)
    text = _html_fw_re.sub("", text)
    return text

def _distance_to_relevance(s: float | None) -> float | None:
    if s is None:
        return None
    try:
        d = float(s)
        rel = 1.0 / (1.0 + max(d, 0.0))
        return round(rel, 3)
    except Exception:
        return None

def build_context(docs: List[Tuple[Any, float]], max_snippet_len: int = 400) -> str:
    lines = []
    for doc, score in docs:
        meta = doc.metadata or {}
        src = meta.get("source", "unknown")
        snippet = doc.page_content[:max_snippet_len]
        lines.append(f"- [Fuente: {src}] {snippet}")
    return "\n\n".join(lines)

def retrieve(tenant_id: str, query: str, k: int) -> List[Tuple[Any, float]]:
    vs = get_vectorstore(tenant_id)
    t0 = time.perf_counter()
    res = vs.similarity_search_with_score(query, k=k)
    took_ms = int((time.perf_counter() - t0) * 1000)
    RETRIEVAL_LATENCY_MS.labels(tenant_id=tenant_id).observe(took_ms)
    if MAX_DISTANCE != float("inf"):
        res = [(d, s) for (d, s) in res if (s is None) or (s <= MAX_DISTANCE)]
    return res

def _token_usage(ai_msg) -> tuple[int, int, int, str]:
    # intenta recuperar tokens y modelo de distintos campos
    model = getattr(ai_msg, "response_metadata", {}).get("model_name") or os.getenv("LLM_MODEL", "unknown")
    usage = getattr(ai_msg, "response_metadata", {}).get("token_usage") or {}
    total = usage.get("total_tokens")
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    # fallback LangChain normalized
    um = getattr(ai_msg, "usage_metadata", None)
    if um:
        total = um.get("total_tokens", total)
        prompt = um.get("input_tokens", prompt)
        completion = um.get("output_tokens", completion)
    return int(prompt or 0), int(completion or 0), int(total or 0), model

def rag_answer(tenant_id: str, query: str, k: int) -> Dict[str, Any]:
    hits = retrieve(tenant_id, query, k)
    context = _content_firewall(build_context(hits))

    llm = _get_llm()
    prompt_value = PROMPT.invoke({
        "system": _SYSTEM_PROMPT,
        "context": context or "(vacío)",
        "question": query,
    })

    t0 = time.perf_counter()
    # callbacks (Langfuse / LangSmith si están habilitados)
    cbs = get_callbacks()
    ai_msg = llm.invoke(prompt_value, config={"callbacks": cbs} if cbs else None)
    llm_ms = int((time.perf_counter() - t0) * 1000)

    LLM_LATENCY_MS.labels(tenant_id=tenant_id, model=os.getenv("LLM_MODEL", "unknown")).observe(llm_ms)

    p_tokens, c_tokens, t_tokens, model = _token_usage(ai_msg)
    for io, n in (("in", p_tokens), ("out", c_tokens), ("total", t_tokens)):
        LLM_TOKENS_TOTAL.labels(tenant_id=tenant_id, model=model, io=io).inc(n)

    cost = estimate_cost_usd(model, p_tokens, c_tokens)
    COST_USD_TOTAL.labels(tenant_id=tenant_id, model=model).inc(cost)

    answer = (ai_msg.content or "").strip()
    citations = []
    for doc, score in hits:
        meta = doc.metadata or {}
        citations.append({
            "source": meta.get("source", "unknown"),
            "distance": float(score) if score is not None else None,
            "relevance": _distance_to_relevance(score),
            "snippet": doc.page_content[:220] + ("..." if len(doc.page_content) > 220 else ""),
            "chunk_id": meta.get("id") or meta.get("_id"),
            "doc_id": meta.get("doc_id"),
        })

    if not context.strip():
        answer = "No encuentro esa información en la base."

    return {
        "answer": answer,
        "citations": citations,
        "metrics": {
            "llm_latency_ms": llm_ms,
            "tokens_in": p_tokens,
            "tokens_out": c_tokens,
            "tokens_total": t_tokens,
            "model": model,
            "cost_usd": round(cost, 6),
        },
    }
