# core/pricing.py
from __future__ import annotations
import json, os

_DEFAULT = {}

def load_pricing() -> dict:
    path = os.getenv("PRICING_FILE")
    if not path or not os.path.exists(path):
        return _DEFAULT
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return _DEFAULT

def estimate_cost_usd(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    tbl = load_pricing().get(model, {})
    # precios por 1k tokens
    p_in = float(tbl.get("prompt", 0.0))
    p_out = float(tbl.get("completion", 0.0))
    return (prompt_tokens / 1000.0) * p_in + (completion_tokens / 1000.0) * p_out
