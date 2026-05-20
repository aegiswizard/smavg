"""Byte-perfect line-oriented binary deltas for the Phase 1 prototype."""

from __future__ import annotations

import base64
import hashlib
import json
from difflib import SequenceMatcher
from typing import Iterable, List


class DeltaError(ValueError):
    """Raised when a delta cannot be applied safely."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _split_parts(data: bytes) -> List[bytes]:
    if not data:
        return []
    return data.splitlines(keepends=True)


def _offsets(parts: Iterable[bytes]) -> List[int]:
    result = [0]
    total = 0
    for part in parts:
        total += len(part)
        result.append(total)
    return result


def create_delta(base: bytes, target: bytes) -> bytes:
    """Create a JSON delta that reconstructs target from base.

    The algorithm is intentionally conservative and dependency-free. It diffs
    line chunks for text-like files and stores replacement chunks as base64.
    Binary files still round-trip, but may fall back to storing most bytes.
    """

    base_parts = _split_parts(base)
    target_parts = _split_parts(target)
    base_offsets = _offsets(base_parts)
    matcher = SequenceMatcher(None, base_parts, target_parts, autojunk=True)

    ops = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            start = base_offsets[i1]
            end = base_offsets[i2]
            if end > start:
                ops.append(["copy", start, end])
            continue

        if tag in {"insert", "replace"}:
            chunk = b"".join(target_parts[j1:j2])
            if chunk:
                ops.append(["data", base64.b64encode(chunk).decode("ascii")])
            continue

        if tag == "delete":
            continue

        raise DeltaError(f"Unknown diff opcode: {tag}")

    document = {
        "v": 1,
        "base_sha256": sha256_bytes(base),
        "target_sha256": sha256_bytes(target),
        "target_size": len(target),
        "ops": ops,
    }
    return json.dumps(document, separators=(",", ":")).encode("utf-8")


def apply_delta(base: bytes, delta: bytes) -> bytes:
    try:
        document = json.loads(delta.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeltaError("Delta payload is not valid JSON") from exc

    if document.get("v") != 1:
        raise DeltaError("Unsupported delta version")

    expected_base = document.get("base_sha256")
    if expected_base != sha256_bytes(base):
        raise DeltaError("Base content does not match delta")

    out = []
    for op in document.get("ops", []):
        if not isinstance(op, list) or not op:
            raise DeltaError("Invalid delta operation")

        kind = op[0]
        if kind == "copy":
            if len(op) != 3:
                raise DeltaError("Invalid copy operation")
            start, end = op[1], op[2]
            if not isinstance(start, int) or not isinstance(end, int):
                raise DeltaError("Copy offsets must be integers")
            if start < 0 or end < start or end > len(base):
                raise DeltaError("Copy offsets are outside the base content")
            out.append(base[start:end])
            continue

        if kind == "data":
            if len(op) != 2 or not isinstance(op[1], str):
                raise DeltaError("Invalid data operation")
            try:
                out.append(base64.b64decode(op[1].encode("ascii"), validate=True))
            except ValueError as exc:
                raise DeltaError("Delta data chunk is not valid base64") from exc
            continue

        raise DeltaError(f"Unknown delta operation: {kind}")

    result = b"".join(out)
    if len(result) != document.get("target_size"):
        raise DeltaError("Reconstructed size does not match delta metadata")
    if sha256_bytes(result) != document.get("target_sha256"):
        raise DeltaError("Reconstructed SHA-256 does not match delta metadata")
    return result
