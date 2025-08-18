# observability/logging.py
from __future__ import annotations
import json
import logging
import os
from datetime import datetime

TRUNC = int(os.getenv("LOG_TRUNCATE_CHARS", "120"))
REDACT = os.getenv("LOG_PII_REDACTION", "true").lower() == "true"

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "t": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "lvl": record.levelname,
            "msg": record.getMessage(),
        }
        if hasattr(record, "extra"):
            payload.update(record.extra)  # type: ignore[attr-defined]
        return json.dumps(payload, ensure_ascii=False)

def setup_logging():
    root = logging.getLogger()
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    root.setLevel(level)
    # limpiar handlers existentes
    for h in list(root.handlers):
        root.removeHandler(h)
    ch = logging.StreamHandler()
    ch.setFormatter(JsonFormatter())
    root.addHandler(ch)

def safe_preview(text: str | None) -> str | None:
    if not text:
        return text
    s = text.replace("\n", " ")
    if REDACT:
        # redacción muy ligera (emails y teléfonos simples)
        import re
        s = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", "[email]", s)
        s = re.sub(r"\+?\d[\d\- ]{7,}\d", "[phone]", s)
    if len(s) > TRUNC:
        s = s[:TRUNC] + "…"
    return s
