"""Snapshot-level codecs for real versioned file histories."""

from __future__ import annotations

import io
import json
import lzma
import struct
import zlib
from difflib import SequenceMatcher
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Dict, Iterable, Iterator, List, Optional, Tuple

from .utils import (
    DEFAULT_HISTORY_CHECKPOINT_INTERVAL,
    DEFAULT_HISTORY_GROUP_SIZE,
    DEFAULT_PARENT_HISTORY_GROUP_SIZE,
    natural_key,
)


HISTORY_PACK_V2_CODEC = "history_pack_v2_lzma"
HISTORY_PACK_V3_CODEC = "history_pack_v3_chunked_lzma"
HISTORY_PACK_V4_CODEC = "history_pack_v4_merkle_lzma"
_V3_MAGIC = b"SMHSTV3\n"
_V4_MAGIC = b"SMHSTV4\n"
_V3_HEADER = struct.Struct("<8sQQ32s")


def _encode_bytes(data: bytes) -> str:
    return data.decode("latin1")


def _decode_bytes(value: str) -> bytes:
    return value.encode("latin1")


def _digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def _self_check_history_payload(
    source_dir: Path,
    payload: bytes,
    manifest_files: List[Dict[str, object]],
) -> None:
    expected_paths = [str(item["path"]) for item in manifest_files]
    seen_count = 0
    for seen_count, (relative, data) in enumerate(iter_history_pack_bytes(payload), start=1):
        expected_index = seen_count - 1
        if expected_index >= len(expected_paths):
            raise ValueError("History-pack self-check produced too many files")
        expected_path = expected_paths[expected_index]
        if relative != expected_path:
            raise ValueError(
                f"History-pack self-check path order mismatch: {relative} != {expected_path}"
            )
        if data != (source_dir / relative).read_bytes():
            raise ValueError(f"History-pack self-check failed for {relative}")
    if seen_count != len(expected_paths):
        raise ValueError("History-pack self-check file count mismatch")


def _update_history_root(hasher, relative: str, data: bytes) -> None:
    path_bytes = relative.encode("utf-8")
    hasher.update(len(path_bytes).to_bytes(4, "little"))
    hasher.update(path_bytes)
    hasher.update(len(data).to_bytes(8, "little"))
    hasher.update(sha256(data).digest())


def _validate_relative_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    normalized = path.as_posix()
    if normalized in {"", "."}:
        raise ValueError("History-pack path cannot be empty")
    if normalized.startswith("/") or normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"Unsafe history-pack path: {value}")
    if "/../" in f"/{normalized}/":
        raise ValueError(f"Unsafe history-pack path: {value}")
    return normalized


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _line_delta(base: bytes, target: bytes) -> List[list]:
    base_lines = base.splitlines(keepends=True)
    target_lines = target.splitlines(keepends=True)
    matcher = SequenceMatcher(None, base_lines, target_lines, autojunk=True)
    ops = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            ops.append(["=", i1, i2])
        elif tag in {"insert", "replace"}:
            chunk = b"".join(target_lines[j1:j2])
            if chunk:
                ops.append(["+", _encode_bytes(chunk)])
        elif tag == "delete":
            continue
        else:
            raise ValueError(f"Unknown delta opcode: {tag}")
    return ops


def _apply_line_delta(base: bytes, ops: List[list]) -> bytes:
    base_lines = base.splitlines(keepends=True)
    out = []
    for op in ops:
        if not isinstance(op, list) or not op:
            raise ValueError("Invalid history-pack operation")
        if op[0] == "=":
            if len(op) != 3:
                raise ValueError("Invalid history-pack copy operation")
            start, end = op[1], op[2]
            if not isinstance(start, int) or not isinstance(end, int):
                raise ValueError("History-pack copy offsets must be integers")
            if start < 0 or end < start or end > len(base_lines):
                raise ValueError("History-pack copy offsets are out of range")
            out.extend(base_lines[start:end])
        elif op[0] == "+":
            if len(op) != 2 or not isinstance(op[1], str):
                raise ValueError("Invalid history-pack insert operation")
            out.append(_decode_bytes(op[1]))
        else:
            raise ValueError(f"Unknown history-pack operation: {op[0]}")
    return b"".join(out)


def history_pack_codec(payload: bytes) -> str:
    if payload.startswith(_V4_MAGIC):
        return HISTORY_PACK_V4_CODEC
    return HISTORY_PACK_V3_CODEC if payload.startswith(_V3_MAGIC) else HISTORY_PACK_V2_CODEC


def encode_history_pack(
    source_dir: Path,
    min_group_size: int = DEFAULT_PARENT_HISTORY_GROUP_SIZE,
    exclude_dir: Optional[Path] = None,
    checkpoint_interval: int = DEFAULT_HISTORY_CHECKPOINT_INTERVAL,
) -> Tuple[bytes, List[Dict[str, object]]] | None:
    source_dir = Path(source_dir).resolve()
    exclude_root = Path(exclude_dir).resolve() if exclude_dir is not None else None
    files = []
    for path in sorted(source_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if exclude_root is not None and _is_relative_to(path.resolve(), exclude_root):
            continue
        files.append(path)
    if not files:
        return None

    grouped: Dict[str, List[Path]] = {}
    for path in files:
        relative_parent = path.parent.relative_to(source_dir).as_posix()
        grouped.setdefault(relative_parent, []).append(path)

    if not any(len(group) >= min_group_size for group in grouped.values()):
        return None
    return _encode_best_grouped_paths(
        source_dir=source_dir,
        grouped=grouped,
        min_group_size=min_group_size,
        checkpoint_interval=checkpoint_interval,
    )


def encode_history_paths(
    source_dir: Path,
    paths: Iterable[Path],
    group_name: str,
    min_group_size: int = DEFAULT_HISTORY_GROUP_SIZE,
    checkpoint_interval: int = DEFAULT_HISTORY_CHECKPOINT_INTERVAL,
) -> Tuple[bytes, List[Dict[str, object]]] | None:
    source_dir = Path(source_dir).resolve()
    files = []
    seen = set()
    for path in paths:
        resolved = Path(path).resolve()
        original = Path(path)
        if original.is_symlink() or not resolved.is_file():
            continue
        relative = resolved.relative_to(source_dir).as_posix()
        if relative in seen:
            continue
        seen.add(relative)
        files.append(resolved)
    files = sorted(files, key=lambda item: natural_key(item.relative_to(source_dir).as_posix()))
    if len(files) < min_group_size:
        return None

    return _encode_best_grouped_paths(
        source_dir=source_dir,
        grouped={group_name: files},
        min_group_size=min_group_size,
        checkpoint_interval=checkpoint_interval,
    )


def _encode_best_grouped_paths(
    source_dir: Path,
    grouped: Dict[str, List[Path]],
    min_group_size: int,
    checkpoint_interval: int,
) -> Tuple[bytes, List[Dict[str, object]]] | None:
    chunked = _encode_v4_grouped_paths(
        source_dir=source_dir,
        grouped=grouped,
        min_group_size=min_group_size,
        checkpoint_interval=checkpoint_interval,
    )
    total_files = sum(len(group) for group in grouped.values())
    legacy = None
    if total_files <= checkpoint_interval:
        legacy = _encode_legacy_grouped_paths(
            source_dir=source_dir,
            grouped=grouped,
            min_group_size=min_group_size,
        )
    if legacy is not None and (chunked is None or len(legacy[0]) < len(chunked[0])):
        return legacy
    return chunked


def _encode_grouped_paths(
    source_dir: Path,
    grouped: Dict[str, List[Path]],
    min_group_size: int,
    checkpoint_interval: int,
) -> Tuple[bytes, List[Dict[str, object]]] | None:
    if checkpoint_interval < 1:
        raise ValueError("History-pack checkpoint interval must be positive")
    if not any(len(group) >= min_group_size for group in grouped.values()):
        return None

    files = [path for group in grouped.values() for path in group]
    full_cost = sum(len(zlib.compress(path.read_bytes(), level=9)) for path in files)
    chunks_region = bytearray()
    chunks_manifest: List[Dict[str, object]] = []
    manifest_files: List[Dict[str, object]] = []
    grouped_sequences: List[Tuple[str, List[Path]]] = []
    ordered_items: List[Tuple[str, Path]] = []

    for group_name, group_files in sorted(grouped.items()):
        sorted_files = sorted(
            group_files,
            key=lambda item: natural_key(item.relative_to(source_dir).as_posix()),
        )
        grouped_sequences.append((group_name, sorted_files))
        ordered_items.extend((group_name, path) for path in sorted_files)

    for chunk_index, chunk_items in enumerate(_chunk_items(ordered_items, checkpoint_interval)):
        chunk_offset = len(chunks_region)
        chunk_payload, members = _encode_v3_chunk(
            source_dir=source_dir,
            chunk_index=chunk_index,
            items=chunk_items,
            first_member_index=len(manifest_files),
        )
        chunks_region.extend(chunk_payload)
        logical_bytes = sum(int(member["logical_size"]) for member in members)
        chunk_record = {
            "index": chunk_index,
            "offset": chunk_offset,
            "length": len(chunk_payload),
            "sha256": _digest(chunk_payload),
            "file_count": len(members),
            "logical_bytes": logical_bytes,
            "first_path": members[0]["path"],
            "last_path": members[-1]["path"],
            "members": [member["path"] for member in members],
        }
        chunks_manifest.append(chunk_record)
        for member in members:
            manifest_files.append(
                {
                    "path": member["path"],
                    "logical_size": member["logical_size"],
                    "sha256": member["sha256"],
                    "member_index": member["member_index"],
                    "chunk_index": chunk_index,
                    "group": member["group"],
                }
            )

    groups_manifest = [
        {
            "name": group_name,
            "file_count": len(files_in_group),
            "first_path": files_in_group[0].relative_to(source_dir).as_posix(),
            "last_path": files_in_group[-1].relative_to(source_dir).as_posix(),
        }
        for group_name, files_in_group in grouped_sequences
        if files_in_group
    ]

    index_document = {
        "format": "smavg-history-pack",
        "version": 3,
        "checkpoint_interval": checkpoint_interval,
        "chunking": "global",
        "groups": groups_manifest,
        "chunks": chunks_manifest,
        "file_count": len(manifest_files),
        "logical_bytes": sum(int(item["logical_size"]) for item in manifest_files),
    }
    index_payload = zlib.compress(
        json.dumps(index_document, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        level=9,
    )
    chunks_payload = bytes(chunks_region)
    payload = (
        _V3_HEADER.pack(
            _V3_MAGIC,
            len(index_payload),
            len(chunks_payload),
            bytes.fromhex(_digest(index_payload)),
        )
        + index_payload
        + chunks_payload
    )
    if len(payload) >= full_cost:
        return None

    _self_check_history_payload(source_dir, payload, manifest_files)

    return payload, manifest_files


def _encode_v4_grouped_paths(
    source_dir: Path,
    grouped: Dict[str, List[Path]],
    min_group_size: int,
    checkpoint_interval: int,
) -> Tuple[bytes, List[Dict[str, object]]] | None:
    if checkpoint_interval < 1:
        raise ValueError("History-pack checkpoint interval must be positive")
    if not any(len(group) >= min_group_size for group in grouped.values()):
        return None

    files = [path for group in grouped.values() for path in group]
    full_cost = sum(len(zlib.compress(path.read_bytes(), level=9)) for path in files)
    chunks_region = bytearray()
    chunks_manifest: List[Dict[str, object]] = []
    manifest_files: List[Dict[str, object]] = []
    grouped_sequences: List[Tuple[str, List[Path]]] = []
    ordered_items: List[Tuple[str, Path]] = []

    for group_name, group_files in sorted(grouped.items()):
        sorted_files = sorted(
            group_files,
            key=lambda item: natural_key(item.relative_to(source_dir).as_posix()),
        )
        grouped_sequences.append((group_name, sorted_files))
        ordered_items.extend((group_name, path) for path in sorted_files)

    for chunk_index, chunk_items in enumerate(_chunk_items(ordered_items, checkpoint_interval)):
        chunk_offset = len(chunks_region)
        chunk_payload, members, chunk_root, logical_bytes = _encode_v4_chunk(
            source_dir=source_dir,
            chunk_index=chunk_index,
            items=chunk_items,
            first_member_index=len(manifest_files),
        )
        chunks_region.extend(chunk_payload)
        chunk_record = {
            "index": chunk_index,
            "offset": chunk_offset,
            "length": len(chunk_payload),
            "sha256": _digest(chunk_payload),
            "root": chunk_root,
            "file_count": len(members),
            "logical_bytes": logical_bytes,
            "first_path": members[0]["path"],
            "last_path": members[-1]["path"],
            "members": [member["path"] for member in members],
            "groups": [member["group"] for member in members],
        }
        chunks_manifest.append(chunk_record)
        for member in members:
            manifest_files.append(
                {
                    "path": member["path"],
                    "logical_size": member["logical_size"],
                    "member_index": member["member_index"],
                    "chunk_index": chunk_index,
                    "group": member["group"],
                }
            )

    groups_manifest = [
        {
            "name": group_name,
            "file_count": len(files_in_group),
            "first_path": files_in_group[0].relative_to(source_dir).as_posix(),
            "last_path": files_in_group[-1].relative_to(source_dir).as_posix(),
        }
        for group_name, files_in_group in grouped_sequences
        if files_in_group
    ]

    index_document = {
        "format": "smavg-history-pack",
        "version": 4,
        "checkpoint_interval": checkpoint_interval,
        "verification": "chunk-merkle-root",
        "groups": groups_manifest,
        "chunks": chunks_manifest,
        "file_count": len(manifest_files),
        "logical_bytes": sum(int(item["logical_size"]) for item in manifest_files),
    }
    index_payload = zlib.compress(
        json.dumps(index_document, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        level=9,
    )
    chunks_payload = bytes(chunks_region)
    payload = (
        _V3_HEADER.pack(
            _V4_MAGIC,
            len(index_payload),
            len(chunks_payload),
            bytes.fromhex(_digest(index_payload)),
        )
        + index_payload
        + chunks_payload
    )
    if len(payload) >= full_cost:
        return None

    _self_check_history_payload(source_dir, payload, manifest_files)
    return payload, manifest_files


def _encode_legacy_grouped_paths(
    source_dir: Path,
    grouped: Dict[str, List[Path]],
    min_group_size: int,
) -> Tuple[bytes, List[Dict[str, object]]] | None:
    if not any(len(group) >= min_group_size for group in grouped.values()):
        return None

    files = [path for group in grouped.values() for path in group]
    full_cost = sum(len(zlib.compress(path.read_bytes(), level=9)) for path in files)
    document = {"v": 2, "groups": []}
    manifest_files: List[Dict[str, object]] = []
    member_index = 0

    for group_name, group_files in sorted(grouped.items()):
        sorted_files = sorted(
            group_files,
            key=lambda item: natural_key(item.relative_to(source_dir).as_posix()),
        )
        previous = None
        group = {"parent": group_name, "files": []}
        for path in sorted_files:
            relative = path.relative_to(source_dir).as_posix()
            data = path.read_bytes()
            digest = _digest(data)
            if previous is None:
                entry = ["base", relative, digest, len(data), _encode_bytes(data)]
            else:
                entry = ["delta", relative, digest, len(data), _line_delta(previous, data)]
            group["files"].append(entry)
            manifest_files.append(
                {
                    "path": relative,
                    "logical_size": len(data),
                    "sha256": digest,
                    "member_index": member_index,
                }
            )
            member_index += 1
            previous = data
        document["groups"].append(group)

    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("latin1")
    payload = lzma.compress(raw, preset=9 | lzma.PRESET_EXTREME)
    if len(payload) >= full_cost:
        return None

    _self_check_history_payload(source_dir, payload, manifest_files)
    return payload, manifest_files


def _chunk_items(
    items: List[Tuple[str, Path]],
    checkpoint_interval: int,
) -> Iterator[List[Tuple[str, Path]]]:
    for start in range(0, len(items), checkpoint_interval):
        yield items[start : start + checkpoint_interval]


def _encode_v3_chunk(
    source_dir: Path,
    chunk_index: int,
    items: List[Tuple[str, Path]],
    first_member_index: int,
) -> Tuple[bytes, List[Dict[str, object]]]:
    entries = []
    members: List[Dict[str, object]] = []
    previous_by_group: Dict[str, bytes] = {}
    for local_index, (group_name, path) in enumerate(items):
        relative = path.relative_to(source_dir).as_posix()
        data = path.read_bytes()
        digest = _digest(data)
        previous = previous_by_group.get(group_name)
        if previous is None:
            entry = ["base", relative, digest, len(data), _encode_bytes(data)]
        else:
            entry = ["delta", relative, digest, len(data), _line_delta(previous, data)]
        entries.append(entry)
        members.append(
            {
                "path": relative,
                "group": group_name,
                "logical_size": len(data),
                "sha256": digest,
                "member_index": first_member_index + local_index,
            }
        )
        previous_by_group[group_name] = data

    chunk_document = {
        "v": 3,
        "chunk_index": chunk_index,
        "files": entries,
    }
    raw = json.dumps(chunk_document, ensure_ascii=False, separators=(",", ":")).encode("latin1")
    return lzma.compress(raw, preset=9 | lzma.PRESET_EXTREME), members


def _encode_v4_chunk(
    source_dir: Path,
    chunk_index: int,
    items: List[Tuple[str, Path]],
    first_member_index: int,
) -> Tuple[bytes, List[Dict[str, object]], str, int]:
    entries = []
    members: List[Dict[str, object]] = []
    previous_by_group: Dict[str, bytes] = {}
    root_hasher = sha256()
    logical_bytes = 0
    for local_index, (group_name, path) in enumerate(items):
        relative = path.relative_to(source_dir).as_posix()
        data = path.read_bytes()
        logical_bytes += len(data)
        _update_history_root(root_hasher, relative, data)
        previous = previous_by_group.get(group_name)
        if previous is None:
            entry = ["b", _encode_bytes(data)]
        else:
            entry = ["d", _line_delta(previous, data)]
        entries.append(entry)
        members.append(
            {
                "path": relative,
                "group": group_name,
                "logical_size": len(data),
                "member_index": first_member_index + local_index,
            }
        )
        previous_by_group[group_name] = data

    chunk_document = {
        "v": 4,
        "chunk_index": chunk_index,
        "entries": entries,
    }
    raw = json.dumps(chunk_document, ensure_ascii=False, separators=(",", ":")).encode("latin1")
    return (
        lzma.compress(raw, preset=9 | lzma.PRESET_EXTREME),
        members,
        root_hasher.hexdigest(),
        logical_bytes,
    )


def decode_history_pack(payload: bytes) -> Dict[str, bytes]:
    if payload.startswith(_V4_MAGIC):
        restored: Dict[str, bytes] = {}
        for relative, data in iter_history_pack_bytes(payload):
            if relative in restored:
                raise ValueError(f"Duplicate history-pack path: {relative}")
            restored[relative] = data
        return restored
    if payload.startswith(_V3_MAGIC):
        restored: Dict[str, bytes] = {}
        for relative, data in iter_history_pack_bytes(payload):
            if relative in restored:
                raise ValueError(f"Duplicate history-pack path: {relative}")
            restored[relative] = data
        return restored
    return _decode_legacy_history_pack(payload)


def iter_history_pack_bytes(payload: bytes) -> Iterator[Tuple[str, bytes]]:
    if not (payload.startswith(_V3_MAGIC) or payload.startswith(_V4_MAGIC)):
        yield from _decode_legacy_history_pack(payload).items()
        return
    source = io.BytesIO(payload)
    if payload.startswith(_V4_MAGIC):
        yield from _iter_history_pack_v4(source, 0, len(payload))
    else:
        yield from _iter_history_pack_v3(source, 0, len(payload))


def iter_history_pack_stream(
    source: BinaryIO,
    offset: int,
    length: int,
) -> Iterator[Tuple[str, bytes]]:
    source.seek(offset)
    prefix = source.read(len(_V3_MAGIC))
    if len(prefix) != len(_V3_MAGIC):
        raise ValueError("Short read from history-pack payload")
    source.seek(offset)
    if prefix == _V4_MAGIC:
        yield from _iter_history_pack_v4(source, offset, length)
        return
    if prefix != _V3_MAGIC:
        payload = source.read(length)
        if len(payload) != length:
            raise ValueError("Short read from history-pack payload")
        yield from _decode_legacy_history_pack(payload).items()
        return
    yield from _iter_history_pack_v3(source, offset, length)


def restore_history_pack_member(payload: bytes, relative_path: str) -> bytes:
    normalized = _validate_relative_path(relative_path)
    if not (payload.startswith(_V3_MAGIC) or payload.startswith(_V4_MAGIC)):
        restored = _decode_legacy_history_pack(payload)
        if normalized not in restored:
            raise KeyError(normalized)
        return restored[normalized]
    source = io.BytesIO(payload)
    iterator = (
        _iter_history_pack_v4(source, 0, len(payload), target_path=normalized)
        if payload.startswith(_V4_MAGIC)
        else _iter_history_pack_v3(source, 0, len(payload), target_path=normalized)
    )
    for relative, data in iterator:
        if relative == normalized:
            return data
    raise KeyError(normalized)


def restore_history_pack_member_stream(
    source: BinaryIO,
    offset: int,
    length: int,
    relative_path: str,
) -> bytes:
    normalized = _validate_relative_path(relative_path)
    source.seek(offset)
    prefix = source.read(len(_V3_MAGIC))
    source.seek(offset)
    if prefix == _V4_MAGIC:
        for relative, data in _iter_history_pack_v4(source, offset, length, target_path=normalized):
            if relative == normalized:
                return data
        raise KeyError(normalized)
    if prefix != _V3_MAGIC:
        payload = source.read(length)
        if len(payload) != length:
            raise ValueError("Short read from history-pack payload")
        restored = _decode_legacy_history_pack(payload)
        if normalized not in restored:
            raise KeyError(normalized)
        return restored[normalized]
    for relative, data in _iter_history_pack_v3(source, offset, length, target_path=normalized):
        if relative == normalized:
            return data
    raise KeyError(normalized)


def _iter_history_pack_v3(
    source: BinaryIO,
    offset: int,
    length: int,
    target_path: Optional[str] = None,
) -> Iterator[Tuple[str, bytes]]:
    if length < _V3_HEADER.size:
        raise ValueError("History-pack v3 payload is too small")
    source.seek(offset)
    header_data = source.read(_V3_HEADER.size)
    if len(header_data) != _V3_HEADER.size:
        raise ValueError("Short read from history-pack v3 header")
    magic, index_len, chunks_len, index_sha = _V3_HEADER.unpack(header_data)
    if magic != _V3_MAGIC:
        raise ValueError("Invalid history-pack v3 magic")
    if _V3_HEADER.size + index_len + chunks_len != length:
        raise ValueError("History-pack v3 size metadata mismatch")

    index_payload = source.read(index_len)
    if len(index_payload) != index_len:
        raise ValueError("Short read from history-pack v3 index")
    if bytes.fromhex(_digest(index_payload)) != index_sha:
        raise ValueError("History-pack v3 index SHA-256 check failed")
    try:
        index_document = json.loads(zlib.decompress(index_payload).decode("utf-8"))
    except (ValueError, zlib.error) as exc:
        raise ValueError("History-pack v3 index decode failed") from exc

    chunks = _validate_v3_index(index_document, chunks_len)
    chunk_region_offset = offset + _V3_HEADER.size + index_len
    yielded = False
    for chunk in chunks:
        if target_path is not None and target_path not in {
            _member_path(member) for member in chunk["members"]
        }:
            continue
        compressed = _read_region(
            source,
            chunk_region_offset + int(chunk["offset"]),
            int(chunk["length"]),
        )
        for relative, data in _decode_v3_chunk(compressed, chunk, target_path=target_path):
            yielded = True
            yield relative, data
            if target_path is not None:
                return
    if target_path is not None and not yielded:
        raise KeyError(target_path)


def _iter_history_pack_v4(
    source: BinaryIO,
    offset: int,
    length: int,
    target_path: Optional[str] = None,
) -> Iterator[Tuple[str, bytes]]:
    if length < _V3_HEADER.size:
        raise ValueError("History-pack v4 payload is too small")
    source.seek(offset)
    header_data = source.read(_V3_HEADER.size)
    if len(header_data) != _V3_HEADER.size:
        raise ValueError("Short read from history-pack v4 header")
    magic, index_len, chunks_len, index_sha = _V3_HEADER.unpack(header_data)
    if magic != _V4_MAGIC:
        raise ValueError("Invalid history-pack v4 magic")
    if _V3_HEADER.size + index_len + chunks_len != length:
        raise ValueError("History-pack v4 size metadata mismatch")

    index_payload = source.read(index_len)
    if len(index_payload) != index_len:
        raise ValueError("Short read from history-pack v4 index")
    if bytes.fromhex(_digest(index_payload)) != index_sha:
        raise ValueError("History-pack v4 index SHA-256 check failed")
    try:
        index_document = json.loads(zlib.decompress(index_payload).decode("utf-8"))
    except (ValueError, zlib.error) as exc:
        raise ValueError("History-pack v4 index decode failed") from exc

    chunks = _validate_v4_index(index_document, chunks_len)
    chunk_region_offset = offset + _V3_HEADER.size + index_len
    yielded = False
    for chunk in chunks:
        if target_path is not None and target_path not in {
            _member_path(member) for member in chunk["members"]
        }:
            continue
        compressed = _read_region(
            source,
            chunk_region_offset + int(chunk["offset"]),
            int(chunk["length"]),
        )
        for relative, data in _decode_v4_chunk(compressed, chunk, target_path=target_path):
            yielded = True
            yield relative, data
            if target_path is not None:
                return
    if target_path is not None and not yielded:
        raise KeyError(target_path)


def _read_region(source: BinaryIO, offset: int, length: int) -> bytes:
    source.seek(offset)
    data = source.read(length)
    if len(data) != length:
        raise ValueError("Short read from history-pack payload")
    return data


def _member_path(raw_member: object) -> str:
    if isinstance(raw_member, str):
        return raw_member
    if isinstance(raw_member, dict):
        value = raw_member.get("path")
        if isinstance(value, str):
            return value
    raise TypeError("history-pack member path must be a string")


def _validate_v3_index(
    raw_document: object,
    chunks_length: int,
) -> List[Dict[str, object]]:
    if not isinstance(raw_document, dict):
        raise ValueError("History-pack v3 index must be an object")
    document: Dict[str, object] = raw_document
    if document.get("format") != "smavg-history-pack" or document.get("version") != 3:
        raise ValueError("Unsupported history-pack v3 index")
    checkpoint_interval = _require_int(document, "checkpoint_interval", "history-pack v3 index")
    if checkpoint_interval < 1:
        raise ValueError("History-pack v3 checkpoint interval must be positive")
    groups = document.get("groups")
    if not isinstance(groups, list):
        raise ValueError("History-pack v3 groups must be a list")
    for group_index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ValueError(f"History-pack v3 group {group_index} must be an object")
        name = group.get("name")
        if not isinstance(name, str):
            raise ValueError(f"History-pack v3 group {group_index} name must be a string")
        _require_int(group, "file_count", f"history-pack v3 group {group_index}")
        for field in ("first_path", "last_path"):
            value = group.get(field)
            if not isinstance(value, str):
                raise ValueError(f"History-pack v3 group {group_index} {field} must be a string")
            _validate_relative_path(value)

    raw_chunks = document.get("chunks")
    if not isinstance(raw_chunks, list):
        raise ValueError("History-pack v3 chunks must be a list")

    chunks: List[Dict[str, object]] = []
    seen_paths = set()
    ranges: List[Tuple[int, int]] = []
    for chunk_index, raw_chunk in enumerate(raw_chunks):
        context = f"history-pack v3 chunk {chunk_index}"
        if not isinstance(raw_chunk, dict):
            raise ValueError(f"{context} must be an object")
        chunk: Dict[str, object] = raw_chunk
        offset = _require_int(chunk, "offset", context)
        length = _require_int(chunk, "length", context)
        if offset < 0 or length < 0 or offset + length > chunks_length:
            raise ValueError(f"{context} points outside chunk region")
        ranges.append((offset, offset + length))
        sha_value = chunk.get("sha256")
        if not isinstance(sha_value, str) or len(sha_value) != 64:
            raise ValueError(f"{context} has invalid SHA-256")
        members = chunk.get("members")
        if not isinstance(members, list) or not members:
            raise ValueError(f"{context} members must be a non-empty list")
        file_count = _require_int(chunk, "file_count", context)
        logical_bytes = _require_int(chunk, "logical_bytes", context)
        if file_count != len(members):
            raise ValueError(f"{context} file count mismatch")
        for member_index, raw_member in enumerate(members):
            try:
                normalized = _validate_relative_path(_member_path(raw_member))
            except TypeError as exc:
                raise ValueError(f"{context} member {member_index} path must be a string") from exc
            if normalized in seen_paths:
                raise ValueError(f"Duplicate history-pack path: {normalized}")
            seen_paths.add(normalized)
        if logical_bytes < 0:
            raise ValueError(f"{context} logical size must be non-negative")
        chunks.append(chunk)

    for previous, current in zip(sorted(ranges), sorted(ranges)[1:]):
        if current[0] < previous[1]:
            raise ValueError("History-pack v3 chunks overlap")
    expected_count = _require_int(document, "file_count", "history-pack v3 index")
    expected_logical = _require_int(document, "logical_bytes", "history-pack v3 index")
    if expected_count != len(seen_paths):
        raise ValueError("History-pack v3 file count mismatch")
    if expected_logical != sum(
        int(chunk["logical_bytes"])
        for chunk in chunks
    ):
        raise ValueError("History-pack v3 logical size mismatch")
    return chunks


def _validate_v4_index(
    raw_document: object,
    chunks_length: int,
) -> List[Dict[str, object]]:
    if not isinstance(raw_document, dict):
        raise ValueError("History-pack v4 index must be an object")
    document: Dict[str, object] = raw_document
    if document.get("format") != "smavg-history-pack" or document.get("version") != 4:
        raise ValueError("Unsupported history-pack v4 index")
    if document.get("verification") != "chunk-merkle-root":
        raise ValueError("Unsupported history-pack v4 verification mode")
    checkpoint_interval = _require_int(document, "checkpoint_interval", "history-pack v4 index")
    if checkpoint_interval < 1:
        raise ValueError("History-pack v4 checkpoint interval must be positive")
    groups = document.get("groups")
    if not isinstance(groups, list):
        raise ValueError("History-pack v4 groups must be a list")
    for group_index, group in enumerate(groups):
        if not isinstance(group, dict):
            raise ValueError(f"History-pack v4 group {group_index} must be an object")
        name = group.get("name")
        if not isinstance(name, str):
            raise ValueError(f"History-pack v4 group {group_index} name must be a string")
        _require_int(group, "file_count", f"history-pack v4 group {group_index}")
        for field in ("first_path", "last_path"):
            value = group.get(field)
            if not isinstance(value, str):
                raise ValueError(f"History-pack v4 group {group_index} {field} must be a string")
            _validate_relative_path(value)

    raw_chunks = document.get("chunks")
    if not isinstance(raw_chunks, list):
        raise ValueError("History-pack v4 chunks must be a list")

    chunks: List[Dict[str, object]] = []
    seen_paths = set()
    ranges: List[Tuple[int, int]] = []
    for chunk_index, raw_chunk in enumerate(raw_chunks):
        context = f"history-pack v4 chunk {chunk_index}"
        if not isinstance(raw_chunk, dict):
            raise ValueError(f"{context} must be an object")
        chunk: Dict[str, object] = raw_chunk
        offset = _require_int(chunk, "offset", context)
        length = _require_int(chunk, "length", context)
        if offset < 0 or length < 0 or offset + length > chunks_length:
            raise ValueError(f"{context} points outside chunk region")
        ranges.append((offset, offset + length))
        for field in ("sha256", "root"):
            value = chunk.get(field)
            if not isinstance(value, str) or len(value) != 64:
                raise ValueError(f"{context} has invalid {field}")
            try:
                int(value, 16)
            except ValueError as exc:
                raise ValueError(f"{context} has invalid {field}") from exc
        members = chunk.get("members")
        groups = chunk.get("groups")
        if not isinstance(members, list) or not members:
            raise ValueError(f"{context} members must be a non-empty list")
        if not isinstance(groups, list) or len(groups) != len(members):
            raise ValueError(f"{context} groups must match members")
        file_count = _require_int(chunk, "file_count", context)
        logical_bytes = _require_int(chunk, "logical_bytes", context)
        if file_count != len(members):
            raise ValueError(f"{context} file count mismatch")
        for member_index, raw_member in enumerate(members):
            try:
                normalized = _validate_relative_path(_member_path(raw_member))
            except TypeError as exc:
                raise ValueError(f"{context} member {member_index} path must be a string") from exc
            if normalized in seen_paths:
                raise ValueError(f"Duplicate history-pack path: {normalized}")
            seen_paths.add(normalized)
            if not isinstance(groups[member_index], str):
                raise ValueError(f"{context} group {member_index} must be a string")
        if logical_bytes < 0:
            raise ValueError(f"{context} logical size must be non-negative")
        chunks.append(chunk)

    for previous, current in zip(sorted(ranges), sorted(ranges)[1:]):
        if current[0] < previous[1]:
            raise ValueError("History-pack v4 chunks overlap")
    expected_count = _require_int(document, "file_count", "history-pack v4 index")
    expected_logical = _require_int(document, "logical_bytes", "history-pack v4 index")
    if expected_count != len(seen_paths):
        raise ValueError("History-pack v4 file count mismatch")
    if expected_logical != sum(int(chunk["logical_bytes"]) for chunk in chunks):
        raise ValueError("History-pack v4 logical size mismatch")
    return chunks


def _decode_v3_chunk(
    compressed: bytes,
    chunk: Dict[str, object],
    target_path: Optional[str] = None,
) -> Iterator[Tuple[str, bytes]]:
    if _digest(compressed) != chunk["sha256"]:
        raise ValueError("History-pack v3 chunk SHA-256 check failed")
    try:
        document = json.loads(lzma.decompress(compressed).decode("latin1"))
    except (ValueError, lzma.LZMAError) as exc:
        raise ValueError("History-pack v3 chunk decode failed") from exc
    if not isinstance(document, dict) or document.get("v") != 3:
        raise ValueError("Unsupported history-pack v3 chunk")
    entries = document.get("files")
    if not isinstance(entries, list):
        raise ValueError("History-pack v3 chunk files must be a list")
    members = chunk["members"]
    if len(entries) != len(members):
        raise ValueError("History-pack v3 chunk file count mismatch")

    previous = None
    yielded_target = False
    logical_bytes = 0
    file_count = 0
    for entry, raw_member in zip(entries, members):
        relative, data = _decode_history_entry(entry, previous)
        expected_path = _validate_relative_path(_member_path(raw_member))
        if relative != expected_path:
            raise ValueError("History-pack v3 chunk path order mismatch")
        previous = data
        file_count += 1
        logical_bytes += len(data)
        if target_path is None or relative == target_path:
            yielded_target = yielded_target or relative == target_path
            yield relative, data
            if target_path is not None:
                return
    if file_count != int(chunk["file_count"]):
        raise ValueError("History-pack v3 chunk file count mismatch")
    if logical_bytes != int(chunk["logical_bytes"]):
        raise ValueError("History-pack v3 chunk logical size mismatch")
    if target_path is not None and not yielded_target:
        raise KeyError(target_path)


def _decode_v4_chunk(
    compressed: bytes,
    chunk: Dict[str, object],
    target_path: Optional[str] = None,
) -> Iterator[Tuple[str, bytes]]:
    if _digest(compressed) != chunk["sha256"]:
        raise ValueError("History-pack v4 chunk SHA-256 check failed")
    try:
        document = json.loads(lzma.decompress(compressed).decode("latin1"))
    except (ValueError, lzma.LZMAError) as exc:
        raise ValueError("History-pack v4 chunk decode failed") from exc
    if not isinstance(document, dict) or document.get("v") != 4:
        raise ValueError("Unsupported history-pack v4 chunk")
    entries = document.get("entries")
    if not isinstance(entries, list):
        raise ValueError("History-pack v4 chunk entries must be a list")
    members = chunk["members"]
    groups = chunk["groups"]
    if len(entries) != len(members) or len(entries) != len(groups):
        raise ValueError("History-pack v4 chunk file count mismatch")

    previous_by_group: Dict[str, bytes] = {}
    root_hasher = sha256()
    yielded_target = False
    target_data = None
    logical_bytes = 0
    file_count = 0
    for entry, raw_member, raw_group in zip(entries, members, groups):
        relative = _validate_relative_path(_member_path(raw_member))
        if not isinstance(raw_group, str):
            raise ValueError("History-pack v4 member group must be a string")
        data = _decode_v4_entry(entry, previous_by_group.get(raw_group))
        previous_by_group[raw_group] = data
        _update_history_root(root_hasher, relative, data)
        file_count += 1
        logical_bytes += len(data)
        if target_path is None:
            yield relative, data
        elif relative == target_path:
            yielded_target = True
            target_data = data
    if file_count != int(chunk["file_count"]):
        raise ValueError("History-pack v4 chunk file count mismatch")
    if logical_bytes != int(chunk["logical_bytes"]):
        raise ValueError("History-pack v4 chunk logical size mismatch")
    if root_hasher.hexdigest() != chunk["root"]:
        raise ValueError("History-pack v4 chunk root check failed")
    if target_path is not None and not yielded_target:
        raise KeyError(target_path)
    if target_path is not None:
        yield target_path, target_data


def _decode_v4_entry(entry: object, previous: Optional[bytes]) -> bytes:
    if not isinstance(entry, list) or len(entry) != 2:
        raise ValueError("Invalid history-pack v4 entry")
    kind, payload_part = entry
    if kind == "b":
        if not isinstance(payload_part, str):
            raise ValueError("Invalid history-pack v4 base payload")
        return _decode_bytes(payload_part)
    if kind == "d":
        if previous is None:
            raise ValueError("History-pack v4 delta has no base")
        return _apply_line_delta(previous, payload_part)
    raise ValueError(f"Unknown history-pack v4 entry kind: {kind}")


def _decode_history_entry(entry: object, previous: Optional[bytes]) -> Tuple[str, bytes]:
    if not isinstance(entry, list) or len(entry) != 5:
        raise ValueError("Invalid history-pack file entry")
    kind, relative, expected_sha, expected_size, payload_part = entry
    if not isinstance(relative, str):
        raise ValueError("Invalid history-pack relative path")
    relative = _validate_relative_path(relative)
    if not isinstance(expected_sha, str) or not isinstance(expected_size, int):
        raise ValueError("Invalid history-pack verification metadata")
    if kind == "base":
        if not isinstance(payload_part, str):
            raise ValueError("Invalid history-pack base payload")
        data = _decode_bytes(payload_part)
    elif kind == "delta":
        if previous is None:
            raise ValueError("History-pack delta has no base")
        data = _apply_line_delta(previous, payload_part)
    else:
        raise ValueError(f"Unknown history-pack file kind: {kind}")
    if len(data) != expected_size:
        raise ValueError(f"History-pack size check failed for {relative}")
    if _digest(data) != expected_sha:
        raise ValueError(f"History-pack SHA-256 check failed for {relative}")
    return relative, data


def _decode_legacy_history_pack(payload: bytes) -> Dict[str, bytes]:
    raw = lzma.decompress(payload)
    document = json.loads(raw.decode("latin1"))
    version = document.get("v")
    if version not in {1, 2}:
        raise ValueError("Unsupported history-pack version")
    restored: Dict[str, bytes] = {}
    for group in document.get("groups", []):
        previous = None
        for entry in group.get("files", []):
            if not isinstance(entry, list):
                raise ValueError("Invalid history-pack file entry")
            if version == 1:
                if len(entry) != 3:
                    raise ValueError("Invalid history-pack v1 file entry")
                kind, relative, payload_part = entry
                expected_sha = None
                expected_size = None
            else:
                if len(entry) != 5:
                    raise ValueError("Invalid history-pack v2 file entry")
                kind, relative, expected_sha, expected_size, payload_part = entry
                if not isinstance(expected_sha, str) or not isinstance(expected_size, int):
                    raise ValueError("Invalid history-pack verification metadata")
            if not isinstance(relative, str):
                raise ValueError("Invalid history-pack relative path")
            relative = _validate_relative_path(relative)
            if kind == "base":
                if not isinstance(payload_part, str):
                    raise ValueError("Invalid history-pack base payload")
                data = _decode_bytes(payload_part)
            elif kind == "delta":
                if previous is None:
                    raise ValueError("History-pack delta has no base")
                data = _apply_line_delta(previous, payload_part)
            else:
                raise ValueError(f"Unknown history-pack file kind: {kind}")
            if expected_size is not None and len(data) != expected_size:
                raise ValueError(f"History-pack size check failed for {relative}")
            if expected_sha is not None and _digest(data) != expected_sha:
                raise ValueError(f"History-pack SHA-256 check failed for {relative}")
            if relative in restored:
                raise ValueError(f"Duplicate history-pack path: {relative}")
            restored[relative] = data
            previous = data
    return restored


def _require_int(record: Dict[str, object], field: str, context: str) -> int:
    value = record.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{context} field {field} must be an integer")
    return value
