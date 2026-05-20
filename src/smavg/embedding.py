"""Local semantic sketches used before the MiniLM/ChromaDB path exists."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Iterable, List


TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_']+|\d+(?:\.\d+)?")


def _tokens(text: str) -> Iterable[str]:
    for match in TOKEN_RE.finditer(text.lower()):
        token = match.group(0)
        if len(token) > 48:
            token = token[:48]
        yield token


def _stable_hash(value: str) -> int:
    digest = hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=False)


def embed_bytes(data: bytes, dimensions: int = 256) -> List[float]:
    """Return a normalized local vector for semantic candidate selection.

    This is a dependency-free placeholder for the production MiniLM embedding
    path. It captures token overlap for text and falls back to a byte histogram
    for binary-ish content.
    """

    vector = [0.0] * dimensions
    text = data.decode("utf-8", errors="ignore")
    token_count = 0

    for token in _tokens(text):
        token_count += 1
        value = _stable_hash(token)
        index = value % dimensions
        sign = 1.0 if value & (1 << 63) else -1.0
        vector[index] += sign

    if token_count < 4:
        for byte in data:
            vector[byte % dimensions] += 1.0

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [round(value / norm, 8) for value in vector]


def cosine(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def vector_to_json(vector: List[float]) -> str:
    return json.dumps(vector, separators=(",", ":"))


def vector_from_json(value: str) -> List[float]:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        return []
    return [float(item) for item in parsed]
