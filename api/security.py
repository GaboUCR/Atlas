from typing import Optional
from fastapi import Header, HTTPException, status, Depends
import os
import time

from core.tenancy import TenantRegistry

# --- Rate limiter (token bucket en memoria) ---
class RateLimiter:
    def __init__(self, rps: float, burst: int):
        self.rps = rps
        self.burst = burst
        self.buckets = {}  # key -> {tokens, ts}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        b = self.buckets.get(key)
        if not b:
            self.buckets[key] = {"tokens": self.burst - 1, "ts": now}
            return True
        elapsed = max(0.0, now - b["ts"])
        refill = elapsed * self.rps
        tokens = min(self.burst, b["tokens"] + refill)
        if tokens >= 1.0:
            tokens -= 1.0
            self.buckets[key] = {"tokens": tokens, "ts": now}
            return True
        else:
            self.buckets[key] = {"tokens": tokens, "ts": now}
            return False

# Dependencias globales (se inicializan en app)
REGISTRY: Optional[TenantRegistry] = None
RATE_LIMITER: Optional[RateLimiter] = None

async def admin_auth(x_admin_key: str = Header(default="")) -> None:
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected or x_admin_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Admin auth inválida")

async def resolve_tenant_id(x_api_key: str = Header(...)) -> str:
    if REGISTRY is None:
        raise HTTPException(status_code=500, detail="Registry no inicializado")
    tid = REGISTRY.resolve_tenant(x_api_key)
    if not tid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key inválida")
    return tid

async def rate_limit(x_api_key: str = Header(...)) -> None:
    if RATE_LIMITER is None:
        return
    if not RATE_LIMITER.allow(x_api_key):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit excedido")