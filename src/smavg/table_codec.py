"""Exact simple-delimited table codec for CSV/TSV-like files."""

from __future__ import annotations

import json
from typing import List, Tuple


def _split_eol(line: str) -> Tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def try_columnar_table(data: bytes, min_rows: int = 20) -> bytes | None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None

    lines = text.splitlines(keepends=True)
    if len(lines) < min_rows:
        return None

    candidates = [",", "\t", "|"]
    best = None
    for delimiter in candidates:
        rows: List[List[str]] = []
        eols: List[str] = []
        width = None
        valid = True
        for line in lines:
            body, eol = _split_eol(line)
            row = body.split(delimiter)
            if len(row) < 2:
                valid = False
                break
            if width is None:
                width = len(row)
            elif len(row) != width:
                valid = False
                break
            rows.append(row)
            eols.append(eol)
        if valid and width:
            score = len(rows) * width
            if best is None or score > best[0]:
                best = (score, delimiter, rows, eols, width)

    if best is None:
        return None

    _, delimiter, rows, eols, width = best
    columns = [[row[index] for row in rows] for index in range(width)]
    document = {
        "v": 1,
        "d": delimiter,
        "e": eols,
        "c": columns,
    }
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if render_columnar_table(payload) != data:
        return None
    return payload


def render_columnar_table(payload: bytes) -> bytes:
    document = json.loads(payload.decode("utf-8"))
    if document.get("v") != 1:
        raise ValueError("Unsupported table codec version")

    delimiter = document.get("d")
    eols = document.get("e")
    columns = document.get("c")
    if not isinstance(delimiter, str) or not isinstance(eols, list) or not isinstance(columns, list):
        raise ValueError("Invalid table codec document")
    if not columns:
        return b""

    height = len(columns[0])
    if len(eols) != height:
        raise ValueError("Table eol count mismatch")
    if any(not isinstance(column, list) or len(column) != height for column in columns):
        raise ValueError("Table column height mismatch")

    lines = []
    for row_index in range(height):
        values = [str(column[row_index]) for column in columns]
        eol = eols[row_index]
        if not isinstance(eol, str):
            raise ValueError("Invalid table eol")
        lines.append(delimiter.join(values) + eol)
    return "".join(lines).encode("utf-8")
