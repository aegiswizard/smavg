"""Read-only Smavg discovery scans."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .context import ContextError, build_context_report, write_context_outputs
from .workflow_context import available_workflow_profiles, build_workflow_context_report


class ScanError(RuntimeError):
    """Raised when a Smavg discovery scan cannot complete."""


@dataclass(frozen=True)
class QuickDirStats:
    path: Path
    file_count: int
    bytes: int
    truncated: bool
    reason: str = ""


SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".smavg",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    "Library",
    "Applications",
    "System",
    "smavg-private-benchmarks",
    "smavg-preflights",
}


def run_scan(
    *,
    root: Path,
    out_dir: Path,
    run_id: Optional[str] = None,
    recursive: bool = False,
    max_depth: int = 1,
    max_dirs: int = 40,
    min_files: int = 2,
    max_files_per_dir: int = 2000,
    max_bytes_per_dir: int = 100 * 1024 * 1024,
    budget_tokens: Optional[int] = 3000,
    include_workflows: bool = True,
) -> Dict[str, object]:
    """Run a read-only discovery scan and write markdown/JSON artifacts."""
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ScanError(f"Not a directory: {root}")
    if max_dirs <= 0:
        raise ScanError("max_dirs must be positive")

    base = Path(out_dir).expanduser()
    run_dir = base / (run_id or _default_run_id(root.name or "root"))
    run_dir.mkdir(parents=True, exist_ok=False)
    contexts_dir = run_dir / "contexts"
    contexts_dir.mkdir()

    candidates = _candidate_dirs(
        root,
        recursive=recursive,
        max_depth=max_depth,
        max_dirs=max_dirs,
        min_files=min_files,
        max_files_per_dir=max_files_per_dir,
        max_bytes_per_dir=max_bytes_per_dir,
    )
    directory_reports = []
    skipped = []
    for index, stats in enumerate(candidates, start=1):
        if stats.truncated:
            skipped.append(_skipped_record(stats))
            continue
        try:
            report = build_context_report(stats.path, budget_tokens=budget_tokens)
        except ContextError as exc:
            skipped.append(
                {
                    "path": str(stats.path),
                    "files": stats.file_count,
                    "bytes": stats.bytes,
                    "reason": str(exc),
                }
            )
            continue
        slug = f"{index:03d}-{_slug(_relative_label(root, stats.path))}"
        context_md = contexts_dir / f"{slug}.md"
        context_json = contexts_dir / f"{slug}.json"
        write_context_outputs(report, context_md, context_json)
        directory_reports.append(_directory_candidate(root, stats.path, report, context_md, context_json))

    workflow_reports = []
    if include_workflows:
        for profile in available_workflow_profiles():
            name = str(profile["name"])
            try:
                report = build_workflow_context_report(name, budget_tokens=budget_tokens)
            except ContextError as exc:
                workflow_reports.append({"name": name, "status": "error", "reason": str(exc)})
                continue
            slug = f"workflow-{_slug(name)}"
            context_md = contexts_dir / f"{slug}.md"
            context_json = contexts_dir / f"{slug}.json"
            write_context_outputs(report, context_md, context_json)
            workflow_reports.append(_workflow_candidate(name, report, context_md, context_json))

    summary = _summary(
        root=root,
        run_dir=run_dir,
        directory_reports=directory_reports,
        workflow_reports=workflow_reports,
        skipped=skipped,
        recursive=recursive,
        max_depth=max_depth,
    )
    scan_json = run_dir / "scan.json"
    scan_md = run_dir / "scan.md"
    summary["scan_json"] = str(scan_json)
    summary["scan_markdown"] = str(scan_md)
    _write_text_atomic(scan_json, json.dumps(summary, indent=2, sort_keys=True) + "\n")
    _write_text_atomic(scan_md, render_scan_markdown(summary))
    return summary


def render_scan_markdown(summary: Dict[str, object]) -> str:
    lines = [
        f"# Smavg Scan: {summary.get('root')}",
        "",
        "This is a read-only discovery report. It does not archive, move, or delete data.",
        "",
        "## Summary",
        "",
        f"- Directories analyzed: {summary.get('directories_analyzed', 0)}",
        f"- Directory candidates: {summary.get('directory_candidates', 0)}",
        f"- Workflow candidates: {summary.get('workflow_candidates', 0)}",
        f"- Skipped directories: {summary.get('skipped_directories', 0)}",
        f"- Best directory token reduction: {summary.get('best_directory_token_reduction', 'n/a')}",
        f"- Best workflow token reduction: {summary.get('best_workflow_token_reduction', 'n/a')}",
        f"- Cleanup performed: `{summary.get('cleanup_performed', False)}`",
        "",
        "## Directory Candidates",
        "",
    ]
    directories = summary.get("directories", [])
    if directories:
        for item in directories:
            lines.extend(_candidate_lines(item))
    else:
        lines.append("No useful directory candidates were found under the current scan limits.")
        lines.append("")

    lines.extend(["## Workflow Candidates", ""])
    workflows = summary.get("workflows", [])
    if workflows:
        for item in workflows:
            lines.extend(_candidate_lines(item))
    else:
        lines.append("Workflow scanning was disabled or no workflow candidates were available.")
        lines.append("")

    lines.extend(["## Skipped", ""])
    skipped = summary.get("skipped", [])
    if skipped:
        for item in skipped[:50]:
            lines.append(f"- `{item.get('path')}`: {item.get('reason')}")
    else:
        lines.append("No directories were skipped.")
    lines.extend(
        [
            "",
            "## Safety Rule",
            "",
            "Scan is discovery only. Use `smavg safe-pack` to create a verified archive,",
            "restore-compare it, and optionally move the original to quarantine. Do not",
            "delete originals directly from scan results.",
            "",
        ]
    )
    return "\n".join(lines)


def _candidate_lines(item: Dict[str, object]) -> List[str]:
    ratio = item.get("token_reduction_ratio")
    ratio_text = "n/a" if ratio is None else f"{ratio}x"
    assessment = item.get("assessment", {})
    lines = [
        f"### `{item.get('label')}`",
        "",
        f"- Kind: `{item.get('kind')}`",
        f"- Files: {item.get('files', 0)}",
        f"- Logical bytes: {item.get('logical_bytes', 0)}",
        f"- Raw token estimate: {item.get('raw_tokens_estimate', 0)}",
        f"- Brief token estimate: {item.get('brief_tokens_estimate', 0)}",
        f"- Token reduction: {ratio_text}",
        f"- Assessment: `{assessment.get('status', 'unknown')}`",
        f"- Context: `{item.get('context_markdown')}`",
        f"- Context JSON: `{item.get('context_json')}`",
    ]
    commands = item.get("recommended_commands", {})
    for label, command in commands.items():
        lines.append(f"- {label}: `{command}`")
    lines.append("")
    return lines


def _summary(
    *,
    root: Path,
    run_dir: Path,
    directory_reports: List[Dict[str, object]],
    workflow_reports: List[Dict[str, object]],
    skipped: List[Dict[str, object]],
    recursive: bool,
    max_depth: int,
) -> Dict[str, object]:
    useful_dirs = [item for item in directory_reports if _is_candidate(item)]
    useful_workflows = [item for item in workflow_reports if _is_candidate(item)]
    best_dir = _best_ratio(directory_reports)
    best_workflow = _best_ratio(workflow_reports)
    return {
        "format": "smavg-scan-report",
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "run_dir": str(run_dir),
        "recursive": recursive,
        "max_depth": max_depth,
        "directories_analyzed": len(directory_reports),
        "directory_candidates": len(useful_dirs),
        "workflow_candidates": len(useful_workflows),
        "skipped_directories": len(skipped),
        "best_directory_token_reduction": best_dir,
        "best_workflow_token_reduction": best_workflow,
        "cleanup_performed": False,
        "directories": directory_reports,
        "workflows": workflow_reports,
        "skipped": skipped,
        "trust_rule": "Scan is read-only discovery. No archive, move, delete, or cleanup occurs.",
    }


def _candidate_dirs(
    root: Path,
    *,
    recursive: bool,
    max_depth: int,
    max_dirs: int,
    min_files: int,
    max_files_per_dir: int,
    max_bytes_per_dir: int,
) -> List[QuickDirStats]:
    candidates: List[QuickDirStats] = []
    roots = [root]
    if recursive:
        root_depth = len(root.parts)
        for current, dirnames, _files in os.walk(root):
            current_path = Path(current)
            depth = len(current_path.parts) - root_depth
            dirnames[:] = [
                name
                for name in sorted(dirnames)
                if name not in SKIP_DIR_NAMES and not (name.startswith(".") and current_path != root)
            ]
            if depth >= max_depth:
                dirnames[:] = []
            if current_path != root:
                roots.append(current_path)
            if len(roots) >= max_dirs:
                break

    for path in roots[:max_dirs]:
        stats = _quick_stats(
            path,
            max_files=max_files_per_dir,
            max_bytes=max_bytes_per_dir,
        )
        if stats.file_count < min_files and path != root:
            continue
        candidates.append(stats)
    return candidates


def _quick_stats(path: Path, max_files: int, max_bytes: int) -> QuickDirStats:
    file_count = 0
    total = 0
    try:
        for current, dirnames, filenames in os.walk(path):
            current_path = Path(current)
            dirnames[:] = [
                name
                for name in sorted(dirnames)
                if name not in SKIP_DIR_NAMES and not (name.startswith(".") and current_path != path)
            ]
            for name in filenames:
                child = current_path / name
                try:
                    if child.is_symlink() or not child.is_file():
                        continue
                    size = child.stat().st_size
                except OSError:
                    continue
                file_count += 1
                total += size
                if file_count > max_files:
                    return QuickDirStats(path, file_count, total, True, "too many files for read-only scan")
                if total > max_bytes:
                    return QuickDirStats(path, file_count, total, True, "too many bytes for read-only scan")
    except OSError as exc:
        return QuickDirStats(path, file_count, total, True, str(exc))
    return QuickDirStats(path, file_count, total, False)


def _directory_candidate(
    root: Path,
    path: Path,
    report: Dict[str, object],
    context_md: Path,
    context_json: Path,
) -> Dict[str, object]:
    label = _relative_label(root, path)
    return {
        "kind": "directory",
        "label": label,
        "path": str(path),
        "files": report.get("file_count", 0),
        "logical_bytes": report.get("logical_bytes", 0),
        "raw_tokens_estimate": report.get("original_tokens_estimate", 0),
        "brief_tokens_estimate": report.get("brief_tokens_estimate", 0),
        "token_reduction_ratio": report.get("token_reduction_ratio"),
        "families_detected": report.get("families_detected", 0),
        "family_coverage_percent": report.get("family_coverage_percent", 0.0),
        "assessment": report.get("assessment", {}),
        "context_markdown": str(context_md),
        "context_json": str(context_json),
        "recommended_commands": {
            "preflight": f"smavg preflight --source {path} --out-dir ~/.codex/smavg-preflights",
            "safe_pack": f"smavg safe-pack {path} --out {path.name}.smavg --work-dir ~/.codex/smavg-safe-pack",
        },
    }


def _workflow_candidate(name: str, report: Dict[str, object], context_md: Path, context_json: Path) -> Dict[str, object]:
    return {
        "kind": "workflow",
        "label": name,
        "path": f"workflow:{name}",
        "files": report.get("file_count", 0),
        "logical_bytes": report.get("logical_bytes", 0),
        "raw_tokens_estimate": report.get("original_tokens_estimate", 0),
        "brief_tokens_estimate": report.get("brief_tokens_estimate", 0),
        "token_reduction_ratio": report.get("token_reduction_ratio"),
        "families_detected": report.get("families_detected", 0),
        "family_coverage_percent": report.get("family_coverage_percent", 0.0),
        "assessment": report.get("assessment", {}),
        "context_markdown": str(context_md),
        "context_json": str(context_json),
        "recommended_commands": {
            "preflight": f"smavg preflight --workflow {name} --out-dir ~/.codex/smavg-preflights",
        },
    }


def _skipped_record(stats: QuickDirStats) -> Dict[str, object]:
    return {
        "path": str(stats.path),
        "files": stats.file_count,
        "bytes": stats.bytes,
        "reason": stats.reason or "scan limit reached",
    }


def _is_candidate(item: Dict[str, object]) -> bool:
    assessment = item.get("assessment", {})
    if isinstance(assessment, dict) and assessment.get("status") in {"useful", "strong", "excellent"}:
        return True
    ratio = item.get("token_reduction_ratio")
    return isinstance(ratio, (int, float)) and ratio >= 2.0


def _best_ratio(items: Iterable[Dict[str, object]]) -> Optional[float]:
    ratios = [
        float(item["token_reduction_ratio"])
        for item in items
        if isinstance(item.get("token_reduction_ratio"), (int, float))
    ]
    return round(max(ratios), 3) if ratios else None


def _relative_label(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = str(path)
    return "." if relative == "." else relative


def _default_run_id(slug: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{_slug(slug)}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._")
    return slug[:80] or "scan"


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
