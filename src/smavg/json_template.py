"""Deterministic JSON template/variable encoding.

The encoder is intentionally strict: it only claims a JSON file when the parsed
object can be serialized back to exactly the same bytes in Smavg canonical JSON
format. If exact reconstruction is not proven, callers must fall back to normal
byte storage.
"""

from __future__ import annotations

import json
from typing import Any, List, Tuple


CANONICAL_JSON_KWARGS = {
    "ensure_ascii": False,
    "indent": 2,
    "sort_keys": True,
}

MAX_TEMPLATE_DEPTH = 128


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, **CANONICAL_JSON_KWARGS) + "\n").encode("utf-8")


def extract_template(value: Any) -> Tuple[Any, List[Any]]:
    variables: List[Any] = []

    def walk(item: Any) -> Any:
        if isinstance(item, dict):
            return ["d", [[key, walk(item[key])] for key in sorted(item)]]
        if isinstance(item, list):
            return ["l", [walk(child) for child in item]]
        index = len(variables)
        variables.append(item)
        return ["v", index]

    return walk(value), variables


def template_to_bytes(template: Any) -> bytes:
    return json.dumps(
        template,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def variables_to_bytes(variables: List[Any]) -> bytes:
    return json.dumps(
        variables,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def apply_template(template: Any, variables: List[Any]) -> Any:
    def walk(node: Any, depth: int) -> Any:
        if depth > MAX_TEMPLATE_DEPTH:
            raise ValueError("JSON template exceeds maximum depth")
        if not isinstance(node, list) or len(node) != 2:
            raise ValueError("Invalid JSON template node")

        kind, payload = node
        if kind == "v":
            if not isinstance(payload, int) or payload < 0 or payload >= len(variables):
                raise ValueError("Invalid JSON template variable reference")
            return variables[payload]

        # "c" nodes are introduced by refine_template_constants when a value is
        # constant across a shared template family.
        if kind == "c":
            return payload

        if kind == "d":
            if not isinstance(payload, list):
                raise ValueError("Invalid JSON template dict payload")
            result = {}
            for entry in payload:
                if not isinstance(entry, list) or len(entry) != 2:
                    raise ValueError("Invalid JSON template dict entry")
                key, child = entry
                if not isinstance(key, str):
                    raise ValueError("Invalid JSON template dict key")
                result[key] = walk(child, depth + 1)
            return result

        if kind == "l":
            if not isinstance(payload, list):
                raise ValueError("Invalid JSON template list payload")
            return [walk(child, depth + 1) for child in payload]

        raise ValueError(f"Invalid JSON template node kind: {kind}")

    return walk(template, 0)


def try_json_template_parts(data: bytes) -> Tuple[Any, List[Any]] | None:
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    if canonical_json_bytes(parsed) != data:
        return None

    template, variables = extract_template(parsed)
    rebuilt = apply_template(template, variables)
    if canonical_json_bytes(rebuilt) != data:
        return None
    return template, variables


def try_json_template(data: bytes) -> Tuple[bytes, bytes] | None:
    parts = try_json_template_parts(data)
    if parts is None:
        return None

    template, variables = parts
    return template_to_bytes(template), variables_to_bytes(variables)


def refine_template_constants(
    template: Any,
    variable_lists: List[List[Any]],
) -> Tuple[Any, List[List[Any]]]:
    if not variable_lists:
        return template, []

    width = len(variable_lists[0])
    if any(len(values) != width for values in variable_lists):
        raise ValueError("Variable lists do not share the same width")

    constant = []
    for index in range(width):
        first = variable_lists[0][index]
        constant.append(all(values[index] == first for values in variable_lists[1:]))

    varying_indices = [index for index, is_constant in enumerate(constant) if not is_constant]
    index_map = {old: new for new, old in enumerate(varying_indices)}

    def walk(node: Any) -> Any:
        if not isinstance(node, list) or len(node) != 2:
            raise ValueError("Invalid JSON template node")

        kind, payload = node
        if kind == "v":
            old_index = int(payload)
            if constant[old_index]:
                return ["c", variable_lists[0][old_index]]
            return ["v", index_map[old_index]]
        if kind == "d":
            return ["d", [[key, walk(child)] for key, child in payload]]
        if kind == "l":
            return ["l", [walk(child) for child in payload]]
        if kind == "c":
            return node
        raise ValueError(f"Invalid JSON template node kind: {kind}")

    refined_values = [
        [values[index] for index in varying_indices]
        for values in variable_lists
    ]
    return walk(template), refined_values


def render_json_template(template_bytes: bytes, variables_bytes: bytes) -> bytes:
    template = json.loads(template_bytes.decode("utf-8"))
    variables = json.loads(variables_bytes.decode("utf-8"))
    if not isinstance(variables, list):
        raise ValueError("JSON template variables must be a list")
    return canonical_json_bytes(apply_template(template, variables))
