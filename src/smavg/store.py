"""SQLite-backed Smavg object store."""

from __future__ import annotations

import os
import json
import lzma
import shutil
import sqlite3
import time
import zlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .delta import DeltaError, apply_delta, create_delta, sha256_bytes
from .embedding import cosine, embed_bytes, vector_from_json, vector_to_json
from .history_pack import decode_history_pack
from .json_template import (
    refine_template_constants,
    render_json_template,
    template_to_bytes,
    try_json_template,
    try_json_template_parts,
    variables_to_bytes,
)
from .line_template import render_line_template, try_line_template
from .planner import ArchivePlan, build_archive_plan
from .table_codec import render_columnar_table, try_columnar_table


class SmavgError(RuntimeError):
    """Base error for store operations."""


@dataclass
class IngestResult:
    path: str
    object_id: int
    mode: str
    logical_size: int
    stored_size: int
    base_id: Optional[int]
    base_similarity: Optional[float]
    sha256: str


@dataclass
class ArchiveResult:
    snapshot_id: str
    source: str
    file_count: int
    logical_bytes: int
    stored_payload_bytes: int
    modes: Dict[str, int]
    plan: Optional[Dict[str, object]] = None


def apparent_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def disk_size(path: Path) -> int:
    def one(item: Path) -> int:
        stat = item.stat()
        blocks = getattr(stat, "st_blocks", 0)
        if blocks:
            return int(blocks) * 512
        return stat.st_size

    if path.is_file():
        return one(path)

    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += one(item)
    return total


class SmavgStore:
    def __init__(self, root: Path, enable_json_templates: bool = True):
        self.root = Path(root)
        self.objects_dir = self.root / "objects"
        self.snapshots_dir = self.root / "snapshots"
        self.pack_path = self.root / "payload.pack"
        self.db_path = self.root / "smavg.sqlite3"
        self.enable_json_templates = enable_json_templates

    def init(self) -> None:
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._write_config()
        with self._connect() as db:
            db.execute("PRAGMA page_size=1024")
            db.executescript(
                """
                PRAGMA journal_mode=DELETE;
                CREATE TABLE IF NOT EXISTS objects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mode TEXT NOT NULL,
                    base_id INTEGER REFERENCES objects(id),
                    sha256 TEXT NOT NULL,
                    logical_size INTEGER NOT NULL,
                    stored_size INTEGER NOT NULL,
                    payload_name TEXT,
                    embedding_json TEXT NOT NULL,
                    base_similarity REAL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_objects_sha256
                    ON objects(sha256);
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    object_id INTEGER NOT NULL REFERENCES objects(id),
                    source_path TEXT,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    sha256 TEXT NOT NULL UNIQUE,
                    stored_size INTEGER NOT NULL,
                    payload_name TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS blobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sha256 TEXT NOT NULL UNIQUE,
                    size INTEGER NOT NULL,
                    data BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS payloads (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sha256 TEXT NOT NULL UNIQUE,
                    size INTEGER NOT NULL,
                    pack_name TEXT NOT NULL,
                    offset INTEGER NOT NULL,
                    length INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY,
                    source_path TEXT NOT NULL,
                    file_count INTEGER NOT NULL,
                    logical_bytes INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshot_packs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
                    kind TEXT NOT NULL,
                    payload_name TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    file_count INTEGER NOT NULL,
                    logical_bytes INTEGER NOT NULL,
                    stored_size INTEGER NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS snapshot_files (
                    snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
                    path TEXT NOT NULL,
                    object_id INTEGER NOT NULL REFERENCES objects(id),
                    sha256 TEXT NOT NULL,
                    logical_size INTEGER NOT NULL,
                    mode TEXT NOT NULL,
                    stored_size INTEGER NOT NULL,
                    PRIMARY KEY(snapshot_id, path)
                );
                """
            )

    def reset(self) -> None:
        if self.root.exists():
            shutil.rmtree(self.root)
        self.init()

    def compact(self) -> None:
        self.init()
        db = self._connect()
        try:
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.DatabaseError:
            pass
        db.commit()
        db.execute("PRAGMA page_size=1024")
        db.execute("VACUUM")
        db.close()

    def put_file(self, source: Path, logical_path: Optional[str] = None) -> IngestResult:
        source = Path(source)
        if not source.is_file():
            raise SmavgError(f"Not a file: {source}")
        data = source.read_bytes()
        path = logical_path or source.name
        return self.put_bytes(path, data, source_path=str(source))

    def put_bytes(
        self,
        logical_path: str,
        data: bytes,
        source_path: Optional[str] = None,
        min_similarity: float = 0.10,
        candidate_limit: int = 8,
    ) -> IngestResult:
        self.init()
        path = self._normalize_logical_path(logical_path)
        digest = sha256_bytes(data)
        vector = embed_bytes(data)

        with self._connect() as db:
            existing = db.execute(
                "SELECT id, mode, logical_size, stored_size, base_id, "
                "base_similarity FROM objects WHERE sha256 = ? ORDER BY id LIMIT 1",
                (digest,),
            ).fetchone()
            if existing:
                self._upsert_file(db, path, int(existing["id"]), source_path)
                return IngestResult(
                    path=path,
                    object_id=int(existing["id"]),
                    mode=str(existing["mode"]),
                    logical_size=len(data),
                    stored_size=0,
                    base_id=existing["base_id"],
                    base_similarity=existing["base_similarity"],
                    sha256=digest,
                )

            full_payload = zlib.compress(data, level=9)
            best_mode = "full"
            best_payload = full_payload
            best_base_id = None
            best_similarity = None
            best_template_payload = None
            best_template_sha = None

            for mode, candidate, renderer in (
                ("csv_columnar", try_columnar_table(data), render_columnar_table),
                ("line_template", try_line_template(data), render_line_template),
            ):
                if candidate is None:
                    continue
                try:
                    reconstructed = renderer(candidate)
                except ValueError:
                    continue
                if reconstructed != data:
                    continue
                payload = zlib.compress(candidate, level=9)
                if len(payload) < len(best_payload):
                    best_mode = mode
                    best_payload = payload
                    best_base_id = None
                    best_similarity = None

            if self.enable_json_templates:
                template_candidate = try_json_template(data)
                if template_candidate is not None:
                    template_bytes, variables_bytes = template_candidate
                    template_payload = zlib.compress(template_bytes, level=9)
                    variable_payload = zlib.compress(variables_bytes, level=9)
                    template_sha = sha256_bytes(template_bytes)
                    template_exists = db.execute(
                        "SELECT id FROM templates WHERE sha256 = ?",
                        (template_sha,),
                    ).fetchone()
                    # Template mode is an archive strategy. The first file pays
                    # for the reusable structure; later files store only values.
                    # So the per-file decision compares variable payload size,
                    # while stats still count the template payload honestly.
                    if len(variable_payload) < len(best_payload):
                        best_mode = "json_template"
                        best_payload = variable_payload
                        best_base_id = (
                            int(template_exists["id"]) if template_exists else None
                        )
                        best_similarity = 1.0
                        best_template_payload = template_payload
                        best_template_sha = template_sha

            for base_id, similarity in self._candidate_bases(db, vector, candidate_limit):
                if similarity < min_similarity:
                    continue
                base_data = self.reconstruct_object(base_id)
                try:
                    delta = create_delta(base_data, data)
                    reconstructed = apply_delta(base_data, delta)
                except DeltaError:
                    continue
                if sha256_bytes(reconstructed) != digest:
                    continue
                payload = zlib.compress(delta, level=9)
                if len(payload) < len(best_payload):
                    best_mode = "delta"
                    best_payload = payload
                    best_base_id = base_id
                    best_similarity = similarity

            if best_mode == "json_template" and best_base_id is None:
                if best_template_payload is None or best_template_sha is None:
                    raise SmavgError("JSON template candidate is incomplete")
                template_payload_name = self._write_payload(db, best_template_payload)
                template_cursor = db.execute(
                    """
                    INSERT INTO templates(kind, sha256, stored_size, payload_name, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "json",
                        best_template_sha,
                        len(best_template_payload),
                        template_payload_name,
                        time.time(),
                    ),
                )
                best_base_id = int(template_cursor.lastrowid)

            payload_name = self._write_payload(db, best_payload)
            created_at = time.time()
            cursor = db.execute(
                """
                INSERT INTO objects (
                    mode, base_id, sha256, logical_size, stored_size, payload_name,
                    embedding_json, base_similarity, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    best_mode,
                    best_base_id,
                    digest,
                    len(data),
                    len(best_payload),
                    payload_name,
                    "[]" if best_mode == "json_template" else vector_to_json(vector),
                    best_similarity,
                    created_at,
                ),
            )
            object_id = int(cursor.lastrowid)
            self._upsert_file(db, path, object_id, source_path)
            return IngestResult(
                path=path,
                object_id=object_id,
                mode=best_mode,
                logical_size=len(data),
                stored_size=len(best_payload),
                base_id=best_base_id,
                base_similarity=best_similarity,
                sha256=digest,
            )

    def import_dir(self, source_dir: Path) -> List[IngestResult]:
        source_dir = Path(source_dir).resolve()
        if not source_dir.is_dir():
            raise SmavgError(f"Not a directory: {source_dir}")

        files = []
        store_root = self.root.resolve()
        for source in sorted(source_dir.rglob("*")):
            if not source.is_file():
                continue
            if self._is_relative_to(source.resolve(), store_root):
                continue
            logical_path = source.relative_to(source_dir).as_posix()
            files.append((source, logical_path, source.read_bytes()))

        if not self.enable_json_templates:
            return [
                self.put_bytes(logical_path, data, source_path=str(source))
                for source, logical_path, data in files
            ]

        grouped: Dict[bytes, List[Dict[str, Any]]] = defaultdict(list)
        fallback = []
        for source, logical_path, data in files:
            parts = try_json_template_parts(data)
            if parts is None:
                fallback.append((source, logical_path, data))
                continue
            template, variables = parts
            grouped[template_to_bytes(template)].append(
                {
                    "source": source,
                    "logical_path": logical_path,
                    "data": data,
                    "template": template,
                    "variables": variables,
                }
            )

        results = []
        for group in grouped.values():
            if len(group) < 2:
                item = group[0]
                fallback.append((item["source"], item["logical_path"], item["data"]))
                continue

            template = group[0]["template"]
            variable_lists = [item["variables"] for item in group]
            try:
                refined_template, refined_variables = refine_template_constants(
                    template,
                    variable_lists,
                )
            except ValueError:
                for item in group:
                    fallback.append((item["source"], item["logical_path"], item["data"]))
                continue

            refined_template_bytes = template_to_bytes(refined_template)
            refined_variable_bytes = [
                variables_to_bytes(values)
                for values in refined_variables
            ]
            template_cost = len(zlib.compress(refined_template_bytes, level=9))
            variable_cost = sum(
                len(zlib.compress(value_bytes, level=9))
                for value_bytes in refined_variable_bytes
            )
            full_cost = sum(len(zlib.compress(item["data"], level=9)) for item in group)

            if template_cost + variable_cost >= full_cost:
                for item in group:
                    fallback.append((item["source"], item["logical_path"], item["data"]))
                continue

            for item, variable_bytes in zip(group, refined_variable_bytes):
                results.append(
                    self.put_json_template_bytes(
                        item["logical_path"],
                        item["data"],
                        refined_template_bytes,
                        variable_bytes,
                        source_path=str(item["source"]),
                    )
                )

        for source, logical_path, data in fallback:
            results.append(self.put_bytes(logical_path, data, source_path=str(source)))
        return results

    def archive_dir(self, source_dir: Path, snapshot_id: Optional[str] = None) -> ArchiveResult:
        source_dir = Path(source_dir).resolve()
        if not source_dir.is_dir():
            raise SmavgError(f"Not a directory: {source_dir}")

        started_at = time.time()
        snapshot_id = snapshot_id or self._new_snapshot_id(started_at)
        self.init()
        with self._connect() as db:
            existing = db.execute(
                "SELECT id FROM snapshots WHERE id = ?",
                (snapshot_id,),
            ).fetchone()
            if existing is not None:
                raise SmavgError(f"Snapshot already exists: {snapshot_id}")

        archive_plan = build_archive_plan(source_dir, self.root)
        if archive_plan.history_packs:
            return self._archive_planned_dir(
                source_dir=source_dir,
                snapshot_id=snapshot_id,
                started_at=started_at,
                archive_plan=archive_plan,
            )

        results = self.import_dir(source_dir)
        current_files = self.list_files()
        logical_bytes = sum(int(item["logical_size"]) for item in current_files)
        modes: Dict[str, int] = {}
        for item in current_files:
            mode = str(item["mode"])
            modes[mode] = modes.get(mode, 0) + 1

        with self._connect() as db:
            db.execute(
                """
                INSERT INTO snapshots(id, source_path, file_count, logical_bytes, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    str(source_dir),
                    len(current_files),
                    logical_bytes,
                    started_at,
                ),
            )
            db.executemany(
                """
                INSERT INTO snapshot_files(
                    snapshot_id, path, object_id, sha256, logical_size, mode, stored_size
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_id,
                        str(item["path"]),
                        int(item["object_id"]),
                        str(item["sha256"]),
                        int(item["logical_size"]),
                        str(item["mode"]),
                        int(item["stored_size"]),
                    )
                    for item in current_files
                ],
            )

        self._write_snapshot_manifest(
            snapshot_id=snapshot_id,
            source_dir=source_dir,
            created_at=started_at,
            files=current_files,
        )

        return ArchiveResult(
            snapshot_id=snapshot_id,
            source=str(source_dir),
            file_count=len(current_files),
            logical_bytes=logical_bytes,
            stored_payload_bytes=sum(result.stored_size for result in results),
            modes=modes,
        )

    def _archive_planned_dir(
        self,
        source_dir: Path,
        snapshot_id: str,
        started_at: float,
        archive_plan: ArchivePlan,
    ) -> ArchiveResult:
        fallback_results = [
            self.put_bytes(fact.relative, fact.path.read_bytes(), source_path=str(fact.path))
            for fact in archive_plan.fallback_files
        ]
        fallback_files = [
            {
                "path": result.path,
                "object_id": result.object_id,
                "sha256": result.sha256,
                "logical_size": result.logical_size,
                "mode": result.mode,
                "stored_size": result.stored_size,
            }
            for result in fallback_results
        ]
        logical_bytes = sum(fact.size for fact in archive_plan.files)
        modes: Dict[str, int] = {}
        for pack in archive_plan.history_packs:
            modes[pack.kind] = modes.get(pack.kind, 0) + len(pack.manifest_files)
        for result in fallback_results:
            modes[result.mode] = modes.get(result.mode, 0) + 1

        pack_manifests = []
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO snapshots(id, source_path, file_count, logical_bytes, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    str(source_dir),
                    len(archive_plan.files),
                    logical_bytes,
                    started_at,
                ),
            )
            db.executemany(
                """
                INSERT INTO snapshot_files(
                    snapshot_id, path, object_id, sha256, logical_size, mode, stored_size
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        snapshot_id,
                        str(item["path"]),
                        int(item["object_id"]),
                        str(item["sha256"]),
                        int(item["logical_size"]),
                        str(item["mode"]),
                        int(item["stored_size"]),
                    )
                    for item in fallback_files
                ],
            )
            for pack in archive_plan.history_packs:
                payload_sha = sha256_bytes(pack.payload)
                payload_name = self._write_payload(db, pack.payload)
                cursor = db.execute(
                    """
                    INSERT INTO snapshot_packs(
                        snapshot_id, kind, payload_name, sha256, file_count,
                        logical_bytes, stored_size, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot_id,
                        pack.kind,
                        payload_name,
                        payload_sha,
                        len(pack.manifest_files),
                        pack.logical_bytes,
                        len(pack.payload),
                        started_at,
                    ),
                )
                pack_manifests.append(
                    {
                        "id": int(cursor.lastrowid),
                        "kind": pack.kind,
                        "codec": pack.codec,
                        "label": pack.label,
                        "sha256": payload_sha,
                        "payload_name": payload_name,
                        "file_count": len(pack.manifest_files),
                        "logical_bytes": pack.logical_bytes,
                        "stored_size": len(pack.payload),
                        "reason": pack.reason,
                    }
                )

        self._write_snapshot_manifest(
            snapshot_id=snapshot_id,
            source_dir=source_dir,
            created_at=started_at,
            files=fallback_files,
            packs=pack_manifests,
            file_count=len(archive_plan.files),
            logical_bytes=logical_bytes,
            planner=archive_plan.report,
        )

        return ArchiveResult(
            snapshot_id=snapshot_id,
            source=str(source_dir),
            file_count=len(archive_plan.files),
            logical_bytes=logical_bytes,
            stored_payload_bytes=sum(len(pack.payload) for pack in archive_plan.history_packs)
            + sum(result.stored_size for result in fallback_results),
            modes=modes,
            plan=archive_plan.report,
        )

    def put_json_template_bytes(
        self,
        logical_path: str,
        data: bytes,
        template_bytes: bytes,
        variables_bytes: bytes,
        source_path: Optional[str] = None,
    ) -> IngestResult:
        self.init()
        path = self._normalize_logical_path(logical_path)
        digest = sha256_bytes(data)

        try:
            reconstructed = render_json_template(template_bytes, variables_bytes)
        except ValueError as exc:
            raise SmavgError(f"Invalid JSON template for {path}") from exc
        if reconstructed != data:
            raise SmavgError(f"JSON template does not reconstruct {path}")

        template_payload = zlib.compress(template_bytes, level=9)
        variable_payload = zlib.compress(variables_bytes, level=9)
        template_sha = sha256_bytes(template_bytes)

        with self._connect() as db:
            existing = db.execute(
                "SELECT id, mode, logical_size, stored_size, base_id, "
                "base_similarity FROM objects WHERE sha256 = ? ORDER BY id LIMIT 1",
                (digest,),
            ).fetchone()
            if existing:
                self._upsert_file(db, path, int(existing["id"]), source_path)
                return IngestResult(
                    path=path,
                    object_id=int(existing["id"]),
                    mode=str(existing["mode"]),
                    logical_size=len(data),
                    stored_size=0,
                    base_id=existing["base_id"],
                    base_similarity=existing["base_similarity"],
                    sha256=digest,
                )

            template_row = db.execute(
                "SELECT id FROM templates WHERE sha256 = ?",
                (template_sha,),
            ).fetchone()
            if template_row is None:
                template_payload_name = self._write_payload(db, template_payload)
                template_cursor = db.execute(
                    """
                    INSERT INTO templates(kind, sha256, stored_size, payload_name, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        "json",
                        template_sha,
                        len(template_payload),
                        template_payload_name,
                        time.time(),
                    ),
                )
                template_id = int(template_cursor.lastrowid)
            else:
                template_id = int(template_row["id"])

            payload_name = self._write_payload(db, variable_payload)
            cursor = db.execute(
                """
                INSERT INTO objects (
                    mode, base_id, sha256, logical_size, stored_size, payload_name,
                    embedding_json, base_similarity, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "json_template",
                    template_id,
                    digest,
                    len(data),
                    len(variable_payload),
                    payload_name,
                    "[]",
                    1.0,
                    time.time(),
                ),
            )
            object_id = int(cursor.lastrowid)
            self._upsert_file(db, path, object_id, source_path)
            return IngestResult(
                path=path,
                object_id=object_id,
                mode="json_template",
                logical_size=len(data),
                stored_size=len(variable_payload),
                base_id=template_id,
                base_similarity=1.0,
                sha256=digest,
            )

    def reconstruct_object(self, object_id: int, seen: Optional[set] = None) -> bytes:
        self.init()
        seen = seen or set()
        if object_id in seen:
            raise SmavgError(f"Object cycle detected at {object_id}")
        seen.add(object_id)

        with self._connect() as db:
            record = db.execute(
                "SELECT * FROM objects WHERE id = ?",
                (object_id,),
            ).fetchone()
        if record is None:
            raise SmavgError(f"Unknown object id: {object_id}")

        payload = self._read_payload(record["payload_name"])
        mode = record["mode"]
        if mode == "full":
            data = zlib.decompress(payload)
        elif mode == "delta":
            if record["base_id"] is None:
                raise SmavgError(f"Delta object {object_id} has no base")
            base = self.reconstruct_object(int(record["base_id"]), seen)
            data = apply_delta(base, zlib.decompress(payload))
        elif mode == "json_template":
            if record["base_id"] is None:
                raise SmavgError(f"JSON template object {object_id} has no template")
            template_payload = self._read_template_payload(int(record["base_id"]))
            data = render_json_template(
                zlib.decompress(template_payload),
                zlib.decompress(payload),
            )
        elif mode == "line_template":
            data = render_line_template(zlib.decompress(payload))
        elif mode == "csv_columnar":
            data = render_columnar_table(zlib.decompress(payload))
        else:
            raise SmavgError(f"Unknown object mode: {mode}")

        digest = sha256_bytes(data)
        if digest != record["sha256"]:
            raise SmavgError(f"Object {object_id} failed SHA-256 verification")
        if len(data) != int(record["logical_size"]):
            raise SmavgError(f"Object {object_id} failed size verification")
        return data

    def get_file(self, logical_path: str) -> bytes:
        path = self._normalize_logical_path(logical_path)
        with self._connect() as db:
            row = db.execute(
                "SELECT object_id FROM files WHERE path = ?",
                (path,),
            ).fetchone()
        if row is None:
            raise SmavgError(f"No such stored file: {path}")
        return self.reconstruct_object(int(row["object_id"]))

    def write_file(self, logical_path: str, destination: Path) -> None:
        data = self.get_file(logical_path)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)

    def export_dir(self, destination: Path) -> int:
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        count = 0
        for item in self.list_files():
            target = destination / item["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.reconstruct_object(int(item["object_id"])))
            count += 1
        return count

    def restore_snapshot(self, snapshot_id: str, destination: Path) -> int:
        snapshot_id = self.resolve_snapshot_id(snapshot_id)
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        count = 0
        for item in self.list_snapshot_files(snapshot_id):
            target = destination / str(item["path"])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.reconstruct_object(int(item["object_id"])))
            count += 1
        for pack in self.list_snapshot_packs(snapshot_id):
            files = self._decode_snapshot_pack(int(pack["id"]))
            for relative, data in sorted(files.items()):
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                count += 1
        return count

    def verify_dir(self, source_dir: Path) -> Tuple[bool, List[str]]:
        source_dir = Path(source_dir).resolve()
        if not source_dir.is_dir():
            raise SmavgError(f"Not a directory: {source_dir}")

        failures = []
        seen = set()
        for source in sorted(source_dir.rglob("*")):
            if not source.is_file():
                continue
            if self._is_relative_to(source.resolve(), self.root.resolve()):
                continue
            logical_path = source.relative_to(source_dir).as_posix()
            seen.add(logical_path)
            try:
                stored = self.get_file(logical_path)
            except SmavgError as exc:
                failures.append(f"{logical_path}: {exc}")
                continue
            actual = source.read_bytes()
            if stored != actual:
                failures.append(f"{logical_path}: bytes differ")

        stored_paths = {item["path"] for item in self.list_files()}
        for missing_source in sorted(stored_paths - seen):
            failures.append(f"{missing_source}: stored file has no source match")

        return not failures, failures

    def verify_snapshot_against_dir(
        self,
        snapshot_id: str,
        source_dir: Path,
    ) -> Tuple[bool, List[str]]:
        snapshot_id = self.resolve_snapshot_id(snapshot_id)
        source_dir = Path(source_dir).resolve()
        if not source_dir.is_dir():
            raise SmavgError(f"Not a directory: {source_dir}")

        failures = []
        snapshot_files = {str(item["path"]): item for item in self.list_snapshot_files(snapshot_id)}
        snapshot_pack_files: Dict[str, bytes] = {}
        for pack in self.list_snapshot_packs(snapshot_id):
            try:
                for relative, data in self._decode_snapshot_pack(int(pack["id"])).items():
                    snapshot_pack_files[relative] = data
            except SmavgError as exc:
                failures.append(f"pack {pack['id']}: {exc}")
        seen = set()
        for source in sorted(source_dir.rglob("*")):
            if not source.is_file():
                continue
            if self._is_relative_to(source.resolve(), self.root.resolve()):
                continue
            logical_path = source.relative_to(source_dir).as_posix()
            seen.add(logical_path)
            item = snapshot_files.get(logical_path)
            packed = snapshot_pack_files.get(logical_path)
            if item is None and packed is None:
                failures.append(f"{logical_path}: source file missing from snapshot")
                continue
            actual = source.read_bytes()
            if item is not None:
                if sha256_bytes(actual) != item["sha256"]:
                    failures.append(f"{logical_path}: source SHA-256 differs from snapshot")
                    continue
                restored = self.reconstruct_object(int(item["object_id"]))
            else:
                restored = packed
            if restored != actual:
                failures.append(f"{logical_path}: restored bytes differ from source")

        snapshot_paths = set(snapshot_files) | set(snapshot_pack_files)
        for missing_source in sorted(snapshot_paths - seen):
            failures.append(f"{missing_source}: snapshot file has no source match")

        return not failures, failures

    def verify_snapshot_integrity(self, snapshot_id: str) -> Tuple[bool, List[str]]:
        snapshot_id = self.resolve_snapshot_id(snapshot_id)
        failures = []
        for item in self.list_snapshot_files(snapshot_id):
            try:
                data = self.reconstruct_object(int(item["object_id"]))
            except SmavgError as exc:
                failures.append(f"{item['path']}: {exc}")
                continue
            if len(data) != int(item["logical_size"]):
                failures.append(f"{item['path']}: restored size differs from snapshot")
            if sha256_bytes(data) != item["sha256"]:
                failures.append(f"{item['path']}: restored SHA-256 differs from snapshot")
        for pack in self.list_snapshot_packs(snapshot_id):
            try:
                self._decode_snapshot_pack(int(pack["id"]))
            except SmavgError as exc:
                failures.append(f"pack {pack['id']}: {exc}")
        return not failures, failures

    def list_files(self) -> List[Dict[str, object]]:
        self.init()
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT f.path, f.object_id, o.mode, o.logical_size, o.stored_size,
                       o.base_id, o.base_similarity, o.sha256
                FROM files f
                JOIN objects o ON o.id = f.object_id
                ORDER BY f.path
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_snapshots(self) -> List[Dict[str, object]]:
        self.init()
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, source_path, file_count, logical_bytes, created_at
                FROM snapshots
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def list_snapshot_files(self, snapshot_id: str) -> List[Dict[str, object]]:
        snapshot_id = self.resolve_snapshot_id(snapshot_id)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT path, object_id, sha256, logical_size, mode, stored_size
                FROM snapshot_files
                WHERE snapshot_id = ?
                ORDER BY path
                """,
                (snapshot_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_snapshot_packs(self, snapshot_id: str) -> List[Dict[str, object]]:
        snapshot_id = self.resolve_snapshot_id(snapshot_id)
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, snapshot_id, kind, payload_name, sha256,
                       file_count, logical_bytes, stored_size, created_at
                FROM snapshot_packs
                WHERE snapshot_id = ?
                ORDER BY id
                """,
                (snapshot_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def snapshot_report(self, snapshot_id: str = "latest") -> Dict[str, object]:
        snapshot_id = self.resolve_snapshot_id(snapshot_id)
        manifest_path = self.snapshots_dir / f"{snapshot_id}.json"
        if not manifest_path.exists():
            raise SmavgError(f"Missing snapshot manifest: {snapshot_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return {
            "snapshot": manifest,
            "stats": self.stats(),
            "packs": self.list_snapshot_packs(snapshot_id),
            "files": self.list_snapshot_files(snapshot_id),
        }

    def resolve_snapshot_id(self, snapshot_id: str) -> str:
        self.init()
        with self._connect() as db:
            if snapshot_id == "latest":
                row = db.execute(
                    """
                    SELECT id FROM snapshots
                    ORDER BY created_at DESC, id DESC
                    LIMIT 1
                    """
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT id FROM snapshots WHERE id = ?",
                    (snapshot_id,),
                ).fetchone()
        if row is None:
            raise SmavgError(f"No such snapshot: {snapshot_id}")
        return str(row["id"])

    def stats(self) -> Dict[str, object]:
        self.init()
        with self._connect() as db:
            current = db.execute(
                """
                SELECT COUNT(*) AS file_count,
                       COALESCE(SUM(o.logical_size), 0) AS logical_bytes
                FROM files f
                JOIN objects o ON o.id = f.object_id
                """
            ).fetchone()
            objects = db.execute(
                """
                SELECT COUNT(*) AS object_count,
                       COALESCE(SUM(logical_size), 0) AS object_logical_bytes,
                       COALESCE(SUM(stored_size), 0) AS payload_bytes
                FROM objects
                """
            ).fetchone()
            templates = db.execute(
                """
                SELECT COUNT(*) AS template_count,
                       COALESCE(SUM(stored_size), 0) AS template_bytes
                FROM templates
                """
            ).fetchone()
            packs = db.execute(
                """
                SELECT COUNT(*) AS snapshot_pack_count,
                       COALESCE(SUM(stored_size), 0) AS snapshot_pack_bytes,
                       COALESCE(SUM(file_count), 0) AS snapshot_pack_file_count,
                       COALESCE(SUM(logical_bytes), 0) AS snapshot_pack_logical_bytes
                FROM snapshot_packs
                """
            ).fetchone()
            modes = db.execute(
                "SELECT mode, COUNT(*) AS count FROM objects GROUP BY mode"
            ).fetchall()
            pack_modes = db.execute(
                """
                SELECT kind AS mode, COALESCE(SUM(file_count), 0) AS count
                FROM snapshot_packs
                GROUP BY kind
                """
            ).fetchall()
            snapshots = db.execute(
                "SELECT COUNT(*) AS snapshot_count FROM snapshots"
            ).fetchone()
            latest_snapshot = db.execute(
                """
                SELECT file_count, logical_bytes
                FROM snapshots
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """
            ).fetchone()

        store_apparent = apparent_size(self.root) if self.root.exists() else 0
        store_disk = disk_size(self.root) if self.root.exists() else 0
        file_count = int(current["file_count"])
        logical = int(current["logical_bytes"])
        if latest_snapshot is not None:
            file_count = int(latest_snapshot["file_count"])
            logical = int(latest_snapshot["logical_bytes"])
        object_payload = int(objects["payload_bytes"])
        template_payload = int(templates["template_bytes"])
        snapshot_pack_payload = int(packs["snapshot_pack_bytes"])
        payload = object_payload + template_payload + snapshot_pack_payload
        object_modes = {str(row["mode"]): int(row["count"]) for row in modes}
        snapshot_pack_modes = {str(row["mode"]): int(row["count"]) for row in pack_modes}
        return {
            "file_count": file_count,
            "object_count": int(objects["object_count"]),
            "template_count": int(templates["template_count"]),
            "snapshot_pack_count": int(packs["snapshot_pack_count"]),
            "snapshot_count": int(snapshots["snapshot_count"]),
            "logical_bytes": logical,
            "object_logical_bytes": int(objects["object_logical_bytes"]),
            "snapshot_pack_logical_bytes": int(packs["snapshot_pack_logical_bytes"]),
            "object_payload_bytes": object_payload,
            "template_payload_bytes": template_payload,
            "snapshot_pack_payload_bytes": snapshot_pack_payload,
            "payload_bytes": payload,
            "store_apparent_bytes": store_apparent,
            "store_disk_bytes": store_disk,
            "payload_ratio": round(logical / payload, 3) if payload else None,
            "apparent_ratio": round(logical / store_apparent, 3) if store_apparent else None,
            "disk_ratio": round(logical / store_disk, 3) if store_disk else None,
            "object_modes": object_modes,
            "snapshot_pack_file_modes": snapshot_pack_modes,
            "modes": {
                "objects": object_modes,
                "snapshot_pack_files": snapshot_pack_modes,
            },
        }

    def _connect(self) -> sqlite3.Connection:
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.db_path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _new_snapshot_id(created_at: float) -> str:
        stamp = datetime.fromtimestamp(created_at, tz=timezone.utc)
        return stamp.strftime("%Y%m%dT%H%M%SZ")

    def _write_config(self) -> None:
        config_path = self.root / "config.json"
        if config_path.exists():
            return
        config = {
            "format": "smavg-archive",
            "version": 1,
            "created_by": "smavg",
            "storage": {
                "metadata": "sqlite",
                "payloads": "append-only pack",
                "snapshots": "json manifests plus sqlite index",
            },
        }
        temp = config_path.with_suffix(".tmp")
        temp.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, config_path)

    def _write_snapshot_manifest(
        self,
        snapshot_id: str,
        source_dir: Path,
        created_at: float,
        files: List[Dict[str, object]],
        packs: Optional[List[Dict[str, object]]] = None,
        file_count: Optional[int] = None,
        logical_bytes: Optional[int] = None,
        planner: Optional[Dict[str, object]] = None,
    ) -> None:
        packs = packs or []
        file_count = len(files) if file_count is None else file_count
        logical_bytes = (
            sum(int(item["logical_size"]) for item in files)
            if logical_bytes is None
            else logical_bytes
        )
        manifest = {
            "format": "smavg-snapshot",
            "version": 1,
            "id": snapshot_id,
            "created_at": datetime.fromtimestamp(created_at, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "source_path": str(source_dir),
            "file_count": file_count,
            "logical_bytes": logical_bytes,
            "packs": packs,
            "planner": planner,
            "files": [
                {
                    "path": str(item["path"]),
                    "object_id": int(item["object_id"]),
                    "sha256": str(item["sha256"]),
                    "logical_size": int(item["logical_size"]),
                    "mode": str(item["mode"]),
                    "stored_size": int(item["stored_size"]),
                }
                for item in files
            ],
        }
        target = self.snapshots_dir / f"{snapshot_id}.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temp, target)

    def _decode_snapshot_pack(self, pack_id: int) -> Dict[str, bytes]:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT kind, payload_name, sha256, file_count, logical_bytes
                FROM snapshot_packs
                WHERE id = ?
                """,
                (pack_id,),
            ).fetchone()
        if row is None:
            raise SmavgError(f"Unknown snapshot pack: {pack_id}")

        payload = self._read_payload(str(row["payload_name"]))
        if sha256_bytes(payload) != row["sha256"]:
            raise SmavgError(f"Snapshot pack {pack_id} failed payload SHA-256 verification")

        kind = str(row["kind"])
        if kind == "history_pack":
            try:
                files = decode_history_pack(payload)
            except (ValueError, lzma.LZMAError) as exc:
                raise SmavgError(f"Invalid history pack {pack_id}") from exc
        else:
            raise SmavgError(f"Unknown snapshot pack kind: {kind}")

        logical_bytes = sum(len(data) for data in files.values())
        if len(files) != int(row["file_count"]):
            raise SmavgError(f"Snapshot pack {pack_id} failed file-count verification")
        if logical_bytes != int(row["logical_bytes"]):
            raise SmavgError(f"Snapshot pack {pack_id} failed logical-size verification")
        return files

    def _candidate_bases(
        self,
        db: sqlite3.Connection,
        vector: List[float],
        limit: int,
    ) -> Iterable[Tuple[int, float]]:
        # Phase 1 avoids delta-on-delta chains. They are correct, but they make
        # ingest cost grow quickly because every candidate has to be rebuilt
        # before proving the new delta. Full objects are stable base checkpoints.
        rows = db.execute(
            "SELECT id, embedding_json FROM objects WHERE mode != 'delta'"
        ).fetchall()
        scored = []
        for row in rows:
            similarity = cosine(vector, vector_from_json(row["embedding_json"]))
            scored.append((int(row["id"]), float(similarity)))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]

    def _write_payload(self, db: sqlite3.Connection, payload: bytes) -> str:
        digest = sha256_bytes(payload)
        row = db.execute(
            "SELECT id FROM payloads WHERE sha256 = ?",
            (digest,),
        ).fetchone()
        if row is not None:
            return f"pack:{int(row['id'])}"

        self.root.mkdir(parents=True, exist_ok=True)
        offset = self.pack_path.stat().st_size if self.pack_path.exists() else 0
        with self.pack_path.open("ab") as pack:
            pack.write(payload)
        cursor = db.execute(
            """
            INSERT INTO payloads(sha256, size, pack_name, offset, length)
            VALUES (?, ?, ?, ?, ?)
            """,
            (digest, len(payload), self.pack_path.name, offset, len(payload)),
        )
        return f"pack:{int(cursor.lastrowid)}"

    def _write_payload_file(self, payload: bytes) -> str:
        name = f"{sha256_bytes(payload)}.obj"
        target = self.objects_dir / name
        if not target.exists():
            temp = target.with_suffix(".tmp")
            temp.write_bytes(payload)
            os.replace(temp, target)
        return name

    def _read_payload(self, payload_name: str) -> bytes:
        if not payload_name:
            raise SmavgError("Object has no payload")
        if payload_name.startswith("pack:"):
            payload_id = int(payload_name.split(":", 1)[1])
            with self._connect() as db:
                row = db.execute(
                    "SELECT pack_name, offset, length FROM payloads WHERE id = ?",
                    (payload_id,),
                ).fetchone()
            if row is None:
                raise SmavgError(f"Missing packed payload: {payload_name}")
            pack_path = self.root / str(row["pack_name"])
            if not pack_path.exists():
                raise SmavgError(f"Missing payload pack: {pack_path.name}")
            with pack_path.open("rb") as pack:
                pack.seek(int(row["offset"]))
                data = pack.read(int(row["length"]))
            if len(data) != int(row["length"]):
                raise SmavgError(f"Short read from payload pack: {payload_name}")
            return data
        if payload_name.startswith("blob:"):
            blob_id = int(payload_name.split(":", 1)[1])
            with self._connect() as db:
                row = db.execute(
                    "SELECT data FROM blobs WHERE id = ?",
                    (blob_id,),
                ).fetchone()
            if row is None:
                raise SmavgError(f"Missing blob payload: {payload_name}")
            return bytes(row["data"])
        path = self.objects_dir / payload_name
        if not path.exists():
            raise SmavgError(f"Missing payload: {payload_name}")
        return path.read_bytes()

    def _read_template_payload(self, template_id: int) -> bytes:
        with self._connect() as db:
            row = db.execute(
                "SELECT payload_name FROM templates WHERE id = ?",
                (template_id,),
            ).fetchone()
        if row is None:
            raise SmavgError(f"Missing template: {template_id}")
        return self._read_payload(row["payload_name"])

    @staticmethod
    def _upsert_file(
        db: sqlite3.Connection,
        path: str,
        object_id: int,
        source_path: Optional[str],
    ) -> None:
        db.execute(
            """
            INSERT INTO files(path, object_id, source_path, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                object_id = excluded.object_id,
                source_path = excluded.source_path,
                updated_at = excluded.updated_at
            """,
            (path, object_id, source_path, time.time()),
        )

    @staticmethod
    def _normalize_logical_path(value: str) -> str:
        raw = value.replace("\\", "/")
        path = PurePosixPath(raw)
        normalized = path.as_posix()
        if normalized in {"", "."}:
            raise SmavgError("Logical path cannot be empty")
        if normalized.startswith("/") or normalized == ".." or normalized.startswith("../"):
            raise SmavgError(f"Unsafe logical path: {value}")
        if "/../" in f"/{normalized}/":
            raise SmavgError(f"Unsafe logical path: {value}")
        return normalized

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
            return True
        except ValueError:
            return False
