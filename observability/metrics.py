# observability/metrics.py
from __future__ import annotations
import os
from prometheus_client import Counter, Histogram, Gauge, CONTENT_TYPE_LATEST, generate_latest
from fastapi import Response

ENABLE_PROM = os.getenv("ENABLE_PROMETHEUS", "false").lower() == "true"

# Histogram buckets en ms (p50..p99 comunes)
_BUCKETS = (50, 100, 200, 300, 500, 750, 1000, 1500, 2500, 5000)

REQUEST_LATENCY_MS = Histogram(
    "atlas_request_latency_ms", "Request latency (ms)", ["route", "tenant_id"], buckets=_BUCKETS
)
RETRIEVAL_LATENCY_MS = Histogram(
    "atlas_retrieval_latency_ms", "Retrieval latency (ms)", ["tenant_id"], buckets=_BUCKETS
)
LLM_LATENCY_MS = Histogram(
    "atlas_llm_latency_ms", "LLM latency (ms)", ["tenant_id", "model"], buckets=_BUCKETS
)

REQUESTS_TOTAL = Counter(
    "atlas_requests_total", "Requests count", ["route", "tenant_id", "status"]
)
LLM_TOKENS_TOTAL = Counter(
    "atlas_llm_tokens_total", "LLM tokens", ["tenant_id", "model", "io"]  # io=in|out|total
)
COST_USD_TOTAL = Counter(
    "atlas_cost_usd_total", "Accumulated LLM cost (USD)", ["tenant_id", "model"]
)
INGESTED_CHUNKS_TOTAL = Counter(
    "atlas_ingested_chunks_total", "Chunks ingested", ["tenant_id"]
)
DUPLICATES_TOTAL = Counter(
    "atlas_duplicates_total", "Duplicate chunks/documents", ["tenant_id"]
)
FEEDBACK_TOTAL = Counter(
    "atlas_feedback_total", "User feedback", ["tenant_id", "label"]  # up|down
)

def metrics_endpoint():
    if not ENABLE_PROM:
        return Response("Prometheus disabled\n", media_type="text/plain")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
