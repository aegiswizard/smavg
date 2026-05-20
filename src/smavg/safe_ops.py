"""Safe archive and quarantine operations for Smavg."""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .container import ContainerError, pack_container, restore_container, verify_container
from .context import ContextError, build_context_report
from .delta import sha256_bytes
from .store import apparent_size, disk_size


class SafePackError(RuntimeError):
    """Raised when safe pack or quarantine cannot complete."""


@dataclass(frozen=True)
class TreeEntry:
    kind: str
    path: str
    size: int = 0
    sha256: str = ""
    mode: int = 0
    target: str = ""


def safe_pack(
    *,
    source: Path,
    archive: Path,
    work_dir: Path,
    quarantine_dir: Optional[Path] = None,
    move_to_quarantine: bool = False,
) -> Dict[str, object]:
    """Pack, verify, restore-compare, and optionally move source to quarantine."""
    source = Path(source).expanduser().resolve()
    archive = Path(archive).expanduser()
    work_dir = Path(work_dir).expanduser().resolve()
    if not source.is_dir():
        raise SafePackError(f"Not a directory: {source}")
    if _is_relative_to(archive.resolve(), source):
        raise SafePackError("Archive output must be outside the source directory")
    if move_to_quarantine and quarantine_dir is None:
        raise SafePackError("--move-to-quarantine requires --quarantine-dir")

    work_dir.mkdir(parents=True, exist_ok=True)
    source_apparent_bytes = apparent_size(source)
    source_disk_bytes = disk_size(source)
    context_report = _cleanup_context_report(source)
    archive_report = pack_container(source, archive)
    ok, failures = verify_container(archive)
    if not ok:
        raise SafePackError("Archive verification failed: " + "; ".join(failures))
    archive_path = Path(archive).expanduser().resolve()
    archive_apparent_bytes = apparent_size(archive_path)
    archive_disk_bytes = disk_size(archive_path)

    restore_root = Path(tempfile.mkdtemp(prefix="smavg-restore-", dir=work_dir))
    try:
        restored_count = restore_container(archive, restore_root)
        compare = compare_trees(source, restore_root)
        if not compare["pass"]:
            raise SafePackError("Restored tree comparison failed")

        quarantined_path = None
        entries = _collect_tree(source)
        cleanup_projection = _cleanup_projection(
            source=source,
            archive=archive_path,
            source_apparent_bytes=source_apparent_bytes,
            source_disk_bytes=source_disk_bytes,
            archive_apparent_bytes=archive_apparent_bytes,
            archive_disk_bytes=archive_disk_bytes,
            context_report=context_report,
            entries=entries,
        )
        if move_to_quarantine:
            assert quarantine_dir is not None
            quarantine_dir = Path(quarantine_dir).expanduser().resolve()
            quarantine_dir.mkdir(parents=True, exist_ok=True)
            target = _unique_quarantine_path(quarantine_dir, source.name)
            shutil.move(str(source), str(target))
            quarantined_path = str(target)
            cleanup_projection["quarantine"]["status"] = "moved"
            cleanup_projection["quarantine"]["path"] = quarantined_path
            cleanup_projection["quarantine"]["active_path_disk_bytes_moved"] = source_disk_bytes
            cleanup_projection["purge_projection"]["additional_disk_bytes_freed_if_quarantine_purged_from_current_state"] = source_disk_bytes
        else:
            cleanup_projection["quarantine"]["status"] = "not_moved"

        report = {
            "format": "smavg-safe-pack-report",
            "version": 1,
            "generated_at": _now(),
            "source": str(source),
            "archive": str(Path(archive)),
            "work_dir": str(work_dir),
            "archive_report": archive_report,
            "archive_verify": {"pass": True, "failures": []},
            "restore_compare": compare,
            "restored_file_count": restored_count,
            "cleanup_projection": cleanup_projection,
            "importance_brief": cleanup_projection["importance_brief"],
            "source_moved_to_quarantine": bool(quarantined_path),
            "quarantined_path": quarantined_path,
            "cleanup_allowed": bool(quarantined_path),
            "delete_performed": False,
            "trust_rule": (
                "Safe-pack never deletes source data. Cleanup is only safe after "
                "pack, verify, restore, and tree comparison pass; this command "
                "can move the source to quarantine but does not destroy it."
            ),
        }
        return report
    finally:
        shutil.rmtree(restore_root, ignore_errors=True)


def compare_trees(source: Path, restored: Path) -> Dict[str, object]:
    source_entries = _collect_tree(Path(source))
    restored_entries = _collect_tree(Path(restored))
    source_map = {entry.path: entry for entry in source_entries}
    restored_map = {entry.path: entry for entry in restored_entries}
    failures: List[str] = []

    for path in sorted(set(source_map) - set(restored_map)):
        failures.append(f"Missing restored path: {path}")
    for path in sorted(set(restored_map) - set(source_map)):
        failures.append(f"Unexpected restored path: {path}")
    for path in sorted(set(source_map) & set(restored_map)):
        left = source_map[path]
        right = restored_map[path]
        if left.kind != right.kind:
            failures.append(f"Kind mismatch for {path}: {left.kind} != {right.kind}")
            continue
        if left.kind == "file":
            if left.size != right.size:
                failures.append(f"Size mismatch for {path}")
            if left.sha256 != right.sha256:
                failures.append(f"SHA-256 mismatch for {path}")
            if left.mode != right.mode:
                failures.append(f"Mode mismatch for {path}: {oct(left.mode)} != {oct(right.mode)}")
        elif left.kind == "symlink" and left.target != right.target:
            failures.append(f"Symlink target mismatch for {path}")
        elif left.kind == "dir" and left.mode != right.mode:
            failures.append(f"Directory mode mismatch for {path}: {oct(left.mode)} != {oct(right.mode)}")

    file_count = sum(1 for entry in source_entries if entry.kind == "file")
    dir_count = sum(1 for entry in source_entries if entry.kind == "dir")
    symlink_count = sum(1 for entry in source_entries if entry.kind == "symlink")
    return {
        "pass": not failures,
        "failures": failures,
        "file_count": file_count,
        "dir_count": dir_count,
        "symlink_count": symlink_count,
        "metadata_scope": {
            "regular_file_bytes": True,
            "relative_paths": True,
            "directories": True,
            "empty_directories": True,
            "file_modes": True,
            "directory_modes": True,
            "symlinks": True,
            "timestamps": False,
            "ownership": False,
            "acl": False,
            "xattrs": False,
        },
    }


def _cleanup_context_report(source: Path) -> Dict[str, object]:
    try:
        return build_context_report(source, budget_tokens=3000)
    except (ContextError, OSError) as exc:
        return {
            "format": "smavg-cleanup-context-error",
            "error": str(exc),
            "original_tokens_estimate": 0,
            "brief_tokens_estimate": 0,
            "token_reduction_ratio": None,
            "families_detected": 0,
            "family_coverage_percent": 0.0,
            "assessment": {"status": "unknown", "finding": str(exc)},
        }


def _cleanup_projection(
    *,
    source: Path,
    archive: Path,
    source_apparent_bytes: int,
    source_disk_bytes: int,
    archive_apparent_bytes: int,
    archive_disk_bytes: int,
    context_report: Dict[str, object],
    entries: List[TreeEntry],
) -> Dict[str, object]:
    raw_tokens = int(context_report.get("original_tokens_estimate", 0))
    brief_tokens = int(context_report.get("brief_tokens_estimate", 0))
    token_saved = max(0, raw_tokens - brief_tokens)
    net_disk_saved = source_disk_bytes - archive_disk_bytes
    net_apparent_saved = source_apparent_bytes - archive_apparent_bytes
    return {
        "source": str(source),
        "archive": str(archive),
        "source_apparent_bytes": source_apparent_bytes,
        "source_disk_bytes": source_disk_bytes,
        "archive_apparent_bytes": archive_apparent_bytes,
        "archive_disk_bytes": archive_disk_bytes,
        "quarantine": {
            "status": "not_moved",
            "path": None,
            "active_path_disk_bytes_moved": 0,
            "disk_bytes_freed_now": 0,
            "truth": (
                "Moving a folder to quarantine cleans the active path but does not "
                "free disk space when quarantine remains on the same disk."
            ),
        },
        "purge_projection": {
            "additional_disk_bytes_freed_if_quarantine_purged_from_current_state": 0,
            "net_disk_bytes_saved_after_purge_and_archive_kept": net_disk_saved,
            "net_apparent_bytes_saved_after_purge_and_archive_kept": net_apparent_saved,
            "archive_disk_bytes_remaining": archive_disk_bytes,
            "archive_apparent_bytes_remaining": archive_apparent_bytes,
            "net_disk_reduction_ratio_after_purge": _ratio(source_disk_bytes, archive_disk_bytes),
            "truth": (
                "Real disk recovery happens only when the quarantined original is "
                "purged or moved off this disk. The .smavg archive remains and must "
                "be kept verified for restore."
            ),
        },
        "token_projection": {
            "raw_source_tokens_estimate": raw_tokens,
            "smavg_brief_tokens_estimate": brief_tokens,
            "tokens_saved_when_agent_uses_smavg_brief_instead_of_raw_source": token_saved,
            "token_reduction_ratio": _ratio(raw_tokens, brief_tokens),
            "assessment": context_report.get("assessment", {}),
            "families_detected": context_report.get("families_detected", 0),
            "family_coverage_percent": context_report.get("family_coverage_percent", 0.0),
            "truth": (
                "Deleting quarantine does not itself save model tokens. Token savings "
                "come from using the Smavg brief/gate and exact archive restore instead "
                "of sending the raw source files to an agent."
            ),
        },
        "importance_brief": _importance_brief(source, context_report, entries),
    }


def _importance_brief(
    source: Path,
    context_report: Dict[str, object],
    entries: List[TreeEntry],
) -> Dict[str, object]:
    file_entries = [entry for entry in entries if entry.kind == "file"]
    paths = [entry.path for entry in file_entries]
    lowered = [path.lower() for path in paths]
    extensions = Counter(Path(path).suffix.lower() or "[no extension]" for path in paths)

    high_needles = (
        "current_focus",
        "session_handoff",
        "runbook",
        "agents.md",
        "skill.md",
        "readme",
        "format.md",
        "pyproject",
        "src/",
        "tests/",
    )
    medium_needles = (
        "benchmark",
        "report",
        "gauntlet",
        "preflight",
        "receipt",
        "scan",
        "context",
        "results",
    )
    low_needles = (
        "__pycache__",
        ".pytest_cache",
        ".cache",
        "tmp/",
        "temp/",
        ".pyc",
        ".log",
        "node_modules",
    )
    high_paths = [path for path in paths if any(needle in path.lower() for needle in high_needles)]
    medium_paths = [path for path in paths if any(needle in path.lower() for needle in medium_needles)]
    low_paths = [path for path in paths if any(needle in path.lower() for needle in low_needles)]
    code_paths = [
        path
        for path in paths
        if Path(path).suffix.lower() in {".py", ".rs", ".js", ".ts", ".tsx", ".go", ".java", ".c", ".cpp", ".h"}
    ]
    raw_tokens = int(context_report.get("original_tokens_estimate", 0))
    family_coverage = float(context_report.get("family_coverage_percent", 0.0))

    if high_paths or code_paths:
        rating = "high"
        purge_risk = "high"
        summary = "Project, source, skill, runbook, or durable memory signals were found."
    elif medium_paths:
        rating = "medium"
        purge_risk = "medium"
        summary = "Benchmark, report, receipt, or workflow evidence signals were found."
    elif low_paths and len(low_paths) >= max(1, len(paths) // 2):
        rating = "low"
        purge_risk = "low"
        summary = "Mostly cache, temporary, or log-like paths were found."
    elif raw_tokens > 1000 or family_coverage >= 10.0:
        rating = "medium"
        purge_risk = "medium"
        summary = "Text content or repeated structure was found, but no critical project markers dominated."
    else:
        rating = "unknown"
        purge_risk = "unknown"
        summary = "Not enough semantic signals were found to rate importance confidently."

    return {
        "rating": rating,
        "purge_risk": purge_risk,
        "summary": summary,
        "file_count": len(file_entries),
        "raw_tokens_estimate": raw_tokens,
        "family_coverage_percent": family_coverage,
        "top_extensions": [
            {"extension": extension, "count": count}
            for extension, count in extensions.most_common(8)
        ],
        "signals": {
            "high_importance_paths": high_paths[:12],
            "code_paths": code_paths[:12],
            "evidence_or_report_paths": medium_paths[:12],
            "cache_temp_or_log_paths": low_paths[:12],
        },
        "truth": (
            "This rating is an advisory briefing generated from local deterministic "
            "signals. It is not deletion permission and it is not a substitute for "
            "a verified archive restore."
        ),
    }


def render_safe_pack_markdown(report: Dict[str, object]) -> str:
    archive_report = report.get("archive_report", {})
    compare = report.get("restore_compare", {})
    cleanup = report.get("cleanup_projection", {})
    quarantine = cleanup.get("quarantine", {})
    purge = cleanup.get("purge_projection", {})
    tokens = cleanup.get("token_projection", {})
    importance = report.get("importance_brief", {})
    ratio = archive_report.get("ratio")
    ratio_text = "n/a" if ratio is None else f"{ratio}x"
    lines = [
        f"# Smavg Safe Pack: {report.get('source')}",
        "",
        "Safe-pack is the trust path before any cleanup: pack, verify, restore, compare, then optionally quarantine.",
        "",
        "## Result",
        "",
        f"- Archive: `{report.get('archive')}`",
        f"- Files: {archive_report.get('file_count', 0)}",
        f"- Logical bytes: {archive_report.get('logical_bytes', 0)}",
        f"- Archive bytes: {archive_report.get('archive_bytes', 0)}",
        f"- Storage ratio: {ratio_text}",
        f"- Archive verify: `{report.get('archive_verify', {}).get('pass', False)}`",
        f"- Restore compare: `{compare.get('pass', False)}`",
        f"- Source moved to quarantine: `{report.get('source_moved_to_quarantine', False)}`",
        f"- Quarantined path: `{report.get('quarantined_path')}`",
        f"- Delete performed: `{report.get('delete_performed', False)}`",
        f"- Disk freed now: {quarantine.get('disk_bytes_freed_now', 0)}",
        "- Disk freed if quarantine is purged: "
        f"{purge.get('additional_disk_bytes_freed_if_quarantine_purged_from_current_state', 0)}",
        "- Net disk saved after purge while keeping archive: "
        f"{purge.get('net_disk_bytes_saved_after_purge_and_archive_kept', 0)}",
        "- Raw source tokens estimate: "
        f"{tokens.get('raw_source_tokens_estimate', 0)}",
        "- Smavg brief tokens estimate: "
        f"{tokens.get('smavg_brief_tokens_estimate', 0)}",
        "- Token reduction if agent uses Smavg brief: "
        f"{_format_ratio(tokens.get('token_reduction_ratio'))}",
        f"- Importance rating: `{importance.get('rating', 'unknown')}`",
        f"- Purge risk: `{importance.get('purge_risk', 'unknown')}`",
        "",
        "## Cleanup Projection",
        "",
        str(quarantine.get("truth", "")),
        "",
        str(purge.get("truth", "")),
        "",
        str(tokens.get("truth", "")),
        "",
        "## Importance Brief",
        "",
        f"- Rating: `{importance.get('rating', 'unknown')}`",
        f"- Purge risk: `{importance.get('purge_risk', 'unknown')}`",
        f"- Summary: {importance.get('summary', '')}",
        "",
        "## Restore Compare Scope",
        "",
    ]
    scope = compare.get("metadata_scope", {})
    for key in sorted(scope):
        lines.append(f"- {key}: `{scope[key]}`")
    failures = compare.get("failures", [])
    lines.extend(["", "## Failures", ""])
    if failures:
        for item in failures:
            lines.append(f"- {item}")
    else:
        lines.append("No failures.")
    lines.extend(["", "## Trust Rule", "", str(report.get("trust_rule", "")), ""])
    return "\n".join(lines)


def write_safe_pack_report(report: Dict[str, object], json_path: Path, markdown_path: Optional[Path] = None) -> None:
    _write_text_atomic(Path(json_path), json.dumps(report, indent=2, sort_keys=True) + "\n")
    _write_text_atomic(Path(markdown_path or Path(json_path).with_suffix(".md")), render_safe_pack_markdown(report))


def _collect_tree(root: Path) -> List[TreeEntry]:
    entries: List[TreeEntry] = []

    def walk(path: Path) -> None:
        with os.scandir(path) as iterator:
            children = sorted(list(iterator), key=lambda item: item.name)
        for child in children:
            child_path = path / child.name
            relative = child_path.relative_to(root).as_posix()
            st = child.stat(follow_symlinks=False)
            mode = stat.S_IMODE(st.st_mode)
            if stat.S_ISLNK(st.st_mode):
                entries.append(TreeEntry("symlink", relative, mode=mode, target=os.readlink(child_path)))
            elif stat.S_ISDIR(st.st_mode):
                entries.append(TreeEntry("dir", relative, mode=mode))
                walk(child_path)
            elif stat.S_ISREG(st.st_mode):
                entries.append(
                    TreeEntry(
                        "file",
                        relative,
                        size=st.st_size,
                        sha256=_hash_file(child_path),
                        mode=mode,
                    )
                )
            else:
                raise SafePackError(f"Unsupported filesystem entry: {relative}")

    walk(root)
    return entries


def _hash_file(path: Path) -> str:
    hasher = __import__("hashlib").sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _unique_quarantine_path(quarantine_dir: Path, source_name: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = quarantine_dir / f"{source_name}-{stamp}"
    candidate = base
    index = 1
    while candidate.exists():
        index += 1
        candidate = quarantine_dir / f"{source_name}-{stamp}-{index}"
    return candidate


def _ratio(before: int, after: int) -> Optional[float]:
    return round(before / after, 3) if before and after else None


def _format_ratio(value: object) -> str:
    return "n/a" if value is None else f"{value}x"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
