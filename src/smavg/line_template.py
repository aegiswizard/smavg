"""Exact line-pattern codec for repetitive logs and line-oriented text."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Dict, List, Tuple


TOKEN_RE = re.compile(r"[A-Za-z0-9_./:@+-]+|[^A-Za-z0-9_./:@+-]+")


def _split_eol(line: str) -> Tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def _tokenize(body: str) -> List[str]:
    if not body:
        return []
    return [match.group(0) for match in TOKEN_RE.finditer(body)]


def _is_variable_token(token: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9]", token))


def try_line_template(data: bytes, min_lines: int = 20) -> bytes | None:
    try:
        text = data.decode("latin1")
    except UnicodeDecodeError:
        return None

    lines = text.splitlines(keepends=True)
    if len(lines) < min_lines:
        return None

    parsed = []
    groups: Dict[Tuple[Tuple[str, str], ...], List[int]] = defaultdict(list)
    for line in lines:
        body, eol = _split_eol(line)
        tokens = _tokenize(body)
        broad = tuple(
            ("v", "") if _is_variable_token(token) else ("l", token)
            for token in tokens
        )
        index = len(parsed)
        parsed.append((tokens, eol, broad))
        groups[broad].append(index)

    encoded_groups: List[Dict[str, Any]] = []
    group_ids: Dict[Tuple[Tuple[str, str], ...], int] = {}
    encoded_lines = []

    for broad, indexes in sorted(groups.items(), key=lambda item: item[0]):
        group_id = len(encoded_groups)
        group_ids[broad] = group_id
        width = len(parsed[indexes[0]][0])
        template = []

        for position in range(width):
            values = [parsed[index][0][position] for index in indexes]
            if broad[position][0] == "l" or all(value == values[0] for value in values):
                template.append(["l", values[0]])
            else:
                template.append(["v"])

        encoded_groups.append({"t": template})

    for tokens, eol, broad in parsed:
        group = encoded_groups[group_ids[broad]]
        values = []
        for token, part in zip(tokens, group["t"]):
            if part[0] == "v":
                values.append(token)
        encoded_lines.append([group_ids[broad], values, eol])

    document = {
        "v": 1,
        "g": encoded_groups,
        "l": encoded_lines,
    }
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("latin1")
    if render_line_template(payload) != data:
        return None
    return payload


def render_line_template(payload: bytes) -> bytes:
    document = json.loads(payload.decode("latin1"))
    if document.get("v") != 1:
        raise ValueError("Unsupported line template version")

    groups = document.get("g")
    lines = document.get("l")
    if not isinstance(groups, list) or not isinstance(lines, list):
        raise ValueError("Invalid line template document")

    out = []
    for entry in lines:
        if not isinstance(entry, list) or len(entry) != 3:
            raise ValueError("Invalid encoded line")
        group_id, values, eol = entry
        if not isinstance(group_id, int) or group_id < 0 or group_id >= len(groups):
            raise ValueError("Invalid line group id")
        if not isinstance(values, list) or not isinstance(eol, str):
            raise ValueError("Invalid line values")

        value_index = 0
        parts = []
        for part in groups[group_id].get("t", []):
            if not isinstance(part, list) or not part:
                raise ValueError("Invalid line template part")
            if part[0] == "l":
                parts.append(str(part[1]))
            elif part[0] == "v":
                if value_index >= len(values):
                    raise ValueError("Missing line variable")
                parts.append(str(values[value_index]))
                value_index += 1
            else:
                raise ValueError("Invalid line template part kind")
        if value_index != len(values):
            raise ValueError("Unused line variables")
        out.append("".join(parts) + eol)

    return "".join(out).encode("latin1")
