"""Family-aware archive planner."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set

from .delta import sha256_bytes
from .history_pack import encode_history_pack, encode_history_paths, history_pack_codec
from .utils import (
    DEFAULT_HISTORY_GROUP_SIZE,
    DEFAULT_PARENT_HISTORY_GROUP_SIZE,
    TEXT_HISTORY_RATIO_THRESHOLD,
    natural_key,
)


@dataclass(frozen=True)
class FileFact:
    path: Path
    relative: str
    parent: str
    name: str
    suffix: str
    size: int
    sha256: str
    is_text: bool


@dataclass
class PlannedPack:
    kind: str
    label: str
    codec: str
    payload: bytes
    manifest_files: List[Dict[str, object]]
    logical_bytes: int
    fallback_payload_bytes: int
    reason: str


@dataclass
class ArchivePlan:
    files: List[FileFact]
    history_packs: List[PlannedPack]
    fallback_files: List[FileFact]
    report: Dict[str, object]


_VERSION_WORDS = {
    "bak",
    "backup",
    "copy",
    "draft",
    "final",
    "old",
    "rev",
    "revision",
    "version",
}


def build_archive_plan(
    source_dir: Path,
    store_root: Path,
    min_history_group_size: int = DEFAULT_HISTORY_GROUP_SIZE,
) -> ArchivePlan:
    source_dir = Path(source_dir).resolve()
    facts = scan_files(source_dir, store_root)
    if not facts:
        return ArchivePlan(
            files=[],
            history_packs=[],
            fallback_files=[],
            report={
                "planner_version": 1,
                "source_path": str(source_dir),
                "scanned_files": 0,
                "logical_bytes": 0,
                "families": [],
                "fallback": {"files": 0, "logical_bytes": 0, "plan": "none"},
                "rejected": [],
            },
        )

    candidates = _history_candidates(source_dir, facts, min_history_group_size)
    accepted = _select_non_overlapping(candidates)
    covered = {str(item["path"]) for pack in accepted for item in pack.manifest_files}

    if accepted and len(covered) == len(facts):
        whole = encode_history_pack(
            source_dir,
            min_group_size=min_history_group_size,
            exclude_dir=store_root,
        )
        if whole is not None:
            payload, manifest_files = whole
            fallback_payload = sum(_zlib_cost(fact.path) for fact in facts)
            accepted = [
                PlannedPack(
                    kind="history_pack",
                    label="whole-corpus-history",
                    codec=history_pack_codec(payload),
                    payload=payload,
                    manifest_files=manifest_files,
                    logical_bytes=sum(int(item["logical_size"]) for item in manifest_files),
                    fallback_payload_bytes=fallback_payload,
                    reason=(
                        "all files matched detected history families; "
                        "single whole-corpus pack was smallest"
                    ),
                )
            ]
            covered = {str(item["path"]) for item in manifest_files}

    fallback = [fact for fact in facts if fact.relative not in covered]
    report = _build_report(source_dir, facts, accepted, fallback, candidates)
    return ArchivePlan(
        files=facts,
        history_packs=accepted,
        fallback_files=fallback,
        report=report,
    )


def scan_files(source_dir: Path, store_root: Path) -> List[FileFact]:
    source_dir = Path(source_dir).resolve()
    store_root = Path(store_root).resolve()
    facts = []
    for path in sorted(source_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        resolved = path.resolve()
        if _is_relative_to(resolved, store_root):
            continue
        data = path.read_bytes()
        relative = path.relative_to(source_dir).as_posix()
        facts.append(
            FileFact(
                path=path,
                relative=relative,
                parent=path.parent.relative_to(source_dir).as_posix(),
                name=path.name,
                suffix=path.suffix.lower(),
                size=len(data),
                sha256=sha256_bytes(data),
                is_text=_looks_like_text(data),
            )
        )
    return facts


def _history_candidates(
    source_dir: Path,
    facts: List[FileFact],
    min_group_size: int,
) -> List[PlannedPack]:
    groups: Dict[str, List[FileFact]] = {}
    for fact in facts:
        if not fact.is_text:
            continue
        if fact.parent != ".":
            groups.setdefault(f"parent:{fact.parent}", []).append(fact)
        normalized = _normalize_stem(fact.path.stem)
        if normalized:
            groups.setdefault(
                f"name:{fact.parent}:{fact.suffix}:{normalized}",
                [],
            ).append(fact)

    candidates = []
    seen_keys: Set[str] = set()
    for key, group in sorted(groups.items()):
        if key.startswith("parent:") and len(group) < DEFAULT_PARENT_HISTORY_GROUP_SIZE:
            continue
        if len(group) < min_group_size:
            continue
        group = sorted(group, key=lambda item: natural_key(item.relative))
        group_key = "\0".join(item.relative for item in group)
        if group_key in seen_keys:
            continue
        seen_keys.add(group_key)
        if _text_ratio(group) < TEXT_HISTORY_RATIO_THRESHOLD:
            continue
        encoded = encode_history_paths(
            source_dir,
            [item.path for item in group],
            group_name=key,
            min_group_size=min_group_size,
        )
        if encoded is None:
            continue
        payload, manifest_files = encoded
        fallback_payload = sum(_zlib_cost(item.path) for item in group)
        if len(payload) >= fallback_payload:
            continue
        candidates.append(
                PlannedPack(
                    kind="history_pack",
                    label=key,
                    codec=history_pack_codec(payload),
                    payload=payload,
                    manifest_files=manifest_files,
                logical_bytes=sum(item.size for item in group),
                fallback_payload_bytes=fallback_payload,
                reason="text sequence encoded smaller than independent zlib fallback",
            )
        )
    candidates.sort(
        key=lambda item: (
            item.fallback_payload_bytes - len(item.payload),
            item.logical_bytes,
            len(item.manifest_files),
        ),
        reverse=True,
    )
    return candidates


def _select_non_overlapping(candidates: Iterable[PlannedPack]) -> List[PlannedPack]:
    accepted = []
    covered: Set[str] = set()
    for candidate in candidates:
        paths = {str(item["path"]) for item in candidate.manifest_files}
        if paths & covered:
            continue
        accepted.append(candidate)
        covered.update(paths)
    accepted.sort(key=lambda item: item.label)
    return accepted


def _build_report(
    source_dir: Path,
    facts: List[FileFact],
    accepted: List[PlannedPack],
    fallback: List[FileFact],
    candidates: List[PlannedPack],
) -> Dict[str, object]:
    accepted_labels = {pack.label for pack in accepted}
    rejected = [
        {
            "label": candidate.label,
            "family": candidate.kind,
            "files": len(candidate.manifest_files),
            "logical_bytes": candidate.logical_bytes,
            "stored_payload_bytes": len(candidate.payload),
            "reason": "overlapped with a better accepted family",
        }
        for candidate in candidates
        if candidate.label not in accepted_labels
    ]
    return {
        "planner_version": 1,
        "source_path": str(source_dir),
        "scanned_files": len(facts),
        "logical_bytes": sum(fact.size for fact in facts),
        "families": [
            {
                "family": pack.kind,
                "label": pack.label,
                "codec": pack.codec,
                "files": len(pack.manifest_files),
                "logical_bytes": pack.logical_bytes,
                "stored_payload_bytes": len(pack.payload),
                "fallback_payload_bytes": pack.fallback_payload_bytes,
                "payload_ratio": round(pack.logical_bytes / len(pack.payload), 3)
                if pack.payload
                else None,
                "reason": pack.reason,
                "sample_paths": [
                    str(item["path"]) for item in pack.manifest_files[:5]
                ],
            }
            for pack in accepted
        ],
        "fallback": {
            "files": len(fallback),
            "logical_bytes": sum(fact.size for fact in fallback),
            "plan": "safe_object_store" if fallback else "none",
            "reason": (
                "no winning structural family found; store with exact per-file codecs"
                if fallback
                else "all files covered by structural families"
            ),
            "sample_paths": [fact.relative for fact in fallback[:5]],
        },
        "rejected": rejected,
    }


def _looks_like_text(data: bytes) -> bool:
    if not data:
        return True
    sample = data[:8192]
    if b"\x00" in sample:
        return False
    control = 0
    for byte in sample:
        if byte in {9, 10, 12, 13}:
            continue
        if byte < 32:
            control += 1
    return control / len(sample) < 0.02


def _normalize_stem(stem: str) -> str:
    value = stem.lower()
    value = re.sub(r"0x[0-9a-f]+", " ", value)
    value = re.sub(r"\b[0-9a-f]{7,}\b", " ", value)
    value = re.sub(r"\b\d{4}[-_]\d{2}[-_]\d{2}\b", " ", value)
    value = re.sub(r"\bv?\d+\b", " ", value)
    tokens = re.split(r"[^a-z0-9]+", value)
    kept = [
        token
        for token in tokens
        if token
        and token not in _VERSION_WORDS
        and not token.isdigit()
        and not re.fullmatch(r"v\d+", token)
    ]
    return "-".join(kept)


def _text_ratio(group: List[FileFact]) -> float:
    if not group:
        return 0.0
    return sum(1 for item in group if item.is_text) / len(group)


def _zlib_cost(path: Path) -> int:
    return len(zlib.compress(path.read_bytes(), level=9))


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
