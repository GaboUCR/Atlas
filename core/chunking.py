# core/chunking.py
from __future__ import annotations
import re
import unicodedata
from typing import List

__all__ = ["normalize_text", "split_into_chunks"]

_ws_re = re.compile(r"\s+")

def normalize_text(text: str) -> str:
    """Normaliza texto: Unicode NFC, recorta espacios duplicados y bordes."""
    if text is None:
        return ""
    t = unicodedata.normalize("NFC", text)
    t = t.replace("\r", "\n")
    t = _ws_re.sub(" ", t)
    return t.strip()

def split_into_chunks(text: str, size: int = 1200, overlap: int = 200) -> List[str]:
    """Divide texto en ventanas con solapamiento fijo (por caracteres).
    Regresa lista de fragmentos no vacíos.
    """
    text = normalize_text(text)
    if not text:
        return []
    size = max(200, int(size))
    overlap = max(0, min(int(overlap), size - 50))
    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(n, start + size)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = end - overlap
        if start <= 0:
            # evita bucles
            start = end
    return chunks