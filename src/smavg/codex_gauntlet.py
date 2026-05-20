"""Codex workload gauntlet for Smavg context quality and token savings."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .context import (
    ContextError,
    build_context_report,
    expand_context_file,
    render_context_markdown,
    write_context_outputs,
)
from .utils import natural_key
from .workflow_context import build_workflow_context_report


class CodexGauntletError(RuntimeError):
    """Raised when the Codex workload gauntlet cannot run."""


@dataclass(frozen=True)
class CodexEvidenceTask:
    """A deterministic A/B task scored against required evidence."""

    name: str
    question: str
    required_paths: tuple[str, ...]
    evidence_terms: tuple[str, ...]
    notes: str = ""


@dataclass(frozen=True)
class CodexWorkloadProbe:
    """A real Codex workload surface plus exact files needed for a task."""

    name: str
    description: str
    source: Optional[Path] = None
    workflow: Optional[str] = None
    required_paths: tuple[str, ...] = ()
    tasks: tuple[CodexEvidenceTask, ...] = ()
    notes: str = ""


def run_codex_workload_gauntlet(
    output_dir: Path,
    *,
    probes: Optional[Iterable[CodexWorkloadProbe]] = None,
    budget_tokens: int = 3000,
    repeat_count: int = 3,
    reset: bool = False,
) -> Dict[str, object]:
    """Run token and quality checks against Codex-local work surfaces."""
    output_dir = Path(output_dir).expanduser().resolve()
    if reset and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    selected = list(probes) if probes is not None else default_codex_workload_probes()
    if not selected:
        raise CodexGauntletError("No Codex workload probes are available")
    if repeat_count < 1:
        raise CodexGauntletError("repeat_count must be at least 1")

    results = []
    for probe in selected:
        results.append(_run_probe(probe, output_dir, budget_tokens, repeat_count))

    report = {
        "format": "smavg-codex-workload-gauntlet",
        "version": 1,
        "generated_at": _utc_now(),
        "output_dir": str(output_dir),
        "budget_tokens": budget_tokens,
        "repeat_count": repeat_count,
        "trust_rule": (
            "A result counts only when Smavg reduces tokens and exact required "
            "files expand from source with SHA-256 verification. Model-routing "
            "quality is reported separately: if required files are not visible "
            "in the brief, the agent must be given an exact path or use a query "
            "step before relying on the brief. Task A/B scores are deterministic "
            "evidence checks, not AI-generated answers."
        ),
        "summary": _summary(results),
        "results": results,
    }
    (output_dir / "results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(_render_markdown(report), encoding="utf-8")
    return report


def default_codex_workload_probes() -> List[CodexWorkloadProbe]:
    """Return the current local Codex surfaces that are safe to measure."""
    home = Path.home()
    probes = [
        CodexWorkloadProbe(
            name="smavg-dev",
            description="Smavg repo development context.",
            source=home / "smavg",
            required_paths=(
                "README.md",
                "src/smavg/cli.py",
                "src/smavg/context.py",
                "src/smavg/preflight.py",
                "src/smavg/mcp_server.py",
            ),
            tasks=(
                CodexEvidenceTask(
                    name="smavg-current-proof",
                    question="What is the latest Codex A/B gauntlet proof?",
                    required_paths=("README.md",),
                    evidence_terms=("Codex A/B evidence gauntlet", "16/16", "task-evidence"),
                ),
                CodexEvidenceTask(
                    name="smavg-preflight-entrypoint",
                    question="Which function implements Smavg preflight?",
                    required_paths=("src/smavg/preflight.py",),
                    evidence_terms=("def run_preflight", "preflight.json", "ContextError"),
                ),
                CodexEvidenceTask(
                    name="smavg-mcp-tools",
                    question="Which MCP surface exposes Smavg preflight and notifications?",
                    required_paths=("src/smavg/mcp_server.py",),
                    evidence_terms=("smavg_preflight", "tools/list", "notifications/initialized"),
                ),
            ),
            notes="Represents continuing Smavg development inside Codex.",
        ),
        CodexWorkloadProbe(
            name="codex-memories",
            description="Codex durable memory system.",
            source=home / ".codex" / "memories",
            required_paths=(
                "medium-term/smavg_runbook.md",
                "short-term/current_focus.md",
                "short-term/session_handoff.md",
                "long-term/collaboration_preferences.md",
            ),
            tasks=(
                CodexEvidenceTask(
                    name="memory-latest-gauntlet",
                    question="What does durable memory say about the latest Smavg Codex A/B gauntlet?",
                    required_paths=("short-term/current_focus.md",),
                    evidence_terms=("Codex A/B Evidence Gauntlet", "16/16", "A/B task evidence"),
                ),
                CodexEvidenceTask(
                    name="memory-smavg-runbook",
                    question="Where is Smavg's durable runbook evidence recorded?",
                    required_paths=("medium-term/smavg_runbook.md",),
                    evidence_terms=("codex-ab-gauntlet-v1", "16/16", "deterministic evidence scoring"),
                ),
            ),
            notes="Represents session resume and project recall.",
        ),
        CodexWorkloadProbe(
            name="codex-skills",
            description="Local Codex skills directory.",
            source=home / ".codex" / "skills",
            required_paths=(
                "smavg-repetition-firewall/SKILL.md",
                "x-browser-automation/SKILL.md",
                "codex-memory-maintainer/SKILL.md",
                "playwright/SKILL.md",
            ),
            tasks=(
                CodexEvidenceTask(
                    name="skill-smavg-gauntlet",
                    question="How should Codex run the Smavg workload gauntlet?",
                    required_paths=("smavg-repetition-firewall/SKILL.md",),
                    evidence_terms=("codex-gauntlet", "16/16", "A/B evidence gauntlet"),
                ),
                CodexEvidenceTask(
                    name="skill-x-browsermcp",
                    question="Which local skill handles X BrowserMCP work?",
                    required_paths=("x-browser-automation/SKILL.md",),
                    evidence_terms=("x-browser-automation", "BrowserMCP", "x.com"),
                ),
            ),
            notes="Represents choosing and expanding exact local skills.",
        ),
        CodexWorkloadProbe(
            name="agents-skills",
            description="Local .agents skills directory.",
            source=home / ".agents" / "skills",
            required_paths=(
                "find-skills/SKILL.md",
                "shopify-admin/SKILL.md",
            ),
            tasks=(
                CodexEvidenceTask(
                    name="agents-find-skills",
                    question="How does the agent find installable skills?",
                    required_paths=("find-skills/SKILL.md",),
                    evidence_terms=("npx skills find", "leaderboard", "find a skill"),
                ),
                CodexEvidenceTask(
                    name="agents-shopify-admin",
                    question="What does the Shopify skill help developers write?",
                    required_paths=("shopify-admin/SKILL.md",),
                    evidence_terms=("Admin GraphQL API", "GraphQL queries", "OPT_OUT_INSTRUMENTATION"),
                ),
            ),
            notes="Represents non-Codex local skill surfaces.",
        ),
        CodexWorkloadProbe(
            name="codex-plugin-cache",
            description="Installed Codex plugin cache.",
            source=home / ".codex" / "plugins" / "cache",
            required_paths=(
                "openai-bundled/browser/0.1.0-alpha2/skills/browser/SKILL.md",
                "openai-bundled/chrome/0.1.7/skills/chrome/SKILL.md",
                "openai-curated/build-web-apps/dc902811/skills/frontend-app-builder/SKILL.md",
                "personal/personal-codex-ops/0.1.1/skills/x-browser-automation/SKILL.md",
            ),
            tasks=(
                CodexEvidenceTask(
                    name="plugin-browser-runtime",
                    question="What browser runtime setup does the Browser skill reference?",
                    required_paths=("openai-bundled/browser/0.1.0-alpha2/skills/browser/SKILL.md",),
                    evidence_terms=("setupBrowserRuntime", "Browser Safety", "nameSession"),
                ),
                CodexEvidenceTask(
                    name="plugin-chrome-extension",
                    question="What does the Chrome skill say about the Codex Chrome Extension?",
                    required_paths=("openai-bundled/chrome/0.1.7/skills/chrome/SKILL.md",),
                    evidence_terms=("Codex Chrome Extension", "claimTab", "Chrome Safety"),
                ),
                CodexEvidenceTask(
                    name="plugin-frontend-builder",
                    question="Which skill covers new frontend app building?",
                    required_paths=("openai-curated/build-web-apps/dc902811/skills/frontend-app-builder/SKILL.md",),
                    evidence_terms=("frontend-app-builder", "Browser/IAB", "faithfully verified"),
                ),
            ),
            notes="Represents plugin and bundled skill reuse.",
        ),
        CodexWorkloadProbe(
            name="workflow-x-browsermcp",
            description="X BrowserMCP workflow capsule.",
            workflow="x-browsermcp",
            required_paths=(
                "skills/codex/x-browser-automation/SKILL.md",
                "memories/medium-term/x_browser_automation_workflow.md",
            ),
            tasks=(
                CodexEvidenceTask(
                    name="workflow-x-post-proof",
                    question="What real X post proved the BrowserMCP workflow?",
                    required_paths=("memories/medium-term/x_browser_automation_workflow.md",),
                    evidence_terms=("https://x.com/smavgs/status/2055607371880358384", "Your post was sent", "Smavg"),
                ),
                CodexEvidenceTask(
                    name="workflow-x-skill",
                    question="Which skill path should be expanded for X work?",
                    required_paths=("skills/codex/x-browser-automation/SKILL.md",),
                    evidence_terms=("x-browser-automation", "BrowserMCP", "Smavg"),
                ),
            ),
            notes="Represents repeated X posting/setup work.",
        ),
        CodexWorkloadProbe(
            name="workflow-hackernews-browsermcp",
            description="Hacker News BrowserMCP workflow capsule.",
            workflow="hackernews-browsermcp",
            required_paths=(
                "skills/codex/hackernews-browsermcp/SKILL.md",
                "memories/medium-term/hackernews_browsermcp_workflow.md",
            ),
            tasks=(
                CodexEvidenceTask(
                    name="workflow-hn-skill",
                    question="Which skill handles Hacker News BrowserMCP work?",
                    required_paths=("skills/codex/hackernews-browsermcp/SKILL.md",),
                    evidence_terms=("Hacker News", "Browser MCP", "human-authored"),
                ),
                CodexEvidenceTask(
                    name="workflow-hn-runbook",
                    question="What does the HN runbook say about the live website?",
                    required_paths=("memories/medium-term/hackernews_browsermcp_workflow.md",),
                    evidence_terms=("Hacker News", "news.ycombinator.com", "Browser MCP"),
                ),
            ),
            notes="Represents repeated Hacker News browsing/setup work.",
        ),
    ]
    return [probe for probe in probes if _probe_exists(probe)]


def _run_probe(
    probe: CodexWorkloadProbe,
    output_dir: Path,
    budget_tokens: int,
    repeat_count: int,
) -> Dict[str, object]:
    run_dir = output_dir / _slug(probe.name)
    run_dir.mkdir(parents=True, exist_ok=True)
    context_md = run_dir / "context.md"
    context_json = run_dir / "context.json"
    exact_dir = run_dir / "exact"
    exact_dir.mkdir(exist_ok=True)

    result: Dict[str, object] = {
        "name": probe.name,
        "description": probe.description,
        "notes": probe.notes,
        "source": str(probe.source) if probe.source is not None else None,
        "workflow": probe.workflow,
        "required_paths": list(probe.required_paths),
        "run_dir": str(run_dir),
        "context_markdown": str(context_md),
        "context_json": str(context_json),
        "status": "not_run",
        "failures": [],
        "warnings": [],
    }
    try:
        report = _build_report(probe, budget_tokens)
        write_context_outputs(report, context_md, context_json)
        markdown = render_context_markdown(report)
        loaded = json.loads(context_json.read_text(encoding="utf-8"))
        files_by_path = {
            str(item["path"]): item
            for item in loaded.get("files", [])
            if isinstance(item, dict) and isinstance(item.get("path"), str)
        }
        expansion_rows = []
        exact_tokens = 0
        all_exact = True
        all_present = True
        all_visible = True
        required_paths = _probe_required_paths(probe)
        for relative in required_paths:
            record = files_by_path.get(relative)
            output = exact_dir / _safe_exact_name(relative)
            row: Dict[str, object] = {
                "path": relative,
                "present_in_context_json": record is not None,
                "visible_in_context_markdown": relative in markdown,
                "expanded": False,
                "verified": False,
                "estimated_tokens": 0,
                "bytes": 0,
                "out": str(output),
            }
            if record is None:
                all_present = False
                all_exact = False
            else:
                row["estimated_tokens"] = int(record.get("estimated_tokens", 0))
                exact_tokens += int(row["estimated_tokens"])
                try:
                    written = expand_context_file(context_json, relative, output)
                    row["bytes"] = written
                    row["expanded"] = True
                    row["verified"] = True
                except ContextError as exc:
                    row["error"] = str(exc)
                    all_exact = False
            if not row["visible_in_context_markdown"]:
                all_visible = False
            expansion_rows.append(row)

        original_tokens = int(report.get("original_tokens_estimate", 0))
        brief_tokens = int(report.get("brief_tokens_estimate", 0))
        first_time_tokens = brief_tokens + exact_tokens
        repeated_raw_tokens = original_tokens * repeat_count
        repeated_smavg_tokens = first_time_tokens
        first_ratio = _ratio(original_tokens, first_time_tokens)
        repeated_ratio = _ratio(repeated_raw_tokens, repeated_smavg_tokens)
        brief_ratio = _ratio(original_tokens, brief_tokens)

        result.update(
            {
                "status": "PASS" if all_present and all_exact else "FAIL",
                "model_routing": "PASS" if all_visible else "NEEDS_EXACT_PATH_OR_QUERY",
                "files": report.get("file_count", 0),
                "text_files": report.get("text_file_count", 0),
                "binary_files": report.get("binary_file_count", 0),
                "logical_bytes": report.get("logical_bytes", 0),
                "raw_tokens_estimate": original_tokens,
                "brief_tokens_estimate": brief_tokens,
                "brief_only_reduction_ratio": brief_ratio,
                "required_exact_tokens_estimate": exact_tokens,
                "first_time_smavg_tokens_estimate": first_time_tokens,
                "first_time_reduction_ratio": first_ratio,
                "repeat_count": repeat_count,
                "repeated_raw_tokens_estimate": repeated_raw_tokens,
                "repeated_smavg_tokens_estimate": repeated_smavg_tokens,
                "repeated_reduction_ratio": repeated_ratio,
                "families_detected": report.get("families_detected", 0),
                "family_coverage_percent": report.get("family_coverage_percent", 0.0),
                "context_assessment": report.get("assessment", {}),
                "exact_expansion": "PASS" if all_exact else "FAIL",
                "all_required_paths_present": all_present,
                "all_required_paths_visible_in_brief": all_visible,
                "required_paths": list(required_paths),
                "expansions": expansion_rows,
                "tasks": _score_tasks(
                    probe=probe,
                    report=loaded,
                    context_json=context_json,
                    markdown=markdown,
                    exact_dir=exact_dir,
                    files_by_path=files_by_path,
                    expansion_rows=expansion_rows,
                    raw_tokens=original_tokens,
                    brief_tokens=brief_tokens,
                ),
                "applicability": _applicability(first_ratio, repeated_ratio, all_exact, all_visible),
            }
        )
        result["task_summary"] = _task_summary(result["tasks"])
        if not all_visible:
            result["warnings"].append(
                "At least one required exact path was not visible in the markdown brief; "
                "a model should be given the exact path or use a query/list step."
            )
        if not all_exact:
            result["failures"].append("At least one required exact file did not expand cleanly")
    except (ContextError, OSError, json.JSONDecodeError) as exc:
        result["status"] = "FAIL"
        result["failures"].append(str(exc))
    return result


def _score_tasks(
    *,
    probe: CodexWorkloadProbe,
    report: Dict[str, object],
    context_json: Path,
    markdown: str,
    exact_dir: Path,
    files_by_path: Dict[str, Dict[str, object]],
    expansion_rows: List[Dict[str, object]],
    raw_tokens: int,
    brief_tokens: int,
) -> List[Dict[str, object]]:
    tasks = probe.tasks or (
        CodexEvidenceTask(
            name="required-files-visible-and-exact",
            question="Can Smavg expose and expand the required exact files?",
            required_paths=tuple(probe.required_paths),
            evidence_terms=tuple(Path(path).name for path in probe.required_paths),
        ),
    )
    expansion_by_path = {str(row.get("path")): row for row in expansion_rows}
    scored = []
    for task in tasks:
        task_exact_tokens = sum(
            int(files_by_path.get(path, {}).get("estimated_tokens", 0))
            for path in task.required_paths
        )
        raw_text = _task_text_from_source(report, task.required_paths, files_by_path)
        smavg_text = _task_text_from_expanded(task.required_paths, expansion_by_path)
        raw_terms = _term_hits(raw_text, task.evidence_terms)
        smavg_terms = _term_hits(smavg_text, task.evidence_terms)
        expanded = all(
            bool(expansion_by_path.get(path, {}).get("verified"))
            for path in task.required_paths
        )
        visible = all(path in markdown for path in task.required_paths)
        raw_correct = all(raw_terms.values()) if task.evidence_terms else bool(raw_text)
        smavg_correct = all(smavg_terms.values()) if task.evidence_terms else bool(smavg_text)
        smavg_tokens = brief_tokens + task_exact_tokens
        row = {
            "name": task.name,
            "question": task.question,
            "notes": task.notes,
            "required_paths": list(task.required_paths),
            "evidence_terms": list(task.evidence_terms),
            "raw_correct": raw_correct,
            "smavg_correct": smavg_correct,
            "same_evidence": raw_terms == smavg_terms,
            "expanded_paths_verified": expanded,
            "paths_visible_in_brief": visible,
            "status": "PASS" if raw_correct and smavg_correct and expanded and visible else "FAIL",
            "raw_tokens_estimate": raw_tokens,
            "smavg_tokens_estimate": smavg_tokens,
            "token_reduction_ratio": _ratio(raw_tokens, smavg_tokens),
            "raw_term_hits": raw_terms,
            "smavg_term_hits": smavg_terms,
            "evidence_snippets": _snippets(smavg_text or raw_text, task.evidence_terms),
        }
        scored.append(row)
    return scored


def _task_text_from_source(
    report: Dict[str, object],
    paths: Iterable[str],
    files_by_path: Dict[str, Dict[str, object]],
) -> str:
    chunks = []
    for relative in paths:
        record = files_by_path.get(relative)
        if record is None:
            continue
        target = _source_target(report, record, relative)
        if target is None:
            continue
        chunks.append(_read_text_best_effort(target))
    return "\n".join(chunks)


def _task_text_from_expanded(paths: Iterable[str], expansion_by_path: Dict[str, Dict[str, object]]) -> str:
    chunks = []
    for relative in paths:
        output = expansion_by_path.get(relative, {}).get("out")
        if not output:
            continue
        chunks.append(_read_text_best_effort(Path(str(output))))
    return "\n".join(chunks)


def _source_target(
    report: Dict[str, object],
    record: Dict[str, object],
    relative: str,
) -> Optional[Path]:
    source_path = record.get("source_path")
    if isinstance(source_path, str) and source_path:
        return Path(source_path)
    source = report.get("source_path")
    if not isinstance(source, str) or not source:
        return None
    return Path(source) / relative


def _read_text_best_effort(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if b"\x00" in data[:8192]:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin1", errors="replace")


def _term_hits(text: str, terms: Iterable[str]) -> Dict[str, bool]:
    lowered = text.lower()
    return {term: term.lower() in lowered for term in terms}


def _snippets(text: str, terms: Iterable[str], limit: int = 8) -> List[Dict[str, str]]:
    lines = text.splitlines()
    output = []
    seen_terms = set()
    for term in terms:
        term_lower = term.lower()
        for line in lines:
            if term_lower not in line.lower():
                continue
            output.append({"term": term, "line": line.strip()[:220]})
            seen_terms.add(term)
            break
        if len(output) >= limit:
            break
    missing = [term for term in terms if term not in seen_terms]
    for term in missing[: max(0, limit - len(output))]:
        output.append({"term": term, "line": ""})
    return output


def _task_summary(tasks: List[Dict[str, object]]) -> Dict[str, object]:
    passed = [task for task in tasks if task.get("status") == "PASS"]
    raw_correct = [task for task in tasks if task.get("raw_correct")]
    smavg_correct = [task for task in tasks if task.get("smavg_correct")]
    routing = [task for task in tasks if task.get("paths_visible_in_brief")]
    same = [task for task in tasks if task.get("same_evidence")]
    raw_tokens = sum(int(task.get("raw_tokens_estimate", 0)) for task in tasks)
    smavg_tokens = sum(int(task.get("smavg_tokens_estimate", 0)) for task in tasks)
    return {
        "tasks": len(tasks),
        "pass": len(passed),
        "raw_correct": len(raw_correct),
        "smavg_correct": len(smavg_correct),
        "routing_pass": len(routing),
        "same_evidence": len(same),
        "raw_tokens_estimate": raw_tokens,
        "smavg_tokens_estimate": smavg_tokens,
        "token_reduction_ratio": _ratio(raw_tokens, smavg_tokens),
    }


def _build_report(probe: CodexWorkloadProbe, budget_tokens: int) -> Dict[str, object]:
    if probe.workflow is not None:
        return build_workflow_context_report(probe.workflow, budget_tokens=budget_tokens)
    if probe.source is None:
        raise CodexGauntletError(f"Probe {probe.name} has no source or workflow")
    source = probe.source.expanduser().resolve()
    if not source.is_dir():
        raise ContextError(f"Not a directory: {source}")
    return build_context_report(source, budget_tokens=budget_tokens)


def _probe_required_paths(probe: CodexWorkloadProbe) -> tuple[str, ...]:
    paths = list(probe.required_paths)
    for task in probe.tasks:
        paths.extend(task.required_paths)
    seen = set()
    output = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        output.append(path)
    return tuple(output)


def _summary(results: List[Dict[str, object]]) -> Dict[str, object]:
    passed = [item for item in results if item.get("status") == "PASS"]
    exact_pass = [item for item in results if item.get("exact_expansion") == "PASS"]
    routing_pass = [item for item in results if item.get("model_routing") == "PASS"]
    first_useful = [
        item
        for item in results
        if isinstance(item.get("first_time_reduction_ratio"), (int, float))
        and float(item["first_time_reduction_ratio"]) > 1.0
    ]
    repeated_useful = [
        item
        for item in results
        if isinstance(item.get("repeated_reduction_ratio"), (int, float))
        and float(item["repeated_reduction_ratio"]) > 1.0
    ]
    totals = {
        "raw_tokens_estimate": sum(int(item.get("raw_tokens_estimate", 0)) for item in results),
        "brief_tokens_estimate": sum(int(item.get("brief_tokens_estimate", 0)) for item in results),
        "first_time_smavg_tokens_estimate": sum(
            int(item.get("first_time_smavg_tokens_estimate", 0)) for item in results
        ),
        "repeated_raw_tokens_estimate": sum(
            int(item.get("repeated_raw_tokens_estimate", 0)) for item in results
        ),
        "repeated_smavg_tokens_estimate": sum(
            int(item.get("repeated_smavg_tokens_estimate", 0)) for item in results
        ),
    }
    totals["brief_only_reduction_ratio"] = _ratio(
        totals["raw_tokens_estimate"],
        totals["brief_tokens_estimate"],
    )
    totals["first_time_reduction_ratio"] = _ratio(
        totals["raw_tokens_estimate"],
        totals["first_time_smavg_tokens_estimate"],
    )
    totals["repeated_reduction_ratio"] = _ratio(
        totals["repeated_raw_tokens_estimate"],
        totals["repeated_smavg_tokens_estimate"],
    )
    task_rows = [
        task
        for result in results
        for task in result.get("tasks", [])
        if isinstance(task, dict)
    ]
    task_totals = {
        "tasks": len(task_rows),
        "pass": sum(1 for task in task_rows if task.get("status") == "PASS"),
        "raw_correct": sum(1 for task in task_rows if task.get("raw_correct")),
        "smavg_correct": sum(1 for task in task_rows if task.get("smavg_correct")),
        "routing_pass": sum(1 for task in task_rows if task.get("paths_visible_in_brief")),
        "same_evidence": sum(1 for task in task_rows if task.get("same_evidence")),
        "raw_tokens_estimate": sum(int(task.get("raw_tokens_estimate", 0)) for task in task_rows),
        "smavg_tokens_estimate": sum(int(task.get("smavg_tokens_estimate", 0)) for task in task_rows),
    }
    task_totals["token_reduction_ratio"] = _ratio(
        task_totals["raw_tokens_estimate"],
        task_totals["smavg_tokens_estimate"],
    )
    return {
        "probes": len(results),
        "pass": len(passed),
        "fail": len(results) - len(passed),
        "exact_expansion_pass": len(exact_pass),
        "model_routing_pass": len(routing_pass),
        "model_routing_needs_query": len(results) - len(routing_pass),
        "first_time_useful": len(first_useful),
        "repeated_useful": len(repeated_useful),
        "totals": totals,
        "task_ab": task_totals,
    }


def _render_markdown(report: Dict[str, object]) -> str:
    summary = report["summary"]
    totals = summary["totals"]
    task_ab = summary.get("task_ab", {})
    lines = [
        "# Smavg Codex Workload Gauntlet",
        "",
        f"Date: {report['generated_at']}",
        "",
        "This gauntlet measures whether Smavg helps Codex work, not only whether it compresses.",
        "It checks token reduction, exact expansion, and whether the compact brief exposes",
        "the files an agent must choose before doing the work.",
        "It also runs deterministic A/B evidence tasks: raw full context versus",
        "Smavg brief plus exact expansions.",
        "",
        "## Summary",
        "",
        f"- Probes: {summary['probes']}",
        f"- Exact expansion pass: {summary['exact_expansion_pass']}/{summary['probes']}",
        f"- Model-routing pass: {summary['model_routing_pass']}/{summary['probes']}",
        f"- First-time useful: {summary['first_time_useful']}/{summary['probes']}",
        f"- Repeated useful: {summary['repeated_useful']}/{summary['probes']}",
        f"- Total raw tokens estimate: {totals['raw_tokens_estimate']}",
        f"- Total brief tokens estimate: {totals['brief_tokens_estimate']}",
        f"- Brief-only reduction: {_format_ratio(totals['brief_only_reduction_ratio'])}",
        f"- First-time Smavg tokens estimate: {totals['first_time_smavg_tokens_estimate']}",
        f"- First-time reduction: {_format_ratio(totals['first_time_reduction_ratio'])}",
        f"- Repeated raw tokens estimate: {totals['repeated_raw_tokens_estimate']}",
        f"- Repeated Smavg tokens estimate: {totals['repeated_smavg_tokens_estimate']}",
        f"- Repeated-work reduction: {_format_ratio(totals['repeated_reduction_ratio'])}",
        f"- A/B evidence tasks: {task_ab.get('pass', 0)}/{task_ab.get('tasks', 0)} PASS",
        f"- A/B raw correct: {task_ab.get('raw_correct', 0)}/{task_ab.get('tasks', 0)}",
        f"- A/B Smavg correct: {task_ab.get('smavg_correct', 0)}/{task_ab.get('tasks', 0)}",
        f"- A/B same evidence: {task_ab.get('same_evidence', 0)}/{task_ab.get('tasks', 0)}",
        f"- A/B token reduction: {_format_ratio(task_ab.get('token_reduction_ratio'))}",
        "",
        "## Trust Rule",
        "",
        str(report["trust_rule"]),
        "",
        "## Results",
        "",
    ]
    for item in sorted(report["results"], key=lambda row: natural_key(str(row.get("name", "")))):
        lines.extend(_render_probe(item))
    return "\n".join(lines)


def _render_probe(item: Dict[str, object]) -> List[str]:
    lines = [
        f"### {item.get('name')}",
        "",
        f"- Description: {item.get('description')}",
        f"- Status: `{item.get('status')}`",
        f"- Model routing: `{item.get('model_routing', 'UNKNOWN')}`",
        f"- Source: `{item.get('source') or item.get('workflow')}`",
        f"- Files: {item.get('files', 0)}",
        f"- Raw tokens estimate: {item.get('raw_tokens_estimate', 0)}",
        f"- Brief tokens estimate: {item.get('brief_tokens_estimate', 0)}",
        f"- Brief-only reduction: {_format_ratio(item.get('brief_only_reduction_ratio'))}",
        f"- Required exact tokens: {item.get('required_exact_tokens_estimate', 0)}",
        f"- First-time Smavg tokens: {item.get('first_time_smavg_tokens_estimate', 0)}",
        f"- First-time reduction: {_format_ratio(item.get('first_time_reduction_ratio'))}",
        f"- Repeated-work reduction: {_format_ratio(item.get('repeated_reduction_ratio'))}",
        f"- Applicability: {item.get('applicability', 'unknown')}",
        f"- A/B evidence tasks: {item.get('task_summary', {}).get('pass', 0)}/{item.get('task_summary', {}).get('tasks', 0)} PASS",
        f"- A/B token reduction: {_format_ratio(item.get('task_summary', {}).get('token_reduction_ratio'))}",
        f"- Context: `{item.get('context_markdown')}`",
        "",
        "Required exact files:",
    ]
    for row in item.get("expansions", []):
        marker = "PASS" if row.get("verified") else "FAIL"
        visible = "visible" if row.get("visible_in_context_markdown") else "not visible in brief"
        lines.append(
            f"- `{row.get('path')}`: {marker}, {visible}, "
            f"{row.get('estimated_tokens', 0)} tokens"
        )
    tasks = item.get("tasks", [])
    if tasks:
        lines.extend(["", "A/B evidence tasks:"])
        for task in tasks:
            marker = "PASS" if task.get("status") == "PASS" else "FAIL"
            lines.append(
                f"- `{task.get('name')}`: {marker}, "
                f"raw={task.get('raw_correct')}, smavg={task.get('smavg_correct')}, "
                f"same_evidence={task.get('same_evidence')}, "
                f"reduction={_format_ratio(task.get('token_reduction_ratio'))}"
            )
            snippets = task.get("evidence_snippets", [])
            for snippet in snippets[:3]:
                line = snippet.get("line", "")
                if line:
                    lines.append(f"  - `{snippet.get('term')}`: {line}")
    warnings = item.get("warnings", [])
    if warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in warnings:
            lines.append(f"- {warning}")
    failures = item.get("failures", [])
    if failures:
        lines.append("")
        lines.append("Failures:")
        for failure in failures:
            lines.append(f"- {failure}")
    lines.append("")
    return lines


def _applicability(
    first_ratio: object,
    repeated_ratio: object,
    exact_pass: bool,
    routing_pass: bool,
) -> str:
    if not exact_pass:
        return "not applicable: exact retrieval failed"
    first = float(first_ratio or 0.0)
    repeated = float(repeated_ratio or 0.0)
    if first >= 2.0 and routing_pass:
        return "strong even for one-off tasks"
    if first > 1.0 and routing_pass:
        return "useful for one-off tasks"
    if repeated >= 2.0:
        return "useful for repeated workflows; one-off use needs narrower context"
    return "weak here; read directly or narrow the target"


def _probe_exists(probe: CodexWorkloadProbe) -> bool:
    if probe.workflow is not None:
        return True
    return probe.source is not None and probe.source.expanduser().is_dir()


def _ratio(numerator: int, denominator: int) -> Optional[float]:
    if numerator <= 0 or denominator <= 0:
        return None
    return round(numerator / denominator, 3)


def _format_ratio(value: object) -> str:
    return "n/a" if value is None else f"{value}x"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _slug(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value)
    safe = safe.strip("-._")
    return safe[:100] or "probe"


def _safe_exact_name(relative: str) -> str:
    return _slug(relative.replace("/", "__")) or "exact-file"
