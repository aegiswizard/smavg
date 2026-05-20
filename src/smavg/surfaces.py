"""Surface registry and gauntlet for Smavg-enabled agent work.

This module inventories local agent surfaces without claiming they are callable
unless Smavg can verify that locally. It also runs a deterministic gauntlet over
the surfaces that can be represented as exact local files.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .context import (
    ContextError,
    build_context_report,
    build_context_report_from_file_map,
    estimate_tokens,
    expand_context_file,
    render_context_markdown,
    write_context_outputs,
)
from .utils import natural_key
from .workflow_context import available_workflow_profiles, build_workflow_context_report


class SurfaceError(RuntimeError):
    """Raised when Smavg cannot inventory or test local surfaces."""


TRUTH_BOUNDARY = (
    "Surface registry is local inventory plus local exact-file verification. "
    "It separates verified local files, discovered local bundles, configured "
    "but uncalled MCP/app settings, and missing references. It does not prove "
    "account-side app access or current-session tool exposure unless the host "
    "exposes that as a local callable signal."
)


@dataclass(frozen=True)
class ContextGroupSpec:
    id: str
    type: str
    label: str
    source: Optional[Path] = None
    file_map: Optional[Dict[str, Path]] = None
    notes: str = ""


def default_surfaces_dir() -> Path:
    return Path.home() / ".smavg" / "surfaces"


def scan_surfaces(
    *,
    out_dir: Path,
    run_id: Optional[str] = None,
    budget_tokens: int = 3000,
    home: Optional[Path] = None,
    smavg_repo: Optional[Path] = None,
) -> Dict[str, object]:
    """Inventory local Codex/agent surfaces and write a registry report."""
    if budget_tokens <= 0:
        raise SurfaceError("budget_tokens must be positive")
    home = Path(home or Path.home()).expanduser().resolve()
    smavg_repo = Path(smavg_repo or (home / "smavg")).expanduser().resolve()
    run_root = Path(out_dir).expanduser().resolve()
    run_dir = run_root / (run_id or _default_run_id("surfaces"))
    run_dir.mkdir(parents=True, exist_ok=True)

    surfaces = _discover_surface_records(home=home, smavg_repo=smavg_repo)
    config_summaries = _write_config_summaries(home, run_dir / "sanitized-configs")
    context_specs = _context_group_specs(
        home=home,
        smavg_repo=smavg_repo,
        config_summaries=config_summaries,
    )
    context_groups = [
        _build_context_group(spec, run_dir / "contexts", budget_tokens)
        for spec in context_specs
    ]
    registry: Dict[str, object] = {
        "format": "smavg-surface-registry",
        "version": 1,
        "generated_at": _now(),
        "run_dir": str(run_dir),
        "budget_tokens": budget_tokens,
        "home": str(home),
        "smavg_repo": str(smavg_repo) if smavg_repo.exists() else None,
        "status_definitions": {
            "verified_local": "Local files or Smavg MCP descriptors were read and hashed; exact expansion is possible through context JSON where provided.",
            "discovered": "Local surface exists on disk, but no external callability was attempted.",
            "configured_unverified": "A local config reference exists, but Smavg did not call the external MCP/app surface.",
            "partial": "Some expected local files exist and some are missing.",
            "missing": "Expected local surface path was not found.",
        },
        "truth_boundary": TRUTH_BOUNDARY,
        "surfaces": surfaces,
        "context_groups": context_groups,
        "config_summaries": config_summaries,
    }
    registry["summary"] = _registry_summary(registry)
    _write_json_atomic(run_dir / "surfaces.json", registry)
    _write_text_atomic(run_dir / "surfaces.md", render_surface_registry_markdown(registry))
    registry["surfaces_json"] = str(run_dir / "surfaces.json")
    registry["surfaces_markdown"] = str(run_dir / "surfaces.md")
    return registry


def render_surface_registry_markdown(registry: Dict[str, object]) -> str:
    summary = registry.get("summary", {})
    lines = [
        "# Smavg Surface Registry",
        "",
        str(registry.get("truth_boundary", TRUTH_BOUNDARY)),
        "",
        "## Summary",
        "",
        f"- Surfaces inventoried: {summary.get('surfaces', 0)}",
        f"- Context groups built: {summary.get('context_groups', 0)}",
        f"- Config summaries: {summary.get('config_summaries', 0)}",
        f"- Raw context tokens estimate: {summary.get('raw_tokens_estimate', 0)}",
        f"- Brief tokens estimate: {summary.get('brief_tokens_estimate', 0)}",
        f"- Registry context reduction: {_format_ratio(summary.get('token_reduction_ratio'))}",
        "",
        "## Status Counts",
        "",
    ]
    for status, count in sorted(dict(summary.get("by_status", {})).items()):
        lines.append(f"- `{status}`: {count}")
    lines.extend(["", "## Type Counts", ""])
    for kind, count in sorted(dict(summary.get("by_type", {})).items()):
        lines.append(f"- `{kind}`: {count}")

    lines.extend(["", "## Context Groups", ""])
    for group in registry.get("context_groups", []):
        if not isinstance(group, dict):
            continue
        lines.extend(
            [
                f"### {group.get('label')}",
                "",
                f"- Type: `{group.get('type')}`",
                f"- Status: `{group.get('status')}`",
                f"- Files: {group.get('file_count', 0)}",
                f"- Raw tokens: {group.get('raw_tokens_estimate', 0)}",
                f"- Brief tokens: {group.get('brief_tokens_estimate', 0)}",
                f"- Reduction: {_format_ratio(group.get('token_reduction_ratio'))}",
                f"- Context markdown: `{group.get('context_markdown')}`",
                f"- Context JSON: `{group.get('context_json')}`",
                "",
            ]
        )
        if group.get("warnings"):
            lines.append("- Warnings:")
            for warning in group.get("warnings", [])[:6]:
                lines.append(f"  - {warning}")
            lines.append("")

    configured = [
        item for item in registry.get("surfaces", [])
        if isinstance(item, dict) and item.get("status") == "configured_unverified"
    ]
    if configured:
        lines.extend(["## Configured But Not Called", ""])
        for item in configured[:60]:
            lines.append(f"- `{item.get('id')}`: {item.get('label')} (`{item.get('path')}`)")
        if len(configured) > 60:
            lines.append(f"- ... {len(configured) - 60} more")
        lines.append("")

    lines.extend(
        [
            "## Rule",
            "",
            "A discovered skill/plugin/MCP config is not treated as callable until a local tool or external host proves it. Smavg can still reduce and verify the repeated local setup files around that surface.",
            "",
        ]
    )
    return "\n".join(lines)


def run_surface_gauntlet(
    output_dir: Path,
    *,
    budget_tokens: int = 3000,
    repeat_count: int = 3,
    reset: bool = False,
    home: Optional[Path] = None,
    smavg_repo: Optional[Path] = None,
) -> Dict[str, object]:
    """Run local exact-expansion checks over all registry context groups."""
    if repeat_count < 1:
        raise SurfaceError("repeat_count must be at least 1")
    if budget_tokens <= 0:
        raise SurfaceError("budget_tokens must be positive")
    output_dir = Path(output_dir).expanduser().resolve()
    if reset and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    registry = scan_surfaces(
        out_dir=output_dir,
        run_id="registry",
        budget_tokens=budget_tokens,
        home=home,
        smavg_repo=smavg_repo,
    )
    results = [
        _run_context_group_gauntlet(group, output_dir / "exact", repeat_count)
        for group in registry.get("context_groups", [])
        if isinstance(group, dict)
    ]
    report: Dict[str, object] = {
        "format": "smavg-surface-gauntlet",
        "version": 1,
        "generated_at": _now(),
        "output_dir": str(output_dir),
        "budget_tokens": budget_tokens,
        "repeat_count": repeat_count,
        "registry_json": registry.get("surfaces_json"),
        "registry_markdown": registry.get("surfaces_markdown"),
        "trust_rule": (
            "Surface gauntlet reads raw local files only as the scoring oracle. "
            "A context group is verified when its context JSON can exact-expand "
            "representative files with SHA-256 checks. Configured MCP/app surfaces "
            "are inventory-only unless a local callable tool is exposed."
        ),
        "registry_summary": registry.get("summary", {}),
        "results": results,
    }
    report["summary"] = _gauntlet_summary(results, registry, repeat_count)
    _write_json_atomic(output_dir / "results.json", report)
    _write_text_atomic(output_dir / "report.md", render_surface_gauntlet_markdown(report))
    return report


def render_surface_gauntlet_markdown(report: Dict[str, object]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# Smavg Surface Gauntlet",
        "",
        str(report.get("trust_rule", "")),
        "",
        "## Summary",
        "",
        f"- Inventory surfaces: {summary.get('surfaces', 0)}",
        f"- Context groups: {summary.get('context_groups', 0)}",
        f"- Verified groups: {summary.get('verified_groups', 0)}/{summary.get('context_groups', 0)}",
        f"- Useful groups: {summary.get('useful_groups', 0)}/{summary.get('context_groups', 0)}",
        f"- Weak/no-benefit groups: {summary.get('weak_groups', 0)}",
        f"- Failed groups: {summary.get('failed_groups', 0)}",
        f"- Exact expansions: {summary.get('exact_expansion_pass', 0)}/{summary.get('exact_expansion_total', 0)}",
        f"- Configured unverified surfaces: {summary.get('configured_unverified_surfaces', 0)}",
        f"- Raw tokens estimate: {summary.get('raw_tokens_estimate', 0)}",
        f"- Smavg supplied tokens estimate: {summary.get('smavg_supplied_tokens_estimate', 0)}",
        f"- First-time reduction: {_format_ratio(summary.get('first_time_reduction_ratio'))}",
        f"- Repeated raw tokens estimate: {summary.get('repeated_raw_tokens_estimate', 0)}",
        f"- Repeated Smavg tokens estimate: {summary.get('repeated_smavg_tokens_estimate', 0)}",
        f"- Repeated-work reduction: {_format_ratio(summary.get('repeated_reduction_ratio'))}",
        f"- Full raw source supplied by Smavg: `{summary.get('full_raw_source_supplied_by_smavg', False)}`",
        "",
        "## Results",
        "",
    ]
    for item in sorted(report.get("results", []), key=lambda row: natural_key(str(row.get("id", "")))):
        lines.extend(
            [
                f"### {item.get('label')}",
                "",
                f"- ID: `{item.get('id')}`",
                f"- Type: `{item.get('type')}`",
                f"- Status: `{item.get('status')}`",
                f"- Raw tokens: {item.get('raw_tokens_estimate', 0)}",
                f"- Brief tokens: {item.get('brief_tokens_estimate', 0)}",
                f"- Exact tokens: {item.get('exact_tokens_estimate', 0)}",
                f"- First-time reduction: {_format_ratio(item.get('first_time_reduction_ratio'))}",
                f"- Repeated-work reduction: {_format_ratio(item.get('repeated_reduction_ratio'))}",
                f"- Exact expansion: {item.get('exact_expansion_pass', 0)}/{item.get('exact_expansion_total', 0)}",
                f"- Context JSON: `{item.get('context_json')}`",
                "",
            ]
        )
        if item.get("warnings"):
            lines.append("- Warnings:")
            for warning in item.get("warnings", [])[:8]:
                lines.append(f"  - {warning}")
            lines.append("")
        if item.get("failures"):
            lines.append("- Failures:")
            for failure in item.get("failures", [])[:8]:
                lines.append(f"  - {failure}")
            lines.append("")
    return "\n".join(lines)


def _discover_surface_records(home: Path, smavg_repo: Path) -> List[Dict[str, object]]:
    records: List[Dict[str, object]] = []
    for root_id, root, surface_type in _skill_roots(home):
        if not root.exists():
            records.append(_missing_record(f"{surface_type}:{root_id}", surface_type, root_id, root))
            continue
        for path in _skill_files(root):
            rel = path.relative_to(root).as_posix()
            records.append(_skill_record(root_id, surface_type, root, rel, path))
    records.extend(_plugin_bundle_records(home / ".codex" / "plugins" / "cache"))
    records.extend(_workflow_records())
    records.extend(_mcp_config_records(home))
    records.extend(_smavg_mcp_records())
    if smavg_repo.exists():
        records.append(
            {
                "id": "project:smavg-dev",
                "type": "project",
                "label": "Smavg development repo",
                "status": "discovered",
                "path": str(smavg_repo),
                "notes": ["Local project surface for continuing Smavg development."],
            }
        )
    else:
        records.append(_missing_record("project:smavg-dev", "project", "Smavg development repo", smavg_repo))
    records.sort(key=lambda item: natural_key(str(item.get("id", ""))))
    return records


def _skill_roots(home: Path) -> List[Tuple[str, Path, str]]:
    return [
        ("codex-skills", home / ".codex" / "skills", "skill"),
        ("agents-skills", home / ".agents" / "skills", "skill"),
        ("plugin-cache", home / ".codex" / "plugins" / "cache", "plugin_skill"),
    ]


def _skill_files(root: Path) -> List[Path]:
    try:
        return sorted(
            (path for path in root.rglob("SKILL.md") if path.is_file()),
            key=lambda path: natural_key(path.relative_to(root).as_posix()),
        )
    except OSError:
        return []


def _skill_record(root_id: str, surface_type: str, root: Path, rel: str, path: Path) -> Dict[str, object]:
    text = _read_text_best_effort(path)
    metadata = _skill_metadata(text)
    sid = f"{surface_type}:{root_id}:{rel}"
    return {
        "id": _surface_id(sid),
        "type": surface_type,
        "label": metadata.get("name") or rel.replace("/SKILL.md", ""),
        "description": metadata.get("description", ""),
        "status": "discovered",
        "path": str(path),
        "root": str(root),
        "relative_path": rel,
        "bytes": _safe_size(path),
        "tokens_estimate": estimate_tokens(text),
        "notes": ["Local skill file discovered. Callability depends on the host session exposing the skill/tool."],
    }


def _plugin_bundle_records(cache: Path) -> List[Dict[str, object]]:
    if not cache.exists():
        return [_missing_record("plugin-cache", "plugin_bundle", "Codex plugin cache", cache)]
    bundles: Dict[Path, List[Path]] = {}
    for skill in _skill_files(cache):
        bundle = _plugin_bundle_path(cache, skill)
        bundles.setdefault(bundle, []).append(skill)
    records = []
    for bundle, skills in sorted(bundles.items(), key=lambda item: natural_key(item[0].as_posix())):
        rel = bundle.relative_to(cache).as_posix() if _is_relative_to(bundle, cache) else bundle.name
        records.append(
            {
                "id": _surface_id(f"plugin:{rel}"),
                "type": "plugin_bundle",
                "label": rel,
                "status": "discovered",
                "path": str(bundle),
                "skill_count": len(skills),
                "notes": ["Plugin bundle discovered in local cache. External app/account callability is not implied."],
            }
        )
    return records


def _plugin_bundle_path(cache: Path, skill: Path) -> Path:
    rel = skill.relative_to(cache).parts
    if len(rel) >= 3 and rel[0] in {"openai-bundled", "openai-primary-runtime"}:
        return cache.joinpath(*rel[:3])
    if len(rel) >= 3 and rel[0] in {"openai-curated", "personal"}:
        return cache.joinpath(*rel[:3])
    if len(rel) >= 1:
        return cache / rel[0]
    return cache


def _workflow_records() -> List[Dict[str, object]]:
    records = []
    for profile in available_workflow_profiles():
        name = str(profile.get("name", ""))
        requested = int(profile.get("files", 0))
        status = "discovered"
        notes = ["Named Smavg workflow profile. Exact file availability is verified by context build/gauntlet."]
        records.append(
            {
                "id": _surface_id(f"workflow:{name}"),
                "type": "workflow",
                "label": name,
                "description": str(profile.get("description", "")),
                "status": status,
                "requested_files": requested,
                "notes": notes,
            }
        )
    return records


def _mcp_config_records(home: Path) -> List[Dict[str, object]]:
    records = []
    for path in _candidate_config_paths(home):
        if not path.exists() or not path.is_file():
            continue
        summary = _config_summary(path)
        records.append(
            {
                "id": _surface_id(f"mcp-config:{path}"),
                "type": "mcp_config",
                "label": path.name,
                "status": "configured_unverified",
                "path": str(path),
                "bytes": summary["bytes"],
                "sha256": summary["sha256"],
                "sections": summary["sections"],
                "keys": summary["keys"],
                "notes": [
                    "Config file is inventoried by path, hash, sections, and keys only.",
                    "Raw config values are not stored in the registry to avoid secrets.",
                ],
            }
        )
    return records


def _smavg_mcp_records() -> List[Dict[str, object]]:
    try:
        from .mcp_server import _tools  # Local descriptor only; no server loop is started.

        tools = _tools()
    except Exception:
        return []
    return [
        {
            "id": "mcp-server:smavg",
            "type": "mcp_server",
            "label": "Smavg MCP stdio server",
            "status": "verified_local",
            "tool_count": len(tools),
            "tools": [str(item.get("name", "")) for item in tools if isinstance(item, dict)],
            "notes": ["Local Smavg MCP descriptor loaded without starting an external server."],
        }
    ]


def _context_group_specs(
    *,
    home: Path,
    smavg_repo: Path,
    config_summaries: List[Dict[str, object]],
) -> List[ContextGroupSpec]:
    specs: List[ContextGroupSpec] = []
    codex_skills = _file_map_for_skills(home / ".codex" / "skills", prefix="codex-skills")
    if codex_skills:
        specs.append(ContextGroupSpec("codex-skills", "skill_group", "Codex local skills", file_map=codex_skills))
    agents_skills = _file_map_for_skills(home / ".agents" / "skills", prefix="agents-skills")
    if agents_skills:
        specs.append(ContextGroupSpec("agents-skills", "skill_group", "Agents local skills", file_map=agents_skills))
    plugin_skills = _file_map_for_skills(home / ".codex" / "plugins" / "cache", prefix="plugin-skills")
    if plugin_skills:
        specs.append(ContextGroupSpec("plugin-skills", "plugin_group", "Codex plugin-cache skills", file_map=plugin_skills))
    memories = home / ".codex" / "memories"
    if memories.exists():
        specs.append(ContextGroupSpec("codex-memories", "memory_group", "Codex memory files", source=memories))
    if smavg_repo.exists():
        specs.append(ContextGroupSpec("smavg-dev", "project", "Smavg development repo", source=smavg_repo))
    config_map = {
        f"sanitized-configs/{Path(str(item['summary_path'])).name}": Path(str(item["summary_path"]))
        for item in config_summaries
        if item.get("summary_path")
    }
    if config_map:
        specs.append(
            ContextGroupSpec(
                "mcp-config-summaries",
                "mcp_config_group",
                "Sanitized MCP/config summaries",
                file_map=config_map,
                notes="Exact expansion returns sanitized summaries, not raw config values.",
            )
        )
    for profile in available_workflow_profiles():
        name = str(profile.get("name", ""))
        if name:
            specs.append(ContextGroupSpec(f"workflow-{name}", "workflow", f"Workflow profile: {name}", notes=name))
    return specs


def _file_map_for_skills(root: Path, *, prefix: str) -> Dict[str, Path]:
    if not root.exists():
        return {}
    return {
        f"{prefix}/{path.relative_to(root).as_posix()}": path
        for path in _skill_files(root)
    }


def _build_context_group(spec: ContextGroupSpec, context_dir: Path, budget_tokens: int) -> Dict[str, object]:
    context_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(spec.id)
    context_md = context_dir / f"{slug}.md"
    context_json = context_dir / f"{slug}.json"
    result: Dict[str, object] = {
        "id": spec.id,
        "type": spec.type,
        "label": spec.label,
        "status": "not_run",
        "context_markdown": str(context_md),
        "context_json": str(context_json),
        "notes": [spec.notes] if spec.notes else [],
        "warnings": [],
        "failures": [],
    }
    try:
        if spec.type == "workflow":
            report = build_workflow_context_report(spec.notes, budget_tokens=budget_tokens)
        elif spec.file_map is not None:
            report = build_context_report_from_file_map(
                spec.file_map,
                source_label=f"surface:{spec.id}",
                source_kind=spec.type,
                budget_tokens=budget_tokens,
                rebuild_command="smavg surfaces scan",
            )
        elif spec.source is not None:
            report = build_context_report(spec.source, budget_tokens=budget_tokens)
            report["source_kind"] = spec.type
        else:
            raise SurfaceError(f"Context group {spec.id} has no source")
        write_context_outputs(report, context_md, context_json)
        assessment = report.get("assessment", {}) if isinstance(report.get("assessment"), dict) else {}
        status = "verified_local" if int(report.get("file_count", 0)) > 0 else "missing"
        if assessment.get("status") in {"weak", "no_text"}:
            result["warnings"].append(str(assessment.get("finding", "Weak or no text benefit.")))
        result.update(
            {
                "status": status,
                "file_count": int(report.get("file_count", 0)),
                "text_file_count": int(report.get("text_file_count", 0)),
                "binary_file_count": int(report.get("binary_file_count", 0)),
                "logical_bytes": int(report.get("logical_bytes", 0)),
                "raw_tokens_estimate": int(report.get("original_tokens_estimate", 0)),
                "brief_tokens_estimate": int(report.get("brief_tokens_estimate", 0)),
                "token_reduction_ratio": report.get("token_reduction_ratio"),
                "families_detected": int(report.get("families_detected", 0)),
                "family_coverage_percent": report.get("family_coverage_percent", 0.0),
                "assessment": assessment,
                "recommended_expansions": report.get("recommended_expansions", [])[:8],
            }
        )
    except (ContextError, SurfaceError, OSError, json.JSONDecodeError) as exc:
        result["status"] = "missing"
        result["failures"].append(str(exc))
    return result


def _run_context_group_gauntlet(group: Dict[str, object], exact_root: Path, repeat_count: int) -> Dict[str, object]:
    result = {
        "id": group.get("id"),
        "type": group.get("type"),
        "label": group.get("label"),
        "status": "FAIL",
        "context_json": group.get("context_json"),
        "context_markdown": group.get("context_markdown"),
        "raw_tokens_estimate": int(group.get("raw_tokens_estimate", 0)),
        "brief_tokens_estimate": int(group.get("brief_tokens_estimate", 0)),
        "exact_tokens_estimate": 0,
        "smavg_supplied_tokens_estimate": int(group.get("brief_tokens_estimate", 0)),
        "exact_expansion_pass": 0,
        "exact_expansion_total": 0,
        "full_raw_source_supplied_by_smavg": False,
        "expansions": [],
        "warnings": list(group.get("warnings", [])) if isinstance(group.get("warnings"), list) else [],
        "failures": list(group.get("failures", [])) if isinstance(group.get("failures"), list) else [],
    }
    context_json = Path(str(group.get("context_json", "")))
    context_md = Path(str(group.get("context_markdown", "")))
    if not context_json.exists():
        result["failures"].append("Context JSON was not written")
        return result
    try:
        report = json.loads(context_json.read_text(encoding="utf-8"))
        markdown = context_md.read_text(encoding="utf-8") if context_md.exists() else render_context_markdown(report)
        files_by_path = {
            str(item["path"]): item
            for item in report.get("files", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        paths = _gauntlet_paths(report)
        if not paths:
            result["warnings"].append("No representative exact paths found")
        exact_dir = exact_root / _slug(str(group.get("id", "group")))
        exact_dir.mkdir(parents=True, exist_ok=True)
        exact_tokens = 0
        rows = []
        for relative in paths:
            record = files_by_path.get(relative)
            row = {
                "path": relative,
                "present_in_context_json": record is not None,
                "visible_in_context_markdown": relative in markdown,
                "expanded": False,
                "verified": False,
                "tokens_estimate": int(record.get("estimated_tokens", 0)) if record else 0,
                "output": str(exact_dir / _safe_exact_name(relative)),
            }
            if record is None:
                result["failures"].append(f"Representative path missing: {relative}")
            else:
                exact_tokens += int(row["tokens_estimate"])
                try:
                    written = expand_context_file(context_json, relative, Path(str(row["output"])))
                    row["bytes"] = written
                    row["expanded"] = True
                    row["verified"] = True
                except ContextError as exc:
                    result["failures"].append(str(exc))
            if not row["visible_in_context_markdown"]:
                result["warnings"].append(f"Representative path not visible in markdown: {relative}")
            rows.append(row)
        result["expansions"] = rows
        result["exact_tokens_estimate"] = exact_tokens
        result["exact_expansion_total"] = len(rows)
        result["exact_expansion_pass"] = sum(1 for row in rows if row.get("verified"))
        supplied = int(group.get("brief_tokens_estimate", 0)) + exact_tokens
        raw = int(group.get("raw_tokens_estimate", 0))
        result["smavg_supplied_tokens_estimate"] = supplied
        result["first_time_reduction_ratio"] = _ratio(raw, supplied)
        result["repeated_raw_tokens_estimate"] = raw * repeat_count
        result["repeated_smavg_tokens_estimate"] = supplied
        result["repeated_reduction_ratio"] = _ratio(raw * repeat_count, supplied)
        all_exact = result["exact_expansion_pass"] == result["exact_expansion_total"]
        if all_exact and raw and supplied < raw:
            result["status"] = "PASS"
        elif all_exact:
            result["status"] = "WEAK"
            result["warnings"].append("Exact expansion passed, but first-time token reduction was weak or not meaningful.")
        else:
            result["status"] = "FAIL"
    except (OSError, json.JSONDecodeError) as exc:
        result["failures"].append(str(exc))
    return result


def _registry_summary(registry: Dict[str, object]) -> Dict[str, object]:
    surfaces = [item for item in registry.get("surfaces", []) if isinstance(item, dict)]
    groups = [item for item in registry.get("context_groups", []) if isinstance(item, dict)]
    by_type = Counter(str(item.get("type", "unknown")) for item in surfaces)
    by_status = Counter(str(item.get("status", "unknown")) for item in surfaces)
    raw = sum(int(item.get("raw_tokens_estimate", 0)) for item in groups)
    brief = sum(int(item.get("brief_tokens_estimate", 0)) for item in groups)
    return {
        "surfaces": len(surfaces),
        "context_groups": len(groups),
        "config_summaries": len(registry.get("config_summaries", [])),
        "by_type": dict(sorted(by_type.items())),
        "by_status": dict(sorted(by_status.items())),
        "raw_tokens_estimate": raw,
        "brief_tokens_estimate": brief,
        "token_reduction_ratio": _ratio(raw, brief),
    }


def _gauntlet_summary(
    results: List[Dict[str, object]],
    registry: Dict[str, object],
    repeat_count: int,
) -> Dict[str, object]:
    exact_total = sum(int(item.get("exact_expansion_total", 0)) for item in results)
    exact_pass = sum(int(item.get("exact_expansion_pass", 0)) for item in results)
    raw = sum(int(item.get("raw_tokens_estimate", 0)) for item in results)
    supplied = sum(int(item.get("smavg_supplied_tokens_estimate", 0)) for item in results)
    repeated_raw = raw * repeat_count
    repeated_supplied = supplied
    surfaces = [item for item in registry.get("surfaces", []) if isinstance(item, dict)]
    configured = [item for item in surfaces if item.get("status") == "configured_unverified"]
    return {
        "surfaces": len(surfaces),
        "context_groups": len(results),
        "verified_groups": sum(1 for item in results if item.get("status") in {"PASS", "WEAK"}),
        "useful_groups": sum(1 for item in results if item.get("status") == "PASS"),
        "weak_groups": sum(1 for item in results if item.get("status") == "WEAK"),
        "failed_groups": sum(1 for item in results if item.get("status") == "FAIL"),
        "exact_expansion_pass": exact_pass,
        "exact_expansion_total": exact_total,
        "configured_unverified_surfaces": len(configured),
        "raw_tokens_estimate": raw,
        "smavg_supplied_tokens_estimate": supplied,
        "first_time_reduction_ratio": _ratio(raw, supplied),
        "repeated_raw_tokens_estimate": repeated_raw,
        "repeated_smavg_tokens_estimate": repeated_supplied,
        "repeated_reduction_ratio": _ratio(repeated_raw, repeated_supplied),
        "full_raw_source_supplied_by_smavg": False,
    }


def _write_config_summaries(home: Path, output_dir: Path) -> List[Dict[str, object]]:
    summaries = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in _candidate_config_paths(home):
        if not path.exists() or not path.is_file():
            continue
        summary = _config_summary(path)
        out = output_dir / f"{_slug(path.as_posix())}.md"
        text = _render_config_summary(path, summary)
        _write_text_atomic(out, text)
        summary["summary_path"] = str(out)
        summaries.append(summary)
    return summaries


def _candidate_config_paths(home: Path) -> List[Path]:
    candidates = [
        home / ".codex" / "config.toml",
        home / ".codex" / "browser" / "config.toml",
        home / ".mcp.json",
        home / ".config" / "mcp" / "config.json",
        home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
    ]
    agents = home / ".codex" / "agents"
    if agents.exists():
        candidates.extend(sorted(agents.glob("*.toml"), key=lambda path: natural_key(path.name)))
    output = []
    seen = set()
    for path in candidates:
        resolved = path.expanduser()
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        output.append(resolved)
    return output


def _config_summary(path: Path) -> Dict[str, object]:
    data = path.read_bytes()
    text = _decode_text(data)
    sections = []
    keys = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("[") and "]" in stripped:
            sections.append(stripped.split("]", 1)[0] + "]")
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)\s*[:=]", stripped)
        if match:
            key = match.group(1)
            if _looks_secret_key(key):
                key = f"{key}:redacted"
            keys.append(key)
    return {
        "path": str(path),
        "bytes": len(data),
        "sha256": sha256(data).hexdigest(),
        "sections": sections[:80],
        "keys": keys[:120],
    }


def _render_config_summary(path: Path, summary: Dict[str, object]) -> str:
    lines = [
        f"# Sanitized Config Summary: {path.name}",
        "",
        "Raw values are intentionally omitted. This file records only path, size, hash, section names, and keys.",
        "",
        f"- Source path: `{path}`",
        f"- Bytes: {summary.get('bytes', 0)}",
        f"- SHA-256: `{summary.get('sha256')}`",
        "",
        "## Sections",
        "",
    ]
    for section in summary.get("sections", []):
        lines.append(f"- `{section}`")
    if not summary.get("sections"):
        lines.append("- none detected")
    lines.extend(["", "## Keys", ""])
    for key in summary.get("keys", []):
        lines.append(f"- `{key}`")
    if not summary.get("keys"):
        lines.append("- none detected")
    lines.append("")
    return "\n".join(lines)


def _gauntlet_paths(report: Dict[str, object], limit: int = 3) -> List[str]:
    paths = []
    for item in report.get("recommended_expansions", []):
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            paths.append(item["path"])
    for item in report.get("compact_file_index", []):
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            paths.append(item["path"])
    for item in sorted(report.get("files", []), key=lambda row: int(row.get("estimated_tokens", 0)) if isinstance(row, dict) else 0, reverse=True):
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            paths.append(item["path"])
    seen = set()
    output = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        output.append(path)
        if len(output) >= limit:
            break
    return output


def _skill_metadata(text: str) -> Dict[str, str]:
    output: Dict[str, str] = {}
    if not text.startswith("---"):
        return output
    parts = text.split("---", 2)
    if len(parts) < 3:
        return output
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower()
        value = value.strip().strip("'\"")
        if key in {"name", "description"}:
            output[key] = value
    return output


def _missing_record(surface_id: str, surface_type: str, label: str, path: Path) -> Dict[str, object]:
    return {
        "id": _surface_id(surface_id),
        "type": surface_type,
        "label": label,
        "status": "missing",
        "path": str(path),
        "notes": ["Expected local surface path was not found."],
    }


def _read_text_best_effort(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if b"\x00" in data[:8192]:
        return ""
    return _decode_text(data)


def _decode_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin1", errors="replace")


def _looks_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(token in lowered for token in ("key", "token", "secret", "password", "credential", "auth"))


def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _surface_id(value: str) -> str:
    return _slug(value.replace(os.sep, "/"))


def _safe_exact_name(path: str) -> str:
    return _slug(path.replace("/", "__")) or "exact-file"


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._")[:140] or "surface"


def _default_run_id(label: str) -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{_slug(label)}"


def _ratio(before: int, after: int) -> Optional[float]:
    return round(before / after, 3) if before and after else None


def _format_ratio(value: object) -> str:
    return "n/a" if value is None else f"{value}x"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _write_json_atomic(path: Path, value: Dict[str, object]) -> None:
    _write_text_atomic(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


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
