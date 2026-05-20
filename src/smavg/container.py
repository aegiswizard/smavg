"""Single-file Smavg archive container."""

from __future__ import annotations

import json
import lzma
import os
import hashlib
import stat
import struct
import time
import zlib
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Dict, Iterable, List, Optional, Set, Tuple

from .delta import sha256_bytes
from .history_pack import (
    HISTORY_PACK_V2_CODEC,
    HISTORY_PACK_V3_CODEC,
    HISTORY_PACK_V4_CODEC,
    decode_history_pack,
    history_pack_codec,
    iter_history_pack_stream,
    restore_history_pack_member_stream,
)
from .planner import ArchivePlan, build_archive_plan


class ContainerError(RuntimeError):
    """Raised for invalid or unrestorable Smavg containers."""


MAGIC = b"SMAVG001"
HEADER = struct.Struct("<8sQQ32s32s")

TOP_LEVEL_FIELDS = {
    "format": str,
    "version": int,
    "created_at": str,
    "source_path": str,
    "file_count": int,
    "logical_bytes": int,
    "payload_bytes": int,
    "payload_sha256": str,
    "manifest_codec": str,
    "families": list,
    "fallback_files": list,
}

FAMILY_FIELDS = {
    "id": str,
    "kind": str,
    "codec": str,
    "offset": int,
    "length": int,
    "sha256": str,
    "file_count": int,
    "logical_bytes": int,
}

FALLBACK_FIELDS = {
    "path": str,
    "codec": str,
    "offset": int,
    "length": int,
    "payload_sha256": str,
    "sha256": str,
    "logical_size": int,
    "is_text": bool,
}

TREE_ENTRY_FIELDS = {
    "path": str,
    "kind": str,
}


@dataclass
class ContainerRead:
    path: Path
    manifest: Dict[str, object]
    manifest_payload: bytes
    payload_offset: int
    payload_length: int
    payload_sha256: str

    @property
    def payload(self) -> bytes:
        """Compatibility escape hatch for tests/tools that explicitly need bytes."""
        with self.path.open("rb") as handle:
            handle.seek(self.payload_offset)
            data = handle.read(self.payload_length)
        if len(data) != self.payload_length:
            raise ContainerError("Short read from payload region")
        return data


def pack_container(source_dir: Path, output: Path) -> Dict[str, object]:
    source_dir = Path(source_dir).resolve()
    output = Path(output)
    if not source_dir.is_dir():
        raise ContainerError(f"Not a directory: {source_dir}")

    plan = build_archive_plan(source_dir, output.resolve())

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    payload_temp = output.with_name(output.name + ".payload.tmp")
    try:
        with payload_temp.open("wb") as payload_file:
            manifest = _build_container_manifest(source_dir, plan, payload_file)

        manifest_payload = zlib.compress(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"),
            level=9,
        )
        header = HEADER.pack(
            MAGIC,
            len(manifest_payload),
            int(manifest["payload_bytes"]),
            bytes.fromhex(sha256_bytes(manifest_payload)),
            bytes.fromhex(str(manifest["payload_sha256"])),
        )

        with temp.open("wb") as archive, payload_temp.open("rb") as payload_file:
            archive.write(header)
            archive.write(manifest_payload)
            shutil.copyfileobj(payload_file, archive, length=1024 * 1024)
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
        payload_temp.unlink(missing_ok=True)

    ok, failures = verify_container(output)
    if not ok:
        raise ContainerError("Packed container verification failed: " + "; ".join(failures))
    return report_container(output)


def verify_container(path: Path) -> Tuple[bool, List[str]]:
    failures = []
    try:
        container = read_container(path)
        _verify_container_payloads(container)
    except (ContainerError, OSError) as exc:
        failures.append(str(exc))
    return not failures, failures


def restore_container(path: Path, destination: Path) -> int:
    container = read_container(path)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    tree_entries = _tree_entries(container.manifest)
    for entry in tree_entries:
        if entry["kind"] == "dir":
            target = destination / str(entry["path"])
            target.mkdir(parents=True, exist_ok=True)

    restored_paths: Set[str] = set()
    logical_bytes = 0
    for family in container.manifest.get("families", []):
        for relative, data in _iter_family_files(container, family):
            normalized = _safe_relative_path(relative)
            if normalized in restored_paths:
                raise ContainerError(f"Duplicate restored path: {normalized}")
            _write_restored_bytes(destination, normalized, data)
            restored_paths.add(normalized)
            logical_bytes += len(data)
    for record in container.manifest.get("fallback_files", []):
        relative = _safe_relative_path(str(record["path"]))
        if relative in restored_paths:
            raise ContainerError(f"Duplicate restored path: {relative}")
        logical_bytes += _restore_fallback_record(container, record, destination / relative)
        restored_paths.add(relative)

    _verify_restored_totals(container.manifest, restored_paths, logical_bytes)
    for entry in tree_entries:
        if entry["kind"] == "symlink":
            relative = str(entry["path"])
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if os.path.lexists(target):
                raise ContainerError(f"Restore target already exists: {relative}")
            os.symlink(str(entry["target"]), target)
    _apply_tree_modes(destination, tree_entries, restored_paths, container.manifest)
    return len(restored_paths)


def extract_container_file(path: Path, relative_path: str, output: Path) -> int:
    container = read_container(path)
    relative = _safe_relative_path(relative_path)
    output = Path(output)
    if os.path.lexists(output):
        raise ContainerError(f"Extract target already exists: {output}")
    for family in container.manifest.get("families", []):
        try:
            data = _extract_family_file(container, family, relative)
        except KeyError:
            continue
        _write_restored_bytes(output.parent, output.name, data)
        return len(data)
    for record in container.manifest.get("fallback_files", []):
        if _safe_relative_path(str(record["path"])) != relative:
            continue
        return _restore_fallback_record(container, record, output)
    raise ContainerError(f"Archive path not found: {relative}")


def report_container(path: Path) -> Dict[str, object]:
    container = read_container(path)
    manifest = container.manifest
    archive_bytes = Path(path).stat().st_size
    logical = int(manifest["logical_bytes"])
    payload_bytes = container.payload_length
    manifest_bytes = len(container.manifest_payload)
    header_bytes = HEADER.size
    overhead_bytes = archive_bytes - payload_bytes
    return {
        "archive": str(Path(path)),
        "format": manifest["format"],
        "version": manifest["version"],
        "file_count": int(manifest["file_count"]),
        "logical_bytes": logical,
        "archive_bytes": archive_bytes,
        "payload_bytes": payload_bytes,
        "manifest_bytes": manifest_bytes,
        "header_bytes": header_bytes,
        "overhead_bytes": overhead_bytes,
        "ratio": round(logical / archive_bytes, 3) if archive_bytes else None,
        "payload_ratio": round(logical / payload_bytes, 3) if payload_bytes else None,
        "families": manifest.get("families", []),
        "fallback_files": manifest.get("fallback_files", []),
        "tree_entry_count": int(manifest.get("tree_entry_count", 0)),
        "file_mode_default": manifest.get("file_mode_default"),
        "file_mode_override_count": len(manifest.get("file_mode_overrides", {}))
        if isinstance(manifest.get("file_mode_overrides"), dict)
        else 0,
        "metadata_scope": manifest.get("metadata_scope", {}),
        "planner": manifest.get("planner"),
        "integrity": {
            "manifest_sha256": sha256_bytes(container.manifest_payload),
            "payload_sha256": container.payload_sha256,
            "health": "PASS",
        },
        "overhead_breakdown": {
            "payload": {
                "bytes": payload_bytes,
                "percent": round(payload_bytes / archive_bytes * 100, 2)
                if archive_bytes
                else None,
            },
            "manifest": {
                "bytes": manifest_bytes,
                "percent": round(manifest_bytes / archive_bytes * 100, 2)
                if archive_bytes
                else None,
            },
            "header": {
                "bytes": header_bytes,
                "percent": round(header_bytes / archive_bytes * 100, 2)
                if archive_bytes
                else None,
            },
        },
    }


def read_container(path: Path) -> ContainerRead:
    path = Path(path)
    actual_size = path.stat().st_size
    with path.open("rb") as handle:
        header_data = handle.read(HEADER.size)
        if len(header_data) < HEADER.size:
            raise ContainerError("Archive is too small to be a Smavg container")
        magic, manifest_len, payload_len, manifest_sha, payload_sha = HEADER.unpack(header_data)
        if magic != MAGIC:
            raise ContainerError("Invalid Smavg container magic")
        expected_size = HEADER.size + manifest_len + payload_len
        if actual_size != expected_size:
            raise ContainerError("Smavg container size does not match header")

        manifest_payload = handle.read(manifest_len)
        if len(manifest_payload) != manifest_len:
            raise ContainerError("Short read from manifest region")

    if bytes.fromhex(sha256_bytes(manifest_payload)) != manifest_sha:
        raise ContainerError("Manifest SHA-256 verification failed")

    try:
        raw_manifest = json.loads(zlib.decompress(manifest_payload).decode("utf-8"))
    except (ValueError, zlib.error) as exc:
        raise ContainerError("Manifest decode failed") from exc
    payload_sha_hex = payload_sha.hex()
    manifest = _validate_manifest(raw_manifest, payload_len, payload_sha_hex)
    container = ContainerRead(
        path=path,
        manifest=manifest,
        manifest_payload=manifest_payload,
        payload_offset=HEADER.size + manifest_len,
        payload_length=payload_len,
        payload_sha256=payload_sha_hex,
    )
    if _hash_file_region(path, container.payload_offset, payload_len) != payload_sha_hex:
        raise ContainerError("Payload SHA-256 verification failed")
    return container


def _validate_manifest(
    raw_manifest: Any,
    payload_length: int,
    payload_sha256_hex: str,
) -> Dict[str, object]:
    if not isinstance(raw_manifest, dict):
        raise ContainerError("Manifest root must be a JSON object")
    manifest: Dict[str, object] = raw_manifest

    for field, expected in TOP_LEVEL_FIELDS.items():
        _require_type(manifest, field, expected, "manifest")

    if manifest["format"] != "smavg-container":
        raise ContainerError("Unsupported Smavg container format")
    if manifest["version"] != 1:
        raise ContainerError("Unsupported Smavg container version")
    if manifest["manifest_codec"] != "zlib":
        raise ContainerError("Unsupported Smavg manifest codec")

    _require_planner(manifest)
    _require_non_negative_int(manifest, "file_count", "manifest")
    _require_non_negative_int(manifest, "logical_bytes", "manifest")
    payload_bytes = _require_non_negative_int(manifest, "payload_bytes", "manifest")
    payload_sha256 = _require_sha256(manifest, "payload_sha256", "manifest")
    if payload_bytes != payload_length:
        raise ContainerError("Manifest payload_bytes does not match payload region")
    if payload_sha256 != payload_sha256_hex:
        raise ContainerError("Manifest payload_sha256 does not match header")

    for index, family in enumerate(manifest["families"]):
        _validate_family_record(family, payload_length, index)
    for index, record in enumerate(manifest["fallback_files"]):
        _validate_fallback_record(record, payload_length, index)
    _validate_tree_manifest(manifest)
    return manifest


def _validate_family_record(raw_family: Any, payload_length: int, index: int) -> None:
    context = f"family record {index}"
    if not isinstance(raw_family, dict):
        raise ContainerError(f"{context} must be a JSON object")
    family: Dict[str, object] = raw_family
    for field, expected in FAMILY_FIELDS.items():
        _require_type(family, field, expected, context)
    if family["kind"] != "history_pack":
        raise ContainerError(f"Unknown family kind: {family.get('kind')}")
    if family["codec"] not in {HISTORY_PACK_V2_CODEC, HISTORY_PACK_V3_CODEC, HISTORY_PACK_V4_CODEC}:
        raise ContainerError(f"Unknown family codec: {family.get('codec')}")
    _require_payload_range(payload_length, family, context)
    _require_sha256(family, "sha256", context)
    _require_non_negative_int(family, "file_count", context)
    _require_non_negative_int(family, "logical_bytes", context)


def _validate_fallback_record(raw_record: Any, payload_length: int, index: int) -> None:
    context = f"fallback record {index}"
    if not isinstance(raw_record, dict):
        raise ContainerError(f"{context} must be a JSON object")
    record: Dict[str, object] = raw_record
    for field, expected in FALLBACK_FIELDS.items():
        _require_type(record, field, expected, context)
    if record["codec"] != "full_zlib":
        raise ContainerError(f"Unknown fallback codec: {record.get('codec')}")
    _safe_relative_path(record["path"])
    _require_payload_range(payload_length, record, context)
    _require_sha256(record, "payload_sha256", context)
    _require_sha256(record, "sha256", context)
    _require_non_negative_int(record, "logical_size", context)


def _validate_tree_manifest(manifest: Dict[str, object]) -> None:
    if "tree_entries" not in manifest:
        return
    entries = _require_type(manifest, "tree_entries", list, "manifest")
    tree_entry_count = _require_non_negative_int(manifest, "tree_entry_count", "manifest")
    if tree_entry_count != len(entries):
        raise ContainerError("Tree entry count verification failed")
    scope = manifest.get("metadata_scope")
    if scope is not None and not isinstance(scope, dict):
        raise ContainerError("manifest field metadata_scope must be an object")
    if "file_mode_default" in manifest:
        mode = _require_non_negative_int(manifest, "file_mode_default", "manifest")
        if mode > 0o7777:
            raise ContainerError("manifest field file_mode_default is outside permission range")
    if "file_mode_overrides" in manifest:
        overrides = _require_type(manifest, "file_mode_overrides", dict, "manifest")
        for path, raw_mode in overrides.items():
            if not isinstance(path, str):
                raise ContainerError("file_mode_overrides path must be a string")
            _safe_relative_path(path)
            if not isinstance(raw_mode, int) or isinstance(raw_mode, bool):
                raise ContainerError("file_mode_overrides values must be integers")
            if raw_mode < 0 or raw_mode > 0o7777:
                raise ContainerError("file_mode_overrides value is outside permission range")

    seen = set()
    for index, raw_entry in enumerate(entries):
        context = f"tree entry {index}"
        if not isinstance(raw_entry, dict):
            raise ContainerError(f"{context} must be a JSON object")
        entry: Dict[str, object] = raw_entry
        for field, expected in TREE_ENTRY_FIELDS.items():
            _require_type(entry, field, expected, context)
        normalized = _safe_relative_path(str(entry["path"]))
        if normalized in seen:
            raise ContainerError(f"Duplicate tree path: {normalized}")
        seen.add(normalized)
        kind = entry["kind"]
        if kind not in {"dir", "symlink"}:
            raise ContainerError(f"Unknown tree entry kind: {kind}")
        if kind == "dir":
            mode = _require_non_negative_int(entry, "mode", context)
            if mode > 0o7777:
                raise ContainerError(f"{context} field mode is outside permission range")
        if kind == "symlink":
            target = _require_type(entry, "target", str, context)
            if "\x00" in target:
                raise ContainerError(f"{context} symlink target contains a null byte")


def _require_planner(manifest: Dict[str, object]) -> None:
    if "planner" not in manifest:
        raise ContainerError("manifest missing required manifest field: planner")
    planner = manifest.get("planner")
    if planner is not None and not isinstance(planner, dict):
        raise ContainerError("manifest field planner must be an object or null")


def _require_type(
    record: Dict[str, object],
    field: str,
    expected_type: type,
    context: str,
) -> object:
    if field not in record:
        raise ContainerError(f"{context} missing required manifest field: {field}")
    value = record[field]
    if expected_type is int:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ContainerError(f"{context} field {field} must be an integer")
        return value
    if expected_type is bool:
        if not isinstance(value, bool):
            raise ContainerError(f"{context} field {field} must be a boolean")
        return value
    if not isinstance(value, expected_type):
        raise ContainerError(f"{context} field {field} has invalid type")
    return value


def _require_non_negative_int(record: Dict[str, object], field: str, context: str) -> int:
    value = _require_type(record, field, int, context)
    if value < 0:
        raise ContainerError(f"{context} field {field} must be non-negative")
    return value


def _require_sha256(record: Dict[str, object], field: str, context: str) -> str:
    value = _require_type(record, field, str, context)
    if len(value) != 64:
        raise ContainerError(f"{context} field {field} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ContainerError(f"{context} field {field} must be a SHA-256 hex digest") from exc
    return value


def _require_payload_range(
    payload_length: int,
    record: Dict[str, object],
    context: str,
) -> Tuple[int, int]:
    offset = _require_non_negative_int(record, "offset", context)
    length = _require_non_negative_int(record, "length", context)
    if offset + length > payload_length:
        raise ContainerError("Payload record points outside payload region")
    return offset, length


def _build_container_manifest(
    source_dir: Path,
    plan: ArchivePlan,
    payload_file: BinaryIO,
) -> Dict[str, object]:
    offset = 0
    payload_hasher = hashlib.sha256()
    families = []
    tree_entries, file_mode_default, file_mode_overrides = _build_tree_metadata(source_dir)

    for index, pack in enumerate(plan.history_packs):
        payload = pack.payload
        codec = getattr(pack, "codec", history_pack_codec(payload))
        payload_file.write(payload)
        payload_hasher.update(payload)
        families.append(
            {
                "id": f"family-{index}",
                "kind": pack.kind,
                "label": pack.label,
                "codec": codec,
                "offset": offset,
                "length": len(payload),
                "sha256": sha256_bytes(payload),
                "file_count": len(pack.manifest_files),
                "logical_bytes": pack.logical_bytes,
                "fallback_payload_bytes": pack.fallback_payload_bytes,
                "reason": pack.reason,
                "sample_paths": [str(item["path"]) for item in pack.manifest_files[:5]],
            }
        )
        offset += len(payload)

    fallback_files = []
    for fact in plan.fallback_files:
        length, payload_sha = _write_zlib_file_segment(fact.path, payload_file, payload_hasher)
        fallback_files.append(
            {
                "path": fact.relative,
                "codec": "full_zlib",
                "offset": offset,
                "length": length,
                "payload_sha256": payload_sha,
                "sha256": fact.sha256,
                "logical_size": fact.size,
                "is_text": fact.is_text,
            }
        )
        offset += length

    created_at = datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat().replace("+00:00", "Z")
    manifest: Dict[str, object] = {
        "format": "smavg-container",
        "version": 1,
        "created_at": created_at,
        "source_path": str(source_dir),
        "file_count": len(plan.files),
        "logical_bytes": sum(fact.size for fact in plan.files),
        "payload_bytes": offset,
        "payload_sha256": payload_hasher.hexdigest(),
        "manifest_codec": "zlib",
        "tree_entries": tree_entries,
        "file_mode_overrides": file_mode_overrides,
        "metadata_scope": {
            "regular_file_bytes": True,
            "relative_paths": True,
            "directories": True,
            "empty_directories": True,
            "file_modes": True,
            "directory_modes": True,
            "symlinks": True,
            "hardlink_identity": False,
            "timestamps": False,
            "ownership": False,
        },
        "families": families,
        "fallback_files": fallback_files,
        "planner": plan.report,
    }
    if file_mode_default is not None:
        manifest["file_mode_default"] = file_mode_default
    manifest["tree_entry_count"] = len(manifest["tree_entries"])
    return manifest


def _write_zlib_file_segment(
    source: Path,
    output: BinaryIO,
    payload_hasher: "hashlib._Hash",
) -> Tuple[int, str]:
    compressor = zlib.compressobj(level=9)
    segment_hasher = hashlib.sha256()
    written = 0
    with source.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            compressed = compressor.compress(chunk)
            if compressed:
                output.write(compressed)
                payload_hasher.update(compressed)
                segment_hasher.update(compressed)
                written += len(compressed)
    compressed = compressor.flush()
    if compressed:
        output.write(compressed)
        payload_hasher.update(compressed)
        segment_hasher.update(compressed)
        written += len(compressed)
    return written, segment_hasher.hexdigest()


def _build_tree_metadata(source_dir: Path) -> Tuple[List[Dict[str, object]], Optional[int], Dict[str, int]]:
    source_dir = Path(source_dir)
    entries: List[Dict[str, object]] = []
    file_modes: Dict[str, int] = {}

    def walk(path: Path) -> None:
        with os.scandir(path) as iterator:
            children = sorted(list(iterator), key=lambda item: item.name)
        for child in children:
            child_path = path / child.name
            relative = child_path.relative_to(source_dir).as_posix()
            try:
                child_stat = child.stat(follow_symlinks=False)
            except OSError as exc:
                raise ContainerError(f"Cannot read filesystem entry: {relative}") from exc
            mode = child_stat.st_mode
            if stat.S_ISLNK(mode):
                try:
                    target = os.readlink(child_path)
                except OSError as exc:
                    raise ContainerError(f"Cannot read symlink target: {relative}") from exc
                entries.append({"path": relative, "kind": "symlink", "target": target})
            elif stat.S_ISDIR(mode):
                entries.append(
                    {
                        "path": relative,
                        "kind": "dir",
                        "mode": stat.S_IMODE(mode),
                    }
                )
                walk(child_path)
            elif stat.S_ISREG(mode):
                file_modes[relative] = stat.S_IMODE(mode)
            else:
                raise ContainerError(f"Unsupported filesystem entry: {relative}")

    walk(source_dir)
    if not file_modes:
        return entries, None, {}
    default_mode = Counter(file_modes.values()).most_common(1)[0][0]
    overrides = {
        path: mode
        for path, mode in sorted(file_modes.items())
        if mode != default_mode
    }
    return entries, default_mode, overrides


def _verify_container_payloads(container: ContainerRead) -> Set[str]:
    manifest = container.manifest
    restored: Set[str] = set()
    logical_bytes = 0

    for family in manifest.get("families", []):
        for relative, data in _iter_family_files(container, family):
            normalized = _safe_relative_path(relative)
            if normalized in restored:
                raise ContainerError(f"Duplicate restored path: {normalized}")
            restored.add(normalized)
            logical_bytes += len(data)

    for record in manifest.get("fallback_files", []):
        normalized = _safe_relative_path(str(record["path"]))
        if normalized in restored:
            raise ContainerError(f"Duplicate restored path: {normalized}")
        logical_bytes += _verify_fallback_payload(container, record)
        restored.add(normalized)

    _verify_restored_totals(manifest, restored, logical_bytes)
    return restored


def _verify_restored_totals(
    manifest: Dict[str, object],
    restored: Set[str],
    logical_bytes: int,
) -> None:
    if len(restored) != int(manifest["file_count"]):
        raise ContainerError("Archive file-count verification failed")
    if logical_bytes != int(manifest["logical_bytes"]):
        raise ContainerError("Archive logical-size verification failed")
    file_mode_overrides = manifest.get("file_mode_overrides")
    if isinstance(file_mode_overrides, dict):
        unknown_modes = set(file_mode_overrides) - restored
        if unknown_modes:
            raise ContainerError("File mode override points at an unrestored file")


def _iter_family_files(
    container: ContainerRead,
    family: Dict[str, object],
) -> Iterable[Tuple[str, bytes]]:
    if _hash_payload_record(container, family) != family["sha256"]:
        raise ContainerError(f"Family payload SHA-256 failed: {family.get('id')}")
    if family.get("kind") != "history_pack":
        raise ContainerError(f"Unknown family kind: {family.get('kind')}")
    codec = family.get("codec")
    try:
        count = 0
        logical_bytes = 0
        if codec in {HISTORY_PACK_V3_CODEC, HISTORY_PACK_V4_CODEC}:
            with container.path.open("rb") as handle:
                iterator = iter_history_pack_stream(
                    handle,
                    container.payload_offset + int(family["offset"]),
                    int(family["length"]),
                )
                for relative, data in iterator:
                    count += 1
                    logical_bytes += len(data)
                    yield relative, data
            if count != int(family["file_count"]):
                raise ContainerError(f"Family file-count check failed: {family.get('id')}")
            if logical_bytes != int(family["logical_bytes"]):
                raise ContainerError(f"Family logical-size check failed: {family.get('id')}")
            return
        if codec == HISTORY_PACK_V2_CODEC:
            segment = _payload_segment(container, family)
            for relative, data in decode_history_pack(segment).items():
                count += 1
                logical_bytes += len(data)
                yield relative, data
            if count != int(family["file_count"]):
                raise ContainerError(f"Family file-count check failed: {family.get('id')}")
            if logical_bytes != int(family["logical_bytes"]):
                raise ContainerError(f"Family logical-size check failed: {family.get('id')}")
            return
        raise ContainerError(f"Unknown family codec: {codec}")
    except (ValueError, lzma.LZMAError) as exc:
        raise ContainerError(f"History family decode failed: {family.get('id')}") from exc


def _extract_family_file(
    container: ContainerRead,
    family: Dict[str, object],
    relative: str,
) -> bytes:
    if _hash_payload_record(container, family) != family["sha256"]:
        raise ContainerError(f"Family payload SHA-256 failed: {family.get('id')}")
    if family.get("kind") != "history_pack":
        raise ContainerError(f"Unknown family kind: {family.get('kind')}")
    codec = family.get("codec")
    try:
        with container.path.open("rb") as handle:
            if codec in {HISTORY_PACK_V3_CODEC, HISTORY_PACK_V4_CODEC}:
                return restore_history_pack_member_stream(
                    handle,
                    container.payload_offset + int(family["offset"]),
                    int(family["length"]),
                    relative,
                )
            if codec == HISTORY_PACK_V2_CODEC:
                segment = _payload_segment(container, family)
                files = decode_history_pack(segment)
                if relative not in files:
                    raise KeyError(relative)
                return files[relative]
        raise ContainerError(f"Unknown family codec: {codec}")
    except (ValueError, lzma.LZMAError) as exc:
        raise ContainerError(f"History family decode failed: {family.get('id')}") from exc


def _verify_fallback_payload(container: ContainerRead, record: Dict[str, object]) -> int:
    _safe_relative_path(str(record["path"]))
    if record.get("codec") != "full_zlib":
        raise ContainerError(f"Unknown fallback codec: {record.get('codec')}")

    payload_hasher = hashlib.sha256()
    data_hasher = hashlib.sha256()
    decompressor = zlib.decompressobj()
    logical_size = 0
    try:
        for chunk in _iter_payload_chunks(container, record):
            payload_hasher.update(chunk)
            data = decompressor.decompress(chunk)
            if data:
                data_hasher.update(data)
                logical_size += len(data)
        data = decompressor.flush()
    except zlib.error as exc:
        raise ContainerError(f"Fallback decode failed: {record.get('path')}") from exc
    if data:
        data_hasher.update(data)
        logical_size += len(data)
    if not decompressor.eof:
        raise ContainerError(f"Fallback decode failed: {record.get('path')}")
    if payload_hasher.hexdigest() != record["payload_sha256"]:
        raise ContainerError(f"Fallback payload SHA-256 failed: {record.get('path')}")
    if logical_size != int(record["logical_size"]):
        raise ContainerError(f"Fallback size check failed: {record.get('path')}")
    if data_hasher.hexdigest() != record["sha256"]:
        raise ContainerError(f"Fallback SHA-256 failed: {record.get('path')}")
    return logical_size


def _restore_fallback_record(
    container: ContainerRead,
    record: Dict[str, object],
    target: Path,
) -> int:
    if os.path.lexists(target):
        raise ContainerError(f"Restore target already exists: {record.get('path')}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.smavg-tmp-{os.getpid()}")
    payload_hasher = hashlib.sha256()
    data_hasher = hashlib.sha256()
    decompressor = zlib.decompressobj()
    logical_size = 0
    try:
        with temp.open("wb") as output:
            for chunk in _iter_payload_chunks(container, record):
                payload_hasher.update(chunk)
                data = decompressor.decompress(chunk)
                if data:
                    output.write(data)
                    data_hasher.update(data)
                    logical_size += len(data)
            data = decompressor.flush()
            if data:
                output.write(data)
                data_hasher.update(data)
                logical_size += len(data)
        if not decompressor.eof:
            raise ContainerError(f"Fallback decode failed: {record.get('path')}")
        if payload_hasher.hexdigest() != record["payload_sha256"]:
            raise ContainerError(f"Fallback payload SHA-256 failed: {record.get('path')}")
        if logical_size != int(record["logical_size"]):
            raise ContainerError(f"Fallback size check failed: {record.get('path')}")
        if data_hasher.hexdigest() != record["sha256"]:
            raise ContainerError(f"Fallback SHA-256 failed: {record.get('path')}")
        os.replace(temp, target)
        return logical_size
    except (ContainerError, OSError, zlib.error) as exc:
        temp.unlink(missing_ok=True)
        if isinstance(exc, zlib.error):
            raise ContainerError(f"Fallback decode failed: {record.get('path')}") from exc
        raise


def _payload_segment(container: ContainerRead, record: Dict[str, object]) -> bytes:
    offset, length = _require_payload_range(container.payload_length, record, "payload record")
    with container.path.open("rb") as handle:
        handle.seek(container.payload_offset + offset)
        data = handle.read(length)
    if len(data) != length:
        raise ContainerError("Short read from payload region")
    return data


def _hash_payload_record(container: ContainerRead, record: Dict[str, object]) -> str:
    offset, length = _require_payload_range(container.payload_length, record, "payload record")
    return _hash_file_region(container.path, container.payload_offset + offset, length)


def _iter_payload_chunks(
    container: ContainerRead,
    record: Dict[str, object],
    chunk_size: int = 1024 * 1024,
):
    offset, length = _require_payload_range(container.payload_length, record, "payload record")
    remaining = length
    with container.path.open("rb") as handle:
        handle.seek(container.payload_offset + offset)
        while remaining:
            chunk = handle.read(min(chunk_size, remaining))
            if not chunk:
                raise ContainerError("Short read from payload region")
            remaining -= len(chunk)
            yield chunk


def _hash_file_region(path: Path, offset: int, length: int) -> str:
    hasher = hashlib.sha256()
    remaining = length
    with path.open("rb") as handle:
        handle.seek(offset)
        while remaining:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ContainerError("Short read from payload region")
            remaining -= len(chunk)
            hasher.update(chunk)
    return hasher.hexdigest()


def _write_restored_bytes(destination: Path, relative: str, data: bytes) -> None:
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(target):
        raise ContainerError(f"Restore target already exists: {relative}")
    target.write_bytes(data)


def _tree_entries(manifest: Dict[str, object]) -> List[Dict[str, object]]:
    entries = manifest.get("tree_entries")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _apply_tree_modes(
    destination: Path,
    tree_entries: List[Dict[str, object]],
    files: Set[str],
    manifest: Dict[str, object],
) -> None:
    default_mode = manifest.get("file_mode_default")
    overrides = manifest.get("file_mode_overrides")
    override_modes = overrides if isinstance(overrides, dict) else {}
    for relative in files:
        if relative in override_modes:
            mode = int(override_modes[relative])
        elif isinstance(default_mode, int):
            mode = default_mode
        else:
            continue
        os.chmod(destination / relative, mode & 0o7777)
    # Apply child directory modes before parent modes so restrictive parent
    # permissions cannot block chmod on descendants during restore.
    for entry in sorted(
        (item for item in tree_entries if item["kind"] == "dir"),
        key=lambda item: str(item["path"]).count("/"),
        reverse=True,
    ):
        target = destination / str(entry["path"])
        os.chmod(target, int(entry["mode"]) & 0o7777)


def _safe_relative_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    normalized = path.as_posix()
    if normalized in {"", "."}:
        raise ContainerError("Archive path cannot be empty")
    if normalized.startswith("/") or normalized == ".." or normalized.startswith("../"):
        raise ContainerError(f"Unsafe archive path: {value}")
    if "/../" in f"/{normalized}/":
        raise ContainerError(f"Unsafe archive path: {value}")
    return normalized
