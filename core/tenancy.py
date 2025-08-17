import json
import os
import time
import hmac
import hashlib
import secrets
from typing import Dict, Optional
from dataclasses import dataclass, asdict

@dataclass
class Tenant:
    tenant_id: str
    name: str
    api_key_hash: str
    created_at: float
    limits: Dict[str, int] | None = None

class TenantRegistry:
    def __init__(self, data_dir: str = ".data", salt: str | None = None):
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.path = os.path.join(self.data_dir, "tenants.json")
        self.salt = (salt or os.getenv("API_KEY_SALT") or "dev_salt").encode()
        self._tenants: Dict[str, Tenant] = {}
        self._api_index: Dict[str, str] = {}  # api_key_hash -> tenant_id
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            self._save()
            return
        with open(self.path, "r", encoding="utf-8") as f:
            try:
                raw = json.load(f)
            except json.JSONDecodeError:
                raw = {"tenants": {}}
        for tid, t in raw.get("tenants", {}).items():
            tenant = Tenant(**t)
            self._tenants[tid] = tenant
            self._api_index[tenant.api_key_hash] = tid

    def _save(self):
        out = {"tenants": {tid: asdict(t) for tid, t in self._tenants.items()}}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

    def _hash_api_key(self, api_key: str) -> str:
        return hmac.new(self.salt, api_key.encode("utf-8"), hashlib.sha256).hexdigest()

    def _generate_api_key(self) -> str:
        # URL-safe, 32 bytes ~ 43 chars
        return secrets.token_urlsafe(32)

    def create_tenant(self, tenant_id: str, name: str) -> str:
        if tenant_id in self._tenants:
            raise ValueError(f"tenant_id ya existe: {tenant_id}")
        api_key = self._generate_api_key()
        api_hash = self._hash_api_key(api_key)
        tenant = Tenant(
            tenant_id=tenant_id, name=name, api_key_hash=api_hash, created_at=time.time(), limits={}
        )
        self._tenants[tenant_id] = tenant
        self._api_index[api_hash] = tenant_id
        self._save()
        return api_key  # se muestra UNA vez

    def rotate_api_key(self, tenant_id: str) -> str:
        if tenant_id not in self._tenants:
            raise KeyError("tenant no existe")
        api_key = self._generate_api_key()
        api_hash = self._hash_api_key(api_key)
        self._tenants[tenant_id].api_key_hash = api_hash
        # reconstruir índice simple
        self._api_index = {t.api_key_hash: t.tenant_id for t in self._tenants.values()}
        self._save()
        return api_key

    def resolve_tenant(self, api_key: str) -> Optional[str]:
        api_hash = self._hash_api_key(api_key)
        return self._api_index.get(api_hash)