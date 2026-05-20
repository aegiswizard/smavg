"""Shared small utilities for Smavg internals."""

from __future__ import annotations

from typing import List


DEFAULT_HISTORY_GROUP_SIZE = 4
DEFAULT_PARENT_HISTORY_GROUP_SIZE = 8
DEFAULT_HISTORY_CHECKPOINT_INTERVAL = 2048
TEXT_HISTORY_RATIO_THRESHOLD = 0.80


def natural_key(value: str) -> List[object]:
    parts: List[object] = []
    current = []
    current_is_digit = None
    for char in value:
        is_digit = char.isdigit()
        if current and is_digit != current_is_digit:
            token = "".join(current)
            parts.append(int(token) if current_is_digit else token.lower())
            current = []
        current.append(char)
        current_is_digit = is_digit
    if current:
        token = "".join(current)
        parts.append(int(token) if current_is_digit else token.lower())
    return parts
