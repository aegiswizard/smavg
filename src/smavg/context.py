"""Deterministic AI-context compression for repeated local folders."""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Optional, Tuple

from .delta import sha256_bytes
from .utils import natural_key


class ContextError(RuntimeError):
    """Raised when a Smavg context report cannot be built or expanded."""


@dataclass(frozen=True)
class ContextFile:
    path: Path
    relative: str
    suffix: str
    parent: str
    size: int
    sha256: str
    is_text: bool
    estimated_tokens: int
    line_count: int
    headings: Tuple[str, ...]
    modified_at: str
    source_path: Optional[str] = None


_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_DATE_RE = re.compile(r"\b\d{4}[-/]\d{2}[-/]\d{2}\b")
_HASH_RE = re.compile(r"\b[0-9a-fA-F]{7,64}\b")
_PATH_RE = re.compile(r"(?:^|\s)(?:/[\w./@+-]+|[\w.@+-]+/[\w./@+-]+)")
_COMMAND_RE = re.compile(r"^\s*(?:PYTHONPATH=|python3\b|smavg\b|git\b|rg\b|cd\b|/usr/bin/time\b)")
_IMPORTANT_PATH_HINTS = [
    ("x-browser-automation", "X BrowserMCP skill"),
    ("x_browser_automation_workflow", "X BrowserMCP workflow"),
    ("reddit-browsermcp", "Reddit BrowserMCP skill"),
    ("reddit_browsermcp_workflow", "Reddit BrowserMCP workflow"),
    ("linkedin-browsermcp", "LinkedIn BrowserMCP skill"),
    ("linkedin_browsermcp_workflow", "LinkedIn BrowserMCP workflow"),
    ("producthunt-browsermcp", "Product Hunt BrowserMCP skill"),
    ("producthunt_browsermcp_workflow", "Product Hunt BrowserMCP workflow"),
    ("hackernews-browsermcp", "Hacker News BrowserMCP skill"),
    ("hackernews_browsermcp_workflow", "Hacker News BrowserMCP workflow"),
    ("threads-browsermcp", "Threads BrowserMCP skill"),
    ("threads_browsermcp_workflow", "Threads BrowserMCP workflow"),
    ("skill.md", "skill instructions"),
    ("current_focus", "current focus"),
    ("session_handoff", "session handoff"),
    ("smavg_runbook", "Smavg runbook"),
    ("runbook", "runbook"),
    ("readme", "README"),
    ("format", "format specification"),
    ("agents.md", "agent instructions"),
    ("benchmark", "benchmark evidence"),
    ("history-pack-v4", "latest history-pack evidence"),
    ("context-v1", "context evidence"),
    ("index", "index"),
    ("pyproject", "project metadata"),
]


def build_context_report(
    source_dir: Path,
    max_family_samples: int = 8,
    budget_tokens: Optional[int] = None,
) -> Dict[str, object]:
    source_dir = Path(source_dir).resolve()
    if not source_dir.is_dir():
        raise ContextError(f"Not a directory: {source_dir}")

    files, skipped = _scan_context_files(source_dir)
    return _build_context_report_from_files(
        source_label=str(source_dir),
        files=files,
        skipped=skipped,
        max_family_samples=max_family_samples,
        budget_tokens=budget_tokens,
        source_kind="directory",
        source_roots=[{"path": str(source_dir), "kind": "directory"}],
        rebuild_command=f"smavg context {source_dir}",
    )


def build_context_report_from_file_map(
    file_map: Dict[str, Path],
    source_label: str,
    max_family_samples: int = 8,
    budget_tokens: Optional[int] = None,
    source_kind: str = "path_set",
    rebuild_command: Optional[str] = None,
) -> Dict[str, object]:
    """Build a context report from named files spread across different roots."""
    if not file_map:
        raise ContextError("Context file map cannot be empty")
    files: List[ContextFile] = []
    skipped: List[Dict[str, str]] = []
    seen = set()
    source_roots = []
    for relative, path in sorted(file_map.items(), key=lambda item: natural_key(item[0])):
        relative = _validate_relative_path(relative)
        if relative in seen:
            raise ContextError(f"Duplicate context path: {relative}")
        seen.add(relative)
        resolved = Path(path).expanduser().resolve()
        if resolved.is_symlink():
            skipped.append({"path": relative, "reason": "symlink", "source_path": str(resolved)})
            continue
        if not resolved.is_file():
            skipped.append({"path": relative, "reason": "missing", "source_path": str(resolved)})
            continue
        files.append(_context_file_from_path(resolved, relative, source_path=str(resolved)))
        source_roots.append({"path": str(resolved), "kind": "file"})
    if not files:
        raise ContextError("No regular files were found for context")

    report = _build_context_report_from_files(
        source_label=source_label,
        files=files,
        skipped=skipped,
        max_family_samples=max_family_samples,
        budget_tokens=budget_tokens,
        source_kind=source_kind,
        source_roots=source_roots,
        rebuild_command=rebuild_command or f"smavg context {source_label}",
    )
    report["missing_source_count"] = sum(1 for item in skipped if item.get("reason") == "missing")
    return report


def _build_context_report_from_files(
    source_label: str,
    files: List[ContextFile],
    skipped: List[object],
    max_family_samples: int,
    budget_tokens: Optional[int],
    source_kind: str,
    source_roots: List[Dict[str, str]],
    rebuild_command: str,
) -> Dict[str, object]:
    root = _root_hash(files)
    families = _detect_families(files, max_family_samples=max_family_samples)
    family_paths = {
        path
        for family in families
        for path in family.get("paths", [])
        if isinstance(path, str)
    }
    ungrouped = [item for item in files if item.relative not in family_paths]
    original_tokens = sum(item.estimated_tokens for item in files if item.is_text)
    family_coverage_tokens = sum(item.estimated_tokens for item in files if item.relative in family_paths)
    skipped_records = _skipped_records(skipped)

    recommended = _recommended_files(files)
    compact_index = _compact_file_index(files, recommended)

    report: Dict[str, object] = {
        "format": "smavg-context",
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_path": source_label,
        "source_kind": source_kind,
        "source_roots": source_roots,
        "file_count": len(files),
        "text_file_count": sum(1 for item in files if item.is_text),
        "binary_file_count": sum(1 for item in files if not item.is_text),
        "skipped_symlink_count": sum(1 for item in skipped_records if item.get("reason") == "symlink"),
        "missing_source_count": sum(1 for item in skipped_records if item.get("reason") == "missing"),
        "logical_bytes": sum(item.size for item in files),
        "original_tokens_estimate": original_tokens,
        "brief_tokens_estimate": 0,
        "token_reduction_ratio": None,
        "brief_budget_tokens": budget_tokens,
        "source_root_sha256": root,
        "families_detected": len(families),
        "family_coverage_tokens": family_coverage_tokens,
        "family_coverage_percent": (
            round((family_coverage_tokens / original_tokens) * 100, 2) if original_tokens else 0.0
        ),
        "families": families,
        "ungrouped_files": {
            "count": len(ungrouped),
            "tokens_estimate": sum(item.estimated_tokens for item in ungrouped if item.is_text),
            "sample_paths": [item.relative for item in sorted(ungrouped, key=lambda f: natural_key(f.relative))[:max_family_samples]],
        },
        "largest_files": [
            _file_summary(item)
            for item in sorted(files, key=lambda f: (f.estimated_tokens, f.size), reverse=True)[:20]
        ],
        "recommended_expansions": recommended,
        "compact_file_index": compact_index,
        "files": [_file_summary(item) for item in sorted(files, key=lambda f: natural_key(f.relative))],
        "skipped": skipped_records,
        "integrity": {
            "hash_algorithm": "sha256",
            "all_regular_files_hashed": True,
            "exact_retrieval_available": True,
            "retrieval_requires_source_path": True,
            "ai_generated_interpretations": False,
        },
        "commands": {
            "rebuild_context": rebuild_command,
            "expand_template": "smavg expand-context CONTEXT_JSON RELATIVE_PATH --out OUTPUT_FILE",
        },
    }
    _refresh_brief_token_estimate(report)
    return report


def render_context_markdown(report: Dict[str, object]) -> str:
    source = report["source_path"]
    limits = _render_limits(report)
    assessment = report.get("assessment", {})
    lines = [
        f"# Smavg Context: {source}",
        "",
        "This is a deterministic repetition map. It does not generate or rewrite file contents.",
        "Exact files remain available through the recorded source path and SHA-256 checks.",
        "",
        "## Summary",
        "",
        f"- Source kind: `{report.get('source_kind', 'directory')}`",
        f"- Files scanned: {report['file_count']}",
        f"- Text files: {report['text_file_count']}",
        f"- Binary files: {report['binary_file_count']}",
        f"- Skipped symlinks: {report['skipped_symlink_count']}",
        f"- Missing source inputs: {report.get('missing_source_count', 0)}",
        f"- Logical bytes: {report['logical_bytes']}",
        f"- Estimated original text tokens: {report['original_tokens_estimate']}",
        f"- Estimated brief tokens: {report['brief_tokens_estimate']}",
        f"- Estimated token reduction: {_format_ratio(report.get('token_reduction_ratio'))}",
        f"- Families detected: {report['families_detected']}",
        f"- Family token coverage: {report['family_coverage_percent']}%",
        f"- Source root SHA-256: `{report['source_root_sha256']}`",
        "",
        "## Usefulness Assessment",
        "",
        f"- Status: `{assessment.get('status', 'unknown')}`",
        f"- Finding: {assessment.get('finding', 'not evaluated')}",
        f"- Recommendation: {assessment.get('recommendation', 'not evaluated')}",
        "",
        "## Trust Boundary",
        "",
        "- Smavg reports structure, repetition, paths, sizes, and hashes.",
        "- Smavg does not ask an AI model to regenerate exact bytes.",
        "- Use exact retrieval when file contents, citations, or line-level facts matter.",
        "",
        "## Exact Retrieval",
        "",
        "```bash",
        "smavg expand-context context.json path/in/folder.ext --out restored-file.ext",
        "```",
        "",
        "The command verifies the current source file against the SHA-256 stored in the context JSON before writing output.",
        "",
        "## Recommended Exact Files To Expand",
        "",
    ]

    recommendations = report.get("recommended_expansions", [])
    if recommendations:
        for item in recommendations[: limits["recommendations"]]:
            reasons = ", ".join(item.get("reasons", [])) or "large/high-signal file"
            lines.append(
                f"- `{item['path']}`: {item['estimated_tokens']} estimated tokens, "
                f"reason: {reasons}, sha256 `{item['sha256']}`"
            )
            headings = item.get("headings", [])
            if headings:
                lines.append("  - Headings: " + ", ".join(f"`{heading}`" for heading in headings[:3]))
    else:
        lines.append("No recommended exact files were identified.")
    lines.extend(["", "## Compact Exact File Index", ""])
    lines.append("Path names only. Use exact retrieval before relying on file contents.")
    lines.append("")
    compact_index = report.get("compact_file_index", [])
    if compact_index:
        for item in compact_index[: limits["file_index"]]:
            reasons = ", ".join(item.get("reasons", [])) or "indexed path"
            lines.append(
                f"- `{item['path']}`: {item['estimated_tokens']} estimated tokens, "
                f"reason: {reasons}"
            )
        remaining = max(0, len(compact_index) - limits["file_index"])
        if remaining:
            lines.append(f"- ... {remaining} more indexed paths in `context.json`")
    else:
        lines.append("No high-signal file-index paths were identified.")
    lines.extend(["", "## Families", ""])

    families = report.get("families", [])
    if not families:
        lines.extend(["No repeated families were detected.", ""])
    for index, family in enumerate(families[: limits["families"]], start=1):
        lines.extend(_render_family(index, family, limits))

    ungrouped = report.get("ungrouped_files", {})
    lines.extend(
        [
            "## Ungrouped Files",
            "",
            f"- Count: {ungrouped.get('count', 0)}",
            f"- Estimated text tokens: {ungrouped.get('tokens_estimate', 0)}",
        ]
    )
    samples = ungrouped.get("sample_paths", [])
    if samples:
        lines.append("- Sample paths:")
        for path in samples[: limits["samples"]]:
            lines.append(f"  - `{path}`")
    lines.append("")

    lines.extend(["## Largest Exact Files", ""])
    for item in report.get("largest_files", [])[: limits["largest_files"]]:
        lines.append(
            f"- `{item['path']}`: {item['estimated_tokens']} estimated tokens, "
            f"{item['size']} bytes, sha256 `{item['sha256']}`"
        )
        headings = item.get("headings", [])
        if headings:
            lines.append("  - Headings: " + ", ".join(f"`{heading}`" for heading in headings[:3]))
    lines.append("")
    return "\n".join(lines)


def write_context_outputs(report: Dict[str, object], markdown_path: Optional[Path], json_path: Optional[Path]) -> None:
    _refresh_brief_token_estimate(report)
    markdown = render_context_markdown(report)
    if markdown_path is not None:
        _write_text_atomic(Path(markdown_path), markdown)
    if json_path is not None:
        _write_text_atomic(
            Path(json_path),
            json.dumps(report, indent=2, sort_keys=True) + "\n",
        )


def _refresh_brief_token_estimate(report: Dict[str, object]) -> None:
    original_tokens = int(report.get("original_tokens_estimate", 0))
    previous = None
    for _ in range(5):
        markdown = render_context_markdown(report)
        current = estimate_tokens(markdown)
        report["brief_tokens_estimate"] = current
        report["token_reduction_ratio"] = (
            round(original_tokens / current, 3) if original_tokens and current else None
        )
        report["assessment"] = _context_assessment(report)
        if current == previous:
            break
        previous = current


def _context_assessment(report: Dict[str, object]) -> Dict[str, object]:
    original_tokens = int(report.get("original_tokens_estimate", 0))
    ratio = float(report.get("token_reduction_ratio") or 0.0)
    family_count = int(report.get("families_detected", 0))
    coverage = float(report.get("family_coverage_percent", 0.0))
    budget = report.get("brief_budget_tokens")
    brief_tokens = int(report.get("brief_tokens_estimate", 0))

    if original_tokens == 0:
        status = "no_text"
        finding = "No text tokens were found. This context is only an exact file/hash index."
        recommendation = "Use exact retrieval for files of interest; token compression is not meaningful here."
    elif family_count == 0 or coverage < 10.0:
        status = "weak"
        finding = "No strong repetition found. The brief is useful as an index, but it is not a strong repetition map."
        recommendation = "Read files directly or select a narrower/more repetitive folder before relying on the brief."
    elif ratio < 2.0:
        status = "weak"
        finding = "Only minor context reduction was measured."
        recommendation = "Read directly or use Smavg only as a hash-verified file index."
    elif ratio < 10.0:
        status = "useful"
        finding = "Some repeated structure was found, with moderate context reduction."
        recommendation = "Use the brief first, then expand recommended exact files for detailed answers."
    elif ratio < 50.0:
        status = "strong"
        finding = "Strong repeated structure was found."
        recommendation = "Give the brief to the agent first and expand exact files only when needed."
    else:
        status = "excellent"
        finding = "Very strong repeated structure was found."
        recommendation = "Use Smavg as a first-pass context firewall before reading raw files."

    if isinstance(budget, int) and budget > 0 and brief_tokens > budget:
        recommendation += f" Brief is above the requested {budget}-token budget; use a higher budget or narrower folder."

    return {
        "status": status,
        "finding": finding,
        "recommendation": recommendation,
        "family_token_coverage_percent": coverage,
    }


def expand_context_file(context_json: Path, relative_path: str, output: Path) -> int:
    try:
        report = json.loads(Path(context_json).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextError(f"Could not read context JSON: {context_json}") from exc
    if report.get("format") != "smavg-context" or report.get("version") != 1:
        raise ContextError("Unsupported context JSON")
    relative = _validate_relative_path(relative_path)
    file_index = {
        str(item["path"]): item
        for item in report.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    record = file_index.get(relative)
    if record is None:
        raise ContextError(f"Path not found in context: {relative}")
    target = _resolve_context_target(report, record, relative)
    try:
        data = target.read_bytes()
    except OSError as exc:
        raise ContextError(f"Could not read source file: {target}") from exc
    expected_size = int(record.get("size", -1))
    expected_sha = str(record.get("sha256", ""))
    if len(data) != expected_size:
        raise ContextError(f"Source size changed for {relative}")
    if sha256_bytes(data) != expected_sha:
        raise ContextError(f"Source SHA-256 changed for {relative}")
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    try:
        temp.write_bytes(data)
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    return len(data)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(_TOKEN_RE.findall(text)))


def _format_ratio(value: object) -> str:
    return "n/a" if value is None else f"{value}x"


def _scan_context_files(source_dir: Path) -> Tuple[List[ContextFile], List[str]]:
    files: List[ContextFile] = []
    skipped: List[str] = []
    for path in sorted(source_dir.rglob("*")):
        if path.is_symlink():
            skipped.append(path.relative_to(source_dir).as_posix())
            continue
        if not path.is_file():
            continue
        files.append(_context_file_from_path(path, path.relative_to(source_dir).as_posix()))
    return files, skipped


def _context_file_from_path(path: Path, relative: str, source_path: Optional[str] = None) -> ContextFile:
    data = path.read_bytes()
    stat = path.stat()
    is_text, text = _decode_text(data)
    headings = tuple(_extract_headings(text)) if is_text else ()
    normalized = _validate_relative_path(relative)
    parent = PurePosixPath(normalized).parent.as_posix()
    return ContextFile(
        path=path,
        relative=normalized,
        suffix=PurePosixPath(normalized).suffix.lower(),
        parent=parent,
        size=len(data),
        sha256=sha256_bytes(data),
        is_text=is_text,
        estimated_tokens=estimate_tokens(text) if is_text else 0,
        line_count=text.count("\n") + (1 if text else 0) if is_text else 0,
        headings=headings,
        modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        source_path=source_path,
    )


def _skipped_records(skipped: List[object]) -> List[Dict[str, str]]:
    records = []
    for item in skipped:
        if isinstance(item, dict):
            records.append({str(key): str(value) for key, value in item.items()})
        else:
            records.append({"path": str(item), "reason": "symlink"})
    return records


def _resolve_context_target(report: Dict[str, object], record: Dict[str, object], relative: str) -> Path:
    if report.get("source_kind") in {"path_set", "workflow"} or "source_path" in record:
        source_path = record.get("source_path")
        if not isinstance(source_path, str) or not source_path:
            raise ContextError(f"Context record does not include source_path for {relative}")
        target = Path(source_path).expanduser().resolve()
        if not _is_allowed_context_source(target, report.get("source_roots", [])):
            raise ContextError(f"Unsafe context source path for {relative}")
        return target

    source = Path(str(report.get("source_path", ""))).resolve()
    target = (source / relative).resolve()
    if not _is_relative_to(target, source):
        raise ContextError(f"Unsafe context path: {relative}")
    return target


def _is_allowed_context_source(target: Path, source_roots: object) -> bool:
    if not isinstance(source_roots, list):
        return False
    for entry in source_roots:
        if not isinstance(entry, dict):
            continue
        root_value = entry.get("path")
        if not isinstance(root_value, str) or not root_value:
            continue
        root = Path(root_value).expanduser().resolve()
        kind = entry.get("kind")
        if kind == "file" and target == root:
            return True
        if kind == "directory" and _is_relative_to(target, root):
            return True
    return False


def _detect_families(files: List[ContextFile], max_family_samples: int) -> List[Dict[str, object]]:
    families: List[Dict[str, object]] = []
    used_labels = set()

    for key, members in _markdown_heading_groups(files).items():
        if len(members) < 2:
            continue
        families.append(_build_family("markdown_heading_template", key, members, max_family_samples))
        used_labels.add(("markdown_heading_template", key))

    for key, members in _parent_suffix_groups(files).items():
        if len(members) < 4:
            continue
        label = f"{key[0]}/*{key[1] or '[no extension]'}"
        if any(set(item.relative for item in members) <= set(family.get("paths", [])) for family in families):
            continue
        family = _build_family("parent_suffix_cluster", label, members, max_family_samples)
        if _is_useful_family(family):
            families.append(family)
            used_labels.add(("parent_suffix_cluster", label))

    md_members = [item for item in files if item.suffix == ".md" and item.is_text]
    covered_md = {
        path
        for family in families
        for path in family.get("paths", [])
        if isinstance(path, str)
    }
    uncovered_md = [item for item in md_members if item.relative not in covered_md]
    if len(md_members) >= 4 and len(uncovered_md) >= max(4, len(md_members) // 2):
        label = "all-markdown-files"
        if ("parent_suffix_cluster", label) not in used_labels:
            family = _build_family("markdown_corpus", label, md_members, max_family_samples)
            if _is_useful_family(family):
                families.append(family)

    families.sort(
        key=lambda item: (
            int(item.get("estimated_tokens", 0)),
            int(item.get("files", 0)),
        ),
        reverse=True,
    )
    return families


def _is_useful_family(family: Dict[str, object]) -> bool:
    if family.get("kind") == "markdown_heading_template":
        return True
    if float(family.get("stable_line_ratio", 0.0)) >= 0.02:
        return True
    if len(family.get("common_headings", [])) >= 2:
        return True
    if len(family.get("top_repeated_lines", [])) >= 2:
        return True
    return False


def _markdown_heading_groups(files: List[ContextFile]) -> Dict[str, List[ContextFile]]:
    groups: Dict[str, List[ContextFile]] = defaultdict(list)
    for item in files:
        if not item.is_text or item.suffix not in {".md", ".markdown"}:
            continue
        signature = _heading_signature(item.headings)
        if signature:
            groups[signature].append(item)
    return groups


def _parent_suffix_groups(files: List[ContextFile]) -> Dict[Tuple[str, str], List[ContextFile]]:
    groups: Dict[Tuple[str, str], List[ContextFile]] = defaultdict(list)
    for item in files:
        if not item.is_text:
            continue
        groups[(item.parent, item.suffix)].append(item)
    return groups


def _build_family(kind: str, label: str, members: List[ContextFile], max_family_samples: int) -> Dict[str, object]:
    members = sorted(members, key=lambda item: natural_key(item.relative))
    texts = [_safe_read_text(item.path) for item in members if item.is_text]
    line_counter = Counter()
    file_line_sets = []
    for text in texts:
        lines = [line.rstrip("\n") for line in text.splitlines() if line.strip()]
        unique_lines = set(lines)
        file_line_sets.append(unique_lines)
        line_counter.update(unique_lines)
    repeated_lines = [
        (line, count)
        for line, count in line_counter.most_common(12)
        if count >= max(2, min(len(members), max(2, len(members) // 2)))
    ]
    heading_counter = Counter()
    for item in members:
        heading_counter.update(set(item.headings))
    variable_markers = _variable_markers(texts)
    logical_bytes = sum(item.size for item in members)
    estimated_tokens = sum(item.estimated_tokens for item in members if item.is_text)
    stable_line_hits = sum(count for _line, count in repeated_lines)
    total_line_slots = sum(len(lines) for lines in file_line_sets)
    stable_line_ratio = round(stable_line_hits / total_line_slots, 3) if total_line_slots else 0.0
    return {
        "id": _family_id(kind, label),
        "kind": kind,
        "label": label,
        "display_label": _display_family_label(kind, label),
        "files": len(members),
        "logical_bytes": logical_bytes,
        "estimated_tokens": estimated_tokens,
        "sha256_root": _root_hash(members),
        "stable_line_ratio": stable_line_ratio,
        "common_headings": [
            {"heading": heading, "files": count}
            for heading, count in heading_counter.most_common(12)
            if count >= 2
        ],
        "top_repeated_lines": [
            {"line": _truncate(line, 140), "files": count}
            for line, count in repeated_lines
        ],
        "variable_markers": variable_markers,
        "paths": [item.relative for item in members],
        "sample_paths": [item.relative for item in members[:max_family_samples]],
        "largest_files": [_file_summary(item) for item in sorted(members, key=lambda f: f.estimated_tokens, reverse=True)[:5]],
    }


def _display_family_label(kind: str, label: str) -> str:
    if kind == "markdown_corpus":
        return "All Markdown files with shared structure"
    if kind == "markdown_heading_template":
        parts = label.split("|")
        headings = [part.split(":", 1)[-1] for part in parts[:3]]
        return "Markdown files sharing headings: " + ", ".join(headings)
    if kind == "parent_suffix_cluster":
        parent, _separator, suffix = label.rpartition("/*")
        suffix_name = {
            ".csv": "CSV",
            ".json": "JSON",
            ".md": "Markdown",
            ".py": "Python",
            ".txt": "text",
        }.get(suffix, suffix or "text")
        where = "root" if parent == "." else parent
        return f"{suffix_name} files in {where}"
    return label


def _render_family(index: int, family: Dict[str, object], limits: Dict[str, int]) -> List[str]:
    lines = [
        f"### Family {index}: {family.get('display_label', family['label'])}",
        "",
        f"- Kind: `{family['kind']}`",
        f"- Raw label: `{family['label']}`",
        f"- Files: {family['files']}",
        f"- Logical bytes: {family['logical_bytes']}",
        f"- Estimated original tokens: {family['estimated_tokens']}",
        f"- Stable repeated-line ratio: {family['stable_line_ratio']}",
        f"- SHA-256 root: `{family['sha256_root']}`",
    ]
    markers = family.get("variable_markers", {})
    if markers:
        lines.append(
            "- Variable markers: "
            + ", ".join(f"{name}={value}" for name, value in markers.items())
        )
    headings = family.get("common_headings", [])
    if headings:
        lines.append("- Common headings:")
        for item in headings[: limits["headings"]]:
            lines.append(f"  - `{item['heading']}` in {item['files']} files")
    repeated = family.get("top_repeated_lines", [])
    if repeated:
        lines.append("- Repeated literal lines:")
        for item in repeated[: limits["repeated_lines"]]:
            lines.append(f"  - `{item['line']}` in {item['files']} files")
    samples = family.get("sample_paths", [])
    if samples:
        lines.append("- Sample exact paths:")
        for path in samples[: limits["samples"]]:
            lines.append(f"  - `{path}`")
    lines.append("")
    return lines


def _extract_headings(text: str) -> List[str]:
    headings = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            level = len(match.group(1))
            title = _normalize_heading(match.group(2))
            if title:
                headings.append(f"h{level}:{title}")
    return headings


def _heading_signature(headings: Tuple[str, ...]) -> str:
    if len(headings) < 2:
        return ""
    selected = list(headings)
    if selected and selected[0].startswith("h1:"):
        selected = selected[1:]
    selected = selected[:24]
    if len(selected) < 2:
        return ""
    return "|".join(selected)


def _normalize_heading(value: str) -> str:
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = _DATE_RE.sub("DATE", value)
    value = _HASH_RE.sub("HASH", value)
    value = re.sub(r"\s+", " ", value.strip().lower())
    return value[:120]


def _variable_markers(texts: Iterable[str]) -> Dict[str, int]:
    dates = hashes = paths = commands = 0
    for text in texts:
        dates += len(_DATE_RE.findall(text))
        hashes += len(_HASH_RE.findall(text))
        paths += len(_PATH_RE.findall(text))
        commands += sum(1 for line in text.splitlines() if _COMMAND_RE.match(line))
    return {
        "dates": dates,
        "hashes": hashes,
        "paths": paths,
        "command_lines": commands,
    }


def _file_summary(item: ContextFile) -> Dict[str, object]:
    summary = {
        "path": item.relative,
        "size": item.size,
        "sha256": item.sha256,
        "is_text": item.is_text,
        "estimated_tokens": item.estimated_tokens,
        "line_count": item.line_count,
        "modified_at": item.modified_at,
        "heading_count": len(item.headings),
        "headings": list(item.headings[:12]),
        "role_hints": _file_role_hints(item.relative),
    }
    if item.source_path is not None:
        summary["source_path"] = item.source_path
    return summary


def _recommended_files(files: List[ContextFile], limit: int = 16) -> List[Dict[str, object]]:
    scored = []
    for item in files:
        if not item.is_text or item.estimated_tokens <= 0:
            continue
        reasons = _file_role_hints(item.relative)
        score = item.estimated_tokens / 100.0
        score += min(item.size / 2000.0, 25.0)
        score += min(len(item.headings), 10)
        score += len(reasons) * 35
        lowered_reasons = " ".join(reasons).lower()
        if "browsermcp workflow" in lowered_reasons:
            score += 100
        if "browsermcp skill" in lowered_reasons:
            score += 85
        if "skill instructions" in lowered_reasons:
            score += 35
        if item.parent in {"short-term", "medium-term", "."}:
            score += 10
        summary = _file_summary(item)
        summary["score"] = round(score, 3)
        summary["reasons"] = reasons or ["large/high-signal text file"]
        summary["expand_command"] = f"smavg expand-context context.json {item.relative} --out exact-file"
        scored.append(summary)
    scored.sort(
        key=lambda entry: (float(entry["score"]), int(entry["estimated_tokens"])),
        reverse=True,
    )
    return scored[:limit]


def _compact_file_index(
    files: List[ContextFile],
    recommended: List[Dict[str, object]],
    limit: int = 260,
) -> List[Dict[str, object]]:
    recommended_paths = {
        str(item.get("path"))
        for item in recommended
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    scored = []
    for item in files:
        if not item.is_text:
            continue
        reasons = []
        score = 0.0
        relative = item.relative
        lowered = relative.lower()
        name = PurePosixPath(relative).name.lower()
        if relative in recommended_paths:
            score += 500
            reasons.append("recommended")
        role_hints = _file_role_hints(relative)
        if role_hints:
            score += 120 * len(role_hints)
            reasons.extend(role_hints)
        if name == "skill.md":
            score += 800
            reasons.append("skill entrypoint")
        if name in {"readme.md", "agents.md", "format.md", "pyproject.toml"}:
            score += 650
            reasons.append("project control file")
        if lowered.startswith("src/smavg/") and lowered.endswith(".py"):
            score += 625
            reasons.append("Smavg source module")
        if lowered.startswith("tests/") and lowered.endswith(".py"):
            score += 500
            reasons.append("Smavg test module")
        if any(part in lowered for part in ("mcp", "preflight", "context", "workflow", "gauntlet")):
            score += 250
            reasons.append("agent workflow surface")
        if item.estimated_tokens >= 1000:
            score += min(item.estimated_tokens / 50.0, 200.0)
            reasons.append("substantial text file")
        if score <= 0:
            continue
        summary = _file_summary(item)
        summary["index_score"] = round(score, 3)
        summary["reasons"] = _dedupe(reasons)
        scored.append(summary)
    scored.sort(
        key=lambda entry: (
            float(entry["index_score"]),
            int(entry["estimated_tokens"]),
            str(entry["path"]),
        ),
        reverse=True,
    )
    return scored[:limit]


def _file_role_hints(relative: str) -> List[str]:
    lowered = relative.lower()
    hints = []
    for needle, label in _IMPORTANT_PATH_HINTS:
        if needle in lowered:
            hints.append(label)
    return hints


def _render_limits(report: Dict[str, object]) -> Dict[str, int]:
    budget = report.get("brief_budget_tokens")
    if not isinstance(budget, int) or budget <= 0:
        return {
            "families": 8,
            "file_index": 180,
            "headings": 8,
            "largest_files": 15,
            "recommendations": 10,
            "repeated_lines": 6,
            "samples": 8,
        }
    if budget <= 1000:
        return {
            "families": 3,
            "file_index": 30,
            "headings": 3,
            "largest_files": 6,
            "recommendations": 4,
            "repeated_lines": 2,
            "samples": 3,
        }
    if budget <= 4000:
        return {
            "families": 5,
            "file_index": 180,
            "headings": 5,
            "largest_files": 10,
            "recommendations": 8,
            "repeated_lines": 4,
            "samples": 5,
        }
    return {
        "families": 10,
        "file_index": 260,
        "headings": 10,
        "largest_files": 20,
        "recommendations": 12,
        "repeated_lines": 8,
        "samples": 10,
    }


def _root_hash(files: Iterable[ContextFile]) -> str:
    hasher = sha256()
    for item in sorted(files, key=lambda file: natural_key(file.relative)):
        path_bytes = item.relative.encode("utf-8")
        hasher.update(len(path_bytes).to_bytes(4, "little"))
        hasher.update(path_bytes)
        hasher.update(item.size.to_bytes(8, "little"))
        hasher.update(bytes.fromhex(item.sha256))
    return hasher.hexdigest()


def _family_id(kind: str, label: str) -> str:
    digest = sha256(f"{kind}:{label}".encode("utf-8")).hexdigest()[:12]
    safe = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:40] or "family"
    return f"{safe}-{digest}"


def _decode_text(data: bytes) -> Tuple[bool, str]:
    if not data:
        return True, ""
    sample = data[:8192]
    if b"\x00" in sample:
        return False, ""
    control = 0
    for byte in sample:
        if byte in {9, 10, 12, 13}:
            continue
        if byte < 32:
            control += 1
    if control / len(sample) >= 0.02:
        return False, ""
    try:
        return True, data.decode("utf-8")
    except UnicodeDecodeError:
        return True, data.decode("latin1")


def _safe_read_text(path: Path) -> str:
    data = path.read_bytes()
    is_text, text = _decode_text(data)
    return text if is_text else ""


def _validate_relative_path(value: str) -> str:
    path = PurePosixPath(value.replace("\\", "/"))
    normalized = path.as_posix()
    if normalized in {"", "."}:
        raise ContextError("Context path cannot be empty")
    if normalized.startswith("/") or normalized == ".." or normalized.startswith("../"):
        raise ContextError(f"Unsafe context path: {value}")
    if "/../" in f"/{normalized}/":
        raise ContextError(f"Unsafe context path: {value}")
    return normalized


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _truncate(value: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


def _dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    output = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
