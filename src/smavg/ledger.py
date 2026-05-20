"""Append-only Smavg benefit ledger and task session counter."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .context import estimate_tokens


class LedgerError(RuntimeError):
    """Raised when the benefit ledger cannot be read or written."""


TRUTH_BOUNDARY = (
    "Smavg-visible estimate, not provider billing meter. Hidden system, "
    "developer, tool-schema, retained-history, and provider-side accounting "
    "tokens are not visible to Smavg unless the host exposes them."
)


def default_ledger_path() -> Path:
    return Path.home() / ".smavg" / "ledger" / "events.jsonl"


def default_tasks_dir() -> Path:
    return Path.home() / ".smavg" / "tasks"


def create_event(
    *,
    kind: str,
    label: str,
    surface: str = "cli",
    before: Optional[Dict[str, int]] = None,
    after: Optional[Dict[str, int]] = None,
    saved: Optional[Dict[str, int]] = None,
    ratios: Optional[Dict[str, Optional[float]]] = None,
    verification: Optional[Dict[str, object]] = None,
    quality: Optional[Dict[str, object]] = None,
    artifacts: Optional[Iterable[str]] = None,
    notes: Optional[Iterable[str]] = None,
    truth_boundary: str = TRUTH_BOUNDARY,
    created_at: Optional[str] = None,
) -> Dict[str, object]:
    """Create one canonical Smavg benefit event."""
    before = _clean_ints(before or {})
    after = _clean_ints(after or {})
    inferred_saved = _saved_from(before, after)
    if saved:
        inferred_saved.update(_clean_ints(saved))
    inferred_ratios = _ratios_from(before, after)
    if ratios:
        inferred_ratios.update({str(key): _optional_float(value) for key, value in ratios.items()})
    created_at = created_at or _now()
    return {
        "format": "smavg-benefit-event",
        "version": 1,
        "id": _event_id(kind, label, created_at),
        "created_at": created_at,
        "kind": _slug(kind),
        "label": label,
        "surface": surface,
        "before": before,
        "after": after,
        "saved": inferred_saved,
        "ratios": inferred_ratios,
        "verification": verification or {"status": "reported"},
        "quality": quality or {},
        "artifacts": [str(item) for item in artifacts or []],
        "notes": [str(item) for item in notes or []],
        "truth_boundary": truth_boundary,
    }


def append_event(event: Dict[str, object], ledger_path: Optional[Path] = None) -> Dict[str, object]:
    """Append one canonical event to the local ledger."""
    path = Path(ledger_path or default_ledger_path()).expanduser()
    if event.get("format") != "smavg-benefit-event":
        raise LedgerError("Unsupported ledger event format")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    return event


def load_events(ledger_path: Optional[Path] = None) -> List[Dict[str, object]]:
    path = Path(ledger_path or default_ledger_path()).expanduser()
    if not path.exists():
        return []
    events = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise LedgerError(f"Bad JSON in ledger at line {line_no}: {path}") from exc
            if item.get("format") == "smavg-benefit-event":
                events.append(item)
    return events


def event_from_report(
    report_path: Path,
    *,
    kind: Optional[str] = None,
    label: Optional[str] = None,
    surface: str = "cli",
) -> Dict[str, object]:
    """Create a benefit event from a known Smavg JSON report."""
    path = Path(report_path).expanduser().resolve()
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"Could not read report JSON: {path}") from exc
    if not isinstance(report, dict):
        raise LedgerError(f"Unsupported Smavg report shape: {path}")
    fmt = str(report.get("format", ""))
    if not fmt and _is_workflow_token_summary(report):
        fmt = "smavg-workflow-token-summary"
    chosen_kind = kind or _kind_for_format(fmt)
    chosen_label = label or _label_for_report(path, report, chosen_kind)

    if fmt == "smavg-gate-gauntlet":
        return _event_from_gate_gauntlet(path, report, chosen_kind, chosen_label, surface)
    if fmt == "smavg-codex-workload-gauntlet":
        return _event_from_codex_gauntlet(path, report, chosen_kind, chosen_label, surface)
    if fmt == "smavg-safe-pack-report":
        return _event_from_safe_pack(path, report, chosen_kind, chosen_label, surface)
    if fmt == "smavg-run-receipt":
        return _event_from_receipt(path, report, chosen_kind, chosen_label, surface)
    if fmt == "smavg-preflight":
        return _event_from_preflight(path, report, chosen_kind, chosen_label, surface)
    if fmt == "smavg-context":
        return _event_from_context(path, report, chosen_kind, chosen_label, surface)
    if fmt == "smavg-gauntlet-v1":
        return _event_from_storage_gauntlet(path, report, chosen_kind, chosen_label, surface)
    if fmt == "smavg-gate":
        return _event_from_gate(path, report, chosen_kind, chosen_label, surface)
    if fmt == "smavg-workflow-token-summary":
        return _event_from_workflow_token_summary(path, report, chosen_kind, chosen_label, surface)
    if fmt == "smavg-surface-gauntlet":
        return _event_from_surface_gauntlet(path, report, chosen_kind, chosen_label, surface)
    raise LedgerError(f"Unsupported Smavg report format: {fmt or 'unknown'}")


def import_reports(
    root: Path,
    *,
    ledger_path: Optional[Path] = None,
    surface: str = "cli",
) -> Dict[str, object]:
    """Import supported Smavg reports under root without double-counting components."""
    base = Path(root).expanduser().resolve()
    if not base.exists():
        raise LedgerError(f"Report root does not exist: {base}")
    if base.is_file():
        scanned = [base]
    else:
        scanned = sorted(path for path in base.rglob("*.json") if path.is_file())
    candidates, suppressed = _select_report_candidates(scanned, base)
    existing_events = load_events(ledger_path)
    known_artifacts = _artifact_keys(existing_events)
    imported = []
    skipped_duplicate = []
    skipped_unsupported = []
    failures = []
    for path in candidates:
        try:
            event = event_from_report(path, surface=surface)
        except LedgerError as exc:
            skipped_unsupported.append({"path": str(path), "reason": str(exc)})
            continue
        keys = _artifact_keys([event])
        if keys and keys.intersection(known_artifacts):
            skipped_duplicate.append(str(path))
            continue
        try:
            append_event(event, ledger_path)
        except (OSError, LedgerError) as exc:
            failures.append({"path": str(path), "reason": str(exc)})
            continue
        known_artifacts.update(keys)
        imported.append(event)
    return {
        "format": "smavg-ledger-import",
        "version": 1,
        "root": str(base),
        "ledger_path": str(Path(ledger_path or default_ledger_path()).expanduser()),
        "scanned_json": len(scanned),
        "selected_reports": len(candidates),
        "suppressed_component_reports": len(suppressed),
        "imported": len(imported),
        "skipped_duplicate": len(skipped_duplicate),
        "skipped_unsupported": len(skipped_unsupported),
        "failures": len(failures),
        "imported_events": imported,
        "skipped_duplicate_paths": skipped_duplicate,
        "skipped_unsupported_examples": skipped_unsupported[:20],
        "suppressed_component_examples": [str(path) for path in suppressed[:20]],
        "failure_examples": failures[:20],
        "truth_boundary": (
            "Importer prefers top-level reports over component JSON files so a single "
            "Smavg run is not counted multiple times."
        ),
    }


def ledger_report(
    *,
    ledger_path: Optional[Path] = None,
    period: str = "all",
    now: Optional[datetime] = None,
) -> Dict[str, object]:
    """Aggregate the append-only ledger into X-denomination totals."""
    all_events = load_events(ledger_path)
    events = _filter_period(all_events, period=period, now=now)
    benefit_events = _benefit_events(events)
    categories = _category_cards(benefit_events)
    token_before = sum(_metric(event, "before", "tokens") for event in benefit_events)
    token_after = sum(_metric(event, "after", "tokens") for event in benefit_events)
    repeated_before = sum(_metric(event, "before", "repeated_tokens") for event in benefit_events)
    repeated_after = sum(_metric(event, "after", "repeated_tokens") for event in benefit_events)
    disk_before = sum(_metric(event, "before", "disk_bytes") for event in benefit_events)
    disk_after = sum(_metric(event, "after", "disk_bytes") for event in benefit_events)
    user_input = sum(_metric(event, "after", "visible_user_input_tokens") for event in benefit_events)
    assistant_output = sum(_metric(event, "after", "visible_assistant_output_tokens") for event in benefit_events)
    tool_tokens = sum(_metric(event, "after", "visible_tool_tokens") for event in benefit_events)
    exact_pass, exact_total = _quality_pair(benefit_events, "exact_expansion_pass", "exact_expansion_total")
    evidence_pass, evidence_total = _quality_pair(benefit_events, "evidence_task_pass", "evidence_task_total")
    restore_pass, restore_total = _quality_pair(benefit_events, "restore_pass", "restore_total")
    verify_pass, verify_total = _quality_pair(benefit_events, "verify_pass", "verify_total")
    weak_cases = sum(1 for event in benefit_events if _is_weak_case(event))
    failed = sum(1 for event in events if _is_failed_event(event))
    quarantine_moves = sum(1 for event in benefit_events if _metric(event, "after", "quarantine_moves") > 0)
    deletes = sum(_metric(event, "after", "deletes_performed") for event in benefit_events)
    return {
        "format": "smavg-benefit-ledger-report",
        "version": 1,
        "generated_at": _now(),
        "period": period,
        "event_count": len(events),
        "ledger_path": str(Path(ledger_path or default_ledger_path()).expanduser()),
        "headline": _headline(all_events, now=now),
        "categories": categories,
        "ai_tokens": _before_after_saved(token_before, token_after),
        "repeated_work_tokens": _before_after_saved(repeated_before, repeated_after),
        "storage_disk": _before_after_saved(disk_before, disk_after),
        "visible_session_tokens": {
            "user_input_tokens": user_input,
            "assistant_output_tokens": assistant_output,
            "tool_tokens": tool_tokens,
            "total_visible_tokens": user_input + assistant_output + tool_tokens,
        },
        "cleanup": {
            "quarantine_moves": quarantine_moves,
            "deletes_performed": deletes,
            "truth": "Quarantine moves do not free same-disk space until purged or moved off-disk.",
        },
        "trust": {
            "exact_expansion": {"pass": exact_pass, "total": exact_total},
            "evidence_tasks": {"pass": evidence_pass, "total": evidence_total},
            "restore": {"pass": restore_pass, "total": restore_total},
            "verify": {"pass": verify_pass, "total": verify_total},
            "weak_cases_reported": weak_cases,
            "failures_counted_as_wins": 0,
            "failed_events": failed,
        },
        "truth_boundary": TRUTH_BOUNDARY,
        "events": events,
    }


def render_ledger_markdown(report: Dict[str, object]) -> str:
    headline = report["headline"]
    ai = report["ai_tokens"]
    repeated = report["repeated_work_tokens"]
    storage = report["storage_disk"]
    visible = report["visible_session_tokens"]
    cleanup = report["cleanup"]
    trust = report["trust"]
    lines = [
        f"# Smavg Benefit Ledger: {report['period']}",
        "",
        "Every X-ratio below names the before/after basis. These are Smavg-visible measurements, not a provider billing meter.",
        "",
        "## Headline",
        "",
        f"- Tokens saved today: {headline['tokens_saved_today']}",
        f"- Tokens saved all time: {headline['tokens_saved_all_time']}",
        f"- Repeated-work tokens saved today: {headline['repeated_tokens_saved_today']}",
        f"- Repeated-work tokens saved all time: {headline['repeated_tokens_saved_all_time']}",
        f"- Disk saved today: {headline['disk_bytes_saved_today']} bytes",
        f"- Disk saved all time: {headline['disk_bytes_saved_all_time']} bytes",
        "",
        "## AI Tokens",
        "",
        f"- Before: {ai['before']}",
        f"- After: {ai['after']}",
        f"- Saved: {ai['saved']}",
        f"- Reduction: {_format_ratio(ai['ratio'])}",
        "",
        "## Category Cards",
        "",
    ]
    for category in report.get("categories", []):
        lines.extend(_render_category_card(category))
    lines.extend(
        [
        "## Repeated Workflow Tokens",
        "",
        f"- Before: {repeated['before']}",
        f"- After: {repeated['after']}",
        f"- Saved: {repeated['saved']}",
        f"- Reduction: {_format_ratio(repeated['ratio'])}",
        "",
        "## Storage Disk",
        "",
        f"- Before: {storage['before']} bytes",
        f"- After: {storage['after']} bytes",
        f"- Saved: {storage['saved']} bytes",
        f"- Reduction: {_format_ratio(storage['ratio'])}",
        "",
        "## Visible Session Tokens",
        "",
        f"- User input: {visible['user_input_tokens']}",
        f"- Assistant output: {visible['assistant_output_tokens']}",
        f"- Tool text: {visible['tool_tokens']}",
        f"- Total visible: {visible['total_visible_tokens']}",
        "",
        "## Cleanup",
        "",
        f"- Quarantine moves: {cleanup['quarantine_moves']}",
        f"- Deletes performed by Smavg: {cleanup['deletes_performed']}",
        f"- Truth: {cleanup['truth']}",
        "",
        "## Trust",
        "",
        f"- Exact expansion: {trust['exact_expansion']['pass']}/{trust['exact_expansion']['total']}",
        f"- Evidence tasks: {trust['evidence_tasks']['pass']}/{trust['evidence_tasks']['total']}",
        f"- Restore: {trust['restore']['pass']}/{trust['restore']['total']}",
        f"- Verify: {trust['verify']['pass']}/{trust['verify']['total']}",
        f"- Weak cases reported: {trust['weak_cases_reported']}",
        f"- Failures counted as wins: {trust['failures_counted_as_wins']}",
        "",
        "## Truth Boundary",
        "",
        str(report["truth_boundary"]),
        "",
        ]
    )
    return "\n".join(lines)


def start_task(
    *,
    label: str,
    surface: str = "codex",
    tasks_dir: Optional[Path] = None,
    task_id: Optional[str] = None,
) -> Dict[str, object]:
    if not label.strip():
        raise LedgerError("Task label cannot be empty")
    task_id = task_id or _event_id("task", label, _now())
    task = {
        "format": "smavg-task-session",
        "version": 1,
        "id": task_id,
        "label": label,
        "surface": surface,
        "started_at": _now(),
        "ended_at": None,
        "messages": [],
        "smavg_events": [],
        "truth_boundary": TRUTH_BOUNDARY,
    }
    _write_task(task, tasks_dir)
    _write_current_task(task["id"], tasks_dir)
    return task


def load_task(task_id: Optional[str] = None, tasks_dir: Optional[Path] = None) -> Dict[str, object]:
    if task_id is None:
        task_id = _read_current_task(tasks_dir)
    path = _task_path(str(task_id), tasks_dir)
    try:
        task = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"Could not read task session: {path}") from exc
    if task.get("format") != "smavg-task-session":
        raise LedgerError("Unsupported task session format")
    return task


def add_task_text(
    *,
    task_id: Optional[str],
    role: str,
    text: str,
    tasks_dir: Optional[Path] = None,
    label: Optional[str] = None,
) -> Dict[str, object]:
    task = load_task(task_id, tasks_dir)
    role = _validate_role(role)
    message = {
        "role": role,
        "label": label or role,
        "tokens_estimate": estimate_tokens(text),
        "characters": len(text),
        "recorded_at": _now(),
    }
    task["messages"].append(message)
    _write_task(task, tasks_dir)
    return task


def add_task_report(
    *,
    task_id: Optional[str],
    report_path: Path,
    kind: Optional[str] = None,
    label: Optional[str] = None,
    surface: str = "cli",
    tasks_dir: Optional[Path] = None,
) -> Dict[str, object]:
    task = load_task(task_id, tasks_dir)
    event = event_from_report(report_path, kind=kind, label=label, surface=surface)
    task["smavg_events"].append(event)
    _write_task(task, tasks_dir)
    return task


def end_task(
    *,
    task_id: Optional[str],
    tasks_dir: Optional[Path] = None,
    ledger_path: Optional[Path] = None,
    record_ledger: bool = True,
    artifacts: Optional[Iterable[str]] = None,
    notes: Optional[Iterable[str]] = None,
) -> Dict[str, object]:
    task = load_task(task_id, tasks_dir)
    task["ended_at"] = _now()
    summary = summarize_task(task)
    task["summary"] = summary
    event = create_event(
        kind="task_session",
        label=str(task.get("label", "")),
        surface=str(task.get("surface", "codex")),
        before={
            "tokens": summary["smavg_raw_context_tokens"],
            "repeated_tokens": summary["smavg_repeated_raw_tokens"],
        },
        after={
            "tokens": summary["smavg_supplied_tokens"],
            "repeated_tokens": summary["smavg_repeated_supplied_tokens"],
            "visible_user_input_tokens": summary["visible_user_input_tokens"],
            "visible_assistant_output_tokens": summary["visible_assistant_output_tokens"],
            "visible_tool_tokens": summary["visible_tool_tokens"],
        },
        verification={"status": "reported", "source": "task-session"},
        quality=summary.get("quality", {}),
        artifacts=artifacts or [],
        notes=[
            "Visible message tokens are user-recorded estimates, not automatic Codex provider accounting.",
            *(notes or []),
        ],
    )
    task["ledger_event"] = event
    _write_task(task, tasks_dir)
    if record_ledger:
        append_event(event, ledger_path)
    return task


def summarize_task(task: Dict[str, object]) -> Dict[str, object]:
    messages = [item for item in task.get("messages", []) if isinstance(item, dict)]
    events = [item for item in task.get("smavg_events", []) if isinstance(item, dict)]
    user_tokens = sum(int(item.get("tokens_estimate", 0)) for item in messages if item.get("role") == "user")
    assistant_tokens = sum(int(item.get("tokens_estimate", 0)) for item in messages if item.get("role") == "assistant")
    tool_tokens = sum(int(item.get("tokens_estimate", 0)) for item in messages if str(item.get("role", "")).startswith("tool"))
    raw = sum(_metric(event, "before", "tokens") for event in events)
    supplied = sum(_metric(event, "after", "tokens") for event in events)
    repeated_raw = sum(_metric(event, "before", "repeated_tokens") for event in events)
    repeated_supplied = sum(_metric(event, "after", "repeated_tokens") for event in events)
    exact_pass, exact_total = _quality_pair(events, "exact_expansion_pass", "exact_expansion_total")
    evidence_pass, evidence_total = _quality_pair(events, "evidence_task_pass", "evidence_task_total")
    return {
        "messages": len(messages),
        "visible_user_input_tokens": user_tokens,
        "visible_assistant_output_tokens": assistant_tokens,
        "visible_tool_tokens": tool_tokens,
        "visible_total_tokens": user_tokens + assistant_tokens + tool_tokens,
        "smavg_events": len(events),
        "smavg_raw_context_tokens": raw,
        "smavg_supplied_tokens": supplied,
        "smavg_saved_tokens": max(0, raw - supplied),
        "smavg_reduction_ratio": _ratio(raw, supplied),
        "smavg_repeated_raw_tokens": repeated_raw,
        "smavg_repeated_supplied_tokens": repeated_supplied,
        "smavg_repeated_reduction_ratio": _ratio(repeated_raw, repeated_supplied),
        "quality": {
            "exact_expansion_pass": exact_pass,
            "exact_expansion_total": exact_total,
            "evidence_task_pass": evidence_pass,
            "evidence_task_total": evidence_total,
        },
        "truth_boundary": TRUTH_BOUNDARY,
    }


def render_task_markdown(task: Dict[str, object]) -> str:
    summary = task.get("summary") or summarize_task(task)
    lines = [
        f"# Smavg Task Session: {task.get('label')}",
        "",
        f"- Task id: `{task.get('id')}`",
        f"- Surface: `{task.get('surface')}`",
        f"- Started: `{task.get('started_at')}`",
        f"- Ended: `{task.get('ended_at')}`",
        "",
        "## Visible Message Tokens",
        "",
        f"- User input: {summary['visible_user_input_tokens']}",
        f"- Assistant output: {summary['visible_assistant_output_tokens']}",
        f"- Tool text: {summary['visible_tool_tokens']}",
        f"- Total visible: {summary['visible_total_tokens']}",
        "",
        "## Smavg Context Rescue",
        "",
        f"- Before: {summary['smavg_raw_context_tokens']}",
        f"- After: {summary['smavg_supplied_tokens']}",
        f"- Saved: {summary['smavg_saved_tokens']}",
        f"- Reduction: {_format_ratio(summary['smavg_reduction_ratio'])}",
        "",
        "## Repeated Work",
        "",
        f"- Before: {summary['smavg_repeated_raw_tokens']}",
        f"- After: {summary['smavg_repeated_supplied_tokens']}",
        f"- Reduction: {_format_ratio(summary['smavg_repeated_reduction_ratio'])}",
        "",
        "## Truth Boundary",
        "",
        str(summary["truth_boundary"]),
        "",
    ]
    return "\n".join(lines)


def _event_from_gate_gauntlet(path: Path, report: Dict[str, object], kind: str, label: str, surface: str) -> Dict[str, object]:
    summary = report.get("summary", {})
    return create_event(
        kind=kind,
        label=label,
        surface=surface,
        before={
            "tokens": int(summary.get("raw_tokens_estimate", 0)),
            "repeated_tokens": int(summary.get("repeated_raw_tokens_estimate", 0)),
        },
        after={
            "tokens": int(summary.get("gate_receipt_tokens_estimate", 0)),
            "repeated_tokens": int(summary.get("repeated_gate_tokens_estimate", 0)),
        },
        ratios={
            "tokens": summary.get("receipt_reduction_ratio"),
            "repeated_tokens": summary.get("repeated_reduction_ratio"),
        },
        verification={"status": "verified" if int(summary.get("fail", 0)) == 0 else "failed"},
        quality={
            "gate_integrity_pass": int(summary.get("gate_integrity_pass", 0)),
            "receipt_integrity_pass": int(summary.get("receipt_integrity_pass", 0)),
            "exact_expansion_pass": int(summary.get("exact_expansion_pass", 0)),
            "exact_expansion_total": int(summary.get("probes", 0)),
            "model_routing_pass": int(summary.get("model_routing_pass", 0)),
            "evidence_task_pass": int(summary.get("evidence_task_pass", 0)),
            "evidence_task_total": int(summary.get("evidence_tasks", 0)),
            "same_evidence": int(summary.get("same_evidence", 0)),
        },
        artifacts=[str(path)],
        created_at=_report_created_at(path, report),
    )


def _event_from_codex_gauntlet(path: Path, report: Dict[str, object], kind: str, label: str, surface: str) -> Dict[str, object]:
    summary = report.get("summary", {})
    totals = summary.get("totals", {})
    task_ab = summary.get("task_ab", {})
    after_tokens = int(totals.get("first_time_smavg_tokens_estimate", totals.get("brief_tokens_estimate", 0)))
    return create_event(
        kind=kind,
        label=label,
        surface=surface,
        before={
            "tokens": int(totals.get("raw_tokens_estimate", 0)),
            "repeated_tokens": int(totals.get("repeated_raw_tokens_estimate", 0)),
        },
        after={
            "tokens": after_tokens,
            "repeated_tokens": int(totals.get("repeated_smavg_tokens_estimate", after_tokens)),
        },
        ratios={
            "tokens": totals.get("first_time_reduction_ratio"),
            "repeated_tokens": totals.get("repeated_reduction_ratio"),
            "brief_only_tokens": totals.get("brief_only_reduction_ratio"),
            "task_evidence_tokens": task_ab.get("token_reduction_ratio"),
        },
        verification={"status": "verified" if int(summary.get("fail", 0)) == 0 else "failed"},
        quality={
            "exact_expansion_pass": int(summary.get("exact_expansion_pass", 0)),
            "exact_expansion_total": int(summary.get("probes", 0)),
            "model_routing_pass": int(summary.get("model_routing_pass", 0)),
            "evidence_task_pass": int(task_ab.get("pass", 0)),
            "evidence_task_total": int(task_ab.get("tasks", 0)),
            "same_evidence": int(task_ab.get("same_evidence", 0)),
        },
        artifacts=[str(path)],
        created_at=_report_created_at(path, report),
    )


def _event_from_safe_pack(path: Path, report: Dict[str, object], kind: str, label: str, surface: str) -> Dict[str, object]:
    cleanup = report.get("cleanup_projection", {})
    purge = cleanup.get("purge_projection", {})
    tokens = cleanup.get("token_projection", {})
    archive_verify = bool(report.get("archive_verify", {}).get("pass", False))
    restore_compare = bool(report.get("restore_compare", {}).get("pass", False))
    return create_event(
        kind=kind,
        label=label,
        surface=surface,
        before={
            "tokens": int(tokens.get("raw_source_tokens_estimate", 0)),
            "disk_bytes": int(cleanup.get("source_disk_bytes", 0)),
            "apparent_bytes": int(cleanup.get("source_apparent_bytes", 0)),
        },
        after={
            "tokens": int(tokens.get("smavg_brief_tokens_estimate", 0)),
            "disk_bytes": int(cleanup.get("archive_disk_bytes", 0)),
            "apparent_bytes": int(cleanup.get("archive_apparent_bytes", 0)),
            "quarantine_moves": 1 if report.get("source_moved_to_quarantine") else 0,
            "deletes_performed": 1 if report.get("delete_performed") else 0,
        },
        saved={
            "disk_bytes": int(purge.get("net_disk_bytes_saved_after_purge_and_archive_kept", 0)),
            "tokens": int(tokens.get("tokens_saved_when_agent_uses_smavg_brief_instead_of_raw_source", 0)),
        },
        ratios={
            "tokens": tokens.get("token_reduction_ratio"),
            "disk_bytes": purge.get("net_disk_reduction_ratio_after_purge"),
        },
        verification={"status": "verified" if archive_verify and restore_compare else "failed"},
        quality={
            "verify_pass": 1 if archive_verify else 0,
            "verify_total": 1,
            "restore_pass": 1 if restore_compare else 0,
            "restore_total": 1,
            "importance_rating": report.get("importance_brief", {}).get("rating", "unknown"),
            "purge_risk": report.get("importance_brief", {}).get("purge_risk", "unknown"),
        },
        artifacts=[str(path), str(report.get("archive", ""))],
        notes=["Disk freed now is zero while quarantine remains on the same disk."],
        created_at=_report_created_at(path, report),
    )


def _event_from_receipt(path: Path, report: Dict[str, object], kind: str, label: str, surface: str) -> Dict[str, object]:
    raw = report.get("raw_material", {})
    supplied = report.get("supplied_to_agent", {})
    verified = bool(report.get("verification", {}).get("exact_expansions_verified", False))
    return create_event(
        kind=kind,
        label=label,
        surface=surface,
        before={"tokens": int(raw.get("raw_tokens_estimate", 0)), "bytes": int(raw.get("logical_bytes", 0))},
        after={"tokens": int(supplied.get("total_tokens_estimate", 0))},
        ratios={"tokens": supplied.get("reduction_ratio")},
        verification={"status": "verified" if verified else "reported"},
        quality={
            "exact_expansion_pass": len(supplied.get("exact_expansions", [])),
            "exact_expansion_total": len(supplied.get("exact_expansions", [])),
        },
        artifacts=[str(path), str(report.get("context_json", ""))],
        created_at=_report_created_at(path, report),
    )


def _event_from_preflight(path: Path, report: Dict[str, object], kind: str, label: str, surface: str) -> Dict[str, object]:
    return create_event(
        kind=kind,
        label=label,
        surface=surface,
        before={"tokens": int(report.get("raw_tokens_estimate", 0)), "bytes": int(report.get("logical_bytes", 0))},
        after={"tokens": int(report.get("brief_tokens_estimate", 0))},
        ratios={"tokens": report.get("token_reduction_ratio")},
        verification={"status": "reported"},
        quality={
            "assessment": report.get("assessment", {}).get("status", "unknown"),
            "families_detected": int(report.get("families_detected", 0)),
        },
        artifacts=[str(path), str(report.get("context_json", "")), str(report.get("receipt_json", ""))],
        created_at=_report_created_at(path, report),
    )


def _event_from_context(path: Path, report: Dict[str, object], kind: str, label: str, surface: str) -> Dict[str, object]:
    assessment = report.get("assessment", {})
    return create_event(
        kind=kind,
        label=label,
        surface=surface,
        before={"tokens": int(report.get("original_tokens_estimate", 0)), "bytes": int(report.get("logical_bytes", 0))},
        after={"tokens": int(report.get("brief_tokens_estimate", 0))},
        ratios={"tokens": report.get("token_reduction_ratio")},
        verification={"status": "reported"},
        quality={
            "assessment": assessment.get("status", "unknown"),
            "families_detected": int(report.get("families_detected", 0)),
            "weak_case": assessment.get("status") in {"weak", "no_text"},
        },
        artifacts=[str(path)],
        created_at=_report_created_at(path, report),
    )


def _event_from_storage_gauntlet(path: Path, report: Dict[str, object], kind: str, label: str, surface: str) -> Dict[str, object]:
    rows = [item for item in report.get("results", []) if isinstance(item, dict) and item.get("result_counted")]
    before_disk = sum(int(item.get("original_disk_bytes", 0)) for item in rows)
    after_disk = sum(int(item.get("smavg_archive_bytes", 0)) for item in rows)
    before_bytes = sum(int(item.get("original_apparent_bytes", 0)) for item in rows)
    after_bytes = after_disk
    summary = report.get("summary", {})
    counted = int(summary.get("counted", 0))
    corpus_total = int(summary.get("corpora", counted))
    restore_pass = int(summary.get("restore_pass", 0))
    verify_pass = int(summary.get("verify_pass", 0))
    restore_total = corpus_total if restore_pass > counted else counted
    verify_total = corpus_total if verify_pass > counted else counted
    return create_event(
        kind=kind,
        label=label,
        surface=surface,
        before={"disk_bytes": before_disk, "apparent_bytes": before_bytes},
        after={"disk_bytes": after_disk, "apparent_bytes": after_bytes},
        verification={"status": "verified" if int(summary.get("not_counted", 0)) == 0 else "reported"},
        quality={
            "verify_pass": verify_pass,
            "verify_total": verify_total,
            "restore_pass": restore_pass,
            "restore_total": restore_total,
            "tree_fidelity_pass": int(summary.get("tree_fidelity_pass", 0)),
            "beats_best_baseline": int(summary.get("beats_best_baseline", 0)),
        },
        artifacts=[str(path)],
        created_at=_report_created_at(path, report),
    )


def _event_from_gate(path: Path, report: Dict[str, object], kind: str, label: str, surface: str) -> Dict[str, object]:
    measurement = report.get("measurement", {})
    return create_event(
        kind=kind,
        label=label,
        surface=surface,
        before={"tokens": int(measurement.get("raw_tokens_estimate", 0))},
        after={"tokens": int(measurement.get("current_smavg_supplied_tokens_estimate", 0))},
        ratios={"tokens": measurement.get("token_reduction_ratio")},
        verification={"status": "verified"},
        quality={
            "assessment": measurement.get("assessment", {}).get("status", "unknown")
            if isinstance(measurement.get("assessment", {}), dict)
            else "unknown",
            "full_raw_source_supplied": bool(measurement.get("full_raw_source_supplied_by_smavg", False)),
        },
        artifacts=[str(path), str(report.get("files", {}).get("context_json", "")) if isinstance(report.get("files"), dict) else ""],
        created_at=_report_created_at(path, report),
    )


def _event_from_workflow_token_summary(
    path: Path,
    report: Dict[str, object],
    kind: str,
    label: str,
    surface: str,
) -> Dict[str, object]:
    repeated_before = int(report.get("workflow_raw_tokens_three_repeated_jobs", 0))
    repeated_after = int(report.get("smavg_session_setup_tokens", 0))
    return create_event(
        kind=kind,
        label=label,
        surface=surface,
        before={
            "tokens": repeated_before,
            "repeated_tokens": repeated_before,
            "end_to_end_tokens": int(report.get("without_smavg_repeated_setup_plus_pages", 0)),
        },
        after={
            "tokens": repeated_after,
            "repeated_tokens": repeated_after,
            "end_to_end_tokens": int(report.get("with_smavg_session_setup_plus_pages", 0)),
        },
        ratios={
            "tokens": report.get("stable_setup_savings_repeated_jobs_ratio"),
            "repeated_tokens": report.get("stable_setup_savings_repeated_jobs_ratio"),
            "end_to_end_tokens": report.get("end_to_end_with_common_pages_ratio_repeated_setup"),
        },
        verification={"status": "verified" if report.get("exact_paths") else "reported"},
        quality={
            "exact_expansion_pass": len(report.get("exact_paths", [])),
            "exact_expansion_total": len(report.get("exact_paths", [])),
            "jobs": len(report.get("jobs", [])),
        },
        artifacts=[str(path)],
        notes=[
            "Workflow token-use summary counts repeated setup reduction, not live page tokens removed.",
        ],
        created_at=_report_created_at(path, report),
    )


def _event_from_surface_gauntlet(
    path: Path,
    report: Dict[str, object],
    kind: str,
    label: str,
    surface: str,
) -> Dict[str, object]:
    summary = report.get("summary", {})
    return create_event(
        kind=kind,
        label=label,
        surface=surface,
        before={
            "tokens": int(summary.get("raw_tokens_estimate", 0)),
            "repeated_tokens": int(summary.get("repeated_raw_tokens_estimate", 0)),
        },
        after={
            "tokens": int(summary.get("smavg_supplied_tokens_estimate", 0)),
            "repeated_tokens": int(summary.get("repeated_smavg_tokens_estimate", 0)),
        },
        ratios={
            "tokens": summary.get("first_time_reduction_ratio"),
            "repeated_tokens": summary.get("repeated_reduction_ratio"),
        },
        verification={"status": "verified" if int(summary.get("failed_groups", 0)) == 0 else "reported"},
        quality={
            "exact_expansion_pass": int(summary.get("exact_expansion_pass", 0)),
            "exact_expansion_total": int(summary.get("exact_expansion_total", 0)),
            "surface_context_groups": int(summary.get("context_groups", 0)),
            "surface_useful_groups": int(summary.get("useful_groups", 0)),
            "surface_weak_groups": int(summary.get("weak_groups", 0)),
            "configured_unverified_surfaces": int(summary.get("configured_unverified_surfaces", 0)),
            "weak_case": int(summary.get("useful_groups", 0)) == 0,
        },
        artifacts=[str(path), str(report.get("registry_json", ""))],
        notes=[
            "Surface gauntlet covers local skills, plugins, workflows, memories, and sanitized MCP/config summaries.",
            "Configured MCP/app surfaces are inventory-only unless the host exposes a callable local tool.",
        ],
        created_at=_report_created_at(path, report),
    )


def _headline(events: List[Dict[str, object]], *, now: Optional[datetime]) -> Dict[str, object]:
    buckets = {}
    benefit_events = _benefit_events(events)
    for period, label in (
        ("day", "today"),
        ("week", "week"),
        ("month", "month"),
        ("year", "year"),
        ("all", "all_time"),
    ):
        selected = _filter_period(benefit_events, period=period, now=now)
        buckets[label] = {
            "tokens_saved": sum(_metric(event, "saved", "tokens") for event in selected),
            "repeated_tokens_saved": sum(_metric(event, "saved", "repeated_tokens") for event in selected),
            "disk_bytes_saved": sum(_metric(event, "saved", "disk_bytes") for event in selected),
            "events": len(selected),
        }
    return {
        "tokens_saved_today": buckets["today"]["tokens_saved"],
        "tokens_saved_all_time": buckets["all_time"]["tokens_saved"],
        "repeated_tokens_saved_today": buckets["today"]["repeated_tokens_saved"],
        "repeated_tokens_saved_all_time": buckets["all_time"]["repeated_tokens_saved"],
        "disk_bytes_saved_today": buckets["today"]["disk_bytes_saved"],
        "disk_bytes_saved_all_time": buckets["all_time"]["disk_bytes_saved"],
        "buckets": buckets,
        "truth": TRUTH_BOUNDARY,
    }


def _select_report_candidates(paths: List[Path], root: Path) -> tuple[List[Path], List[Path]]:
    supported = {}
    for path in paths:
        fmt = _report_format(path)
        if fmt is not None:
            supported[path.resolve()] = fmt
    candidates = []
    suppressed = []
    for raw_path in sorted(supported):
        path = raw_path.resolve()
        if _has_summary_ancestor(path, root, supported):
            suppressed.append(path)
            continue
        if _has_higher_priority_sibling(path, supported):
            suppressed.append(path)
            continue
        candidates.append(path)
    return candidates, suppressed


def _report_format(path: Path) -> Optional[str]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(report, dict):
        return None
    fmt = str(report.get("format", ""))
    if fmt in _supported_report_formats():
        return fmt
    if not fmt and _is_workflow_token_summary(report):
        return "smavg-workflow-token-summary"
    return None


def _supported_report_formats() -> set[str]:
    return {
        "smavg-gate-gauntlet",
        "smavg-codex-workload-gauntlet",
        "smavg-safe-pack-report",
        "smavg-run-receipt",
        "smavg-preflight",
        "smavg-context",
        "smavg-gauntlet-v1",
        "smavg-gate",
        "smavg-workflow-token-summary",
        "smavg-surface-gauntlet",
    }


def _has_summary_ancestor(path: Path, root: Path, supported: Dict[Path, str]) -> bool:
    root = root.resolve()
    if root.is_file():
        return False
    summaries = {
        "smavg-gate-gauntlet",
        "smavg-codex-workload-gauntlet",
        "smavg-safe-pack-report",
        "smavg-gauntlet-v1",
        "smavg-surface-gauntlet",
    }
    for ancestor in path.parents:
        if ancestor == path.parent:
            continue
        if ancestor == root.parent:
            break
        if ancestor == path:
            continue
        for candidate in (ancestor / "results.json", ancestor / "report.json"):
            if candidate.resolve() != path and supported.get(candidate.resolve()) in summaries:
                return True
        if ancestor == root:
            break
    return False


def _has_higher_priority_sibling(path: Path, supported: Dict[Path, str]) -> bool:
    priority = {
        "smavg-gate-gauntlet": 100,
        "smavg-codex-workload-gauntlet": 100,
        "smavg-safe-pack-report": 100,
        "smavg-gauntlet-v1": 100,
        "smavg-surface-gauntlet": 100,
        "smavg-workflow-token-summary": 90,
        "smavg-gate": 80,
        "smavg-run-receipt": 70,
        "smavg-preflight": 60,
        "smavg-context": 50,
    }
    current = priority.get(supported[path], 0)
    for sibling, fmt in supported.items():
        if sibling == path or sibling.parent != path.parent:
            continue
        if priority.get(fmt, 0) > current:
            return True
    return False


def _artifact_keys(events: Iterable[Dict[str, object]]) -> set[str]:
    output = set()
    for event in events:
        artifacts = event.get("artifacts", [])
        if not isinstance(artifacts, list):
            continue
        for item in artifacts:
            text = str(item)
            if not text:
                continue
            output.add(str(Path(text).expanduser().resolve(strict=False)))
    return output


def _report_created_at(path: Path, report: Dict[str, object]) -> str:
    for key in ("generated_at", "created_at", "completed_at", "finished_at", "started_at"):
        value = report.get(key)
        if isinstance(value, str) and _parse_time(value) is not None:
            return _parse_time(value).isoformat()  # type: ignore[union-attr]
    match = re.search(r"(20\d{2})-(\d{2})-(\d{2})", str(path))
    if match:
        year, month, day = (int(part) for part in match.groups())
        return datetime(year, month, day, tzinfo=timezone.utc).isoformat()
    return _now()


def _is_workflow_token_summary(report: Dict[str, object]) -> bool:
    return "workflow_raw_tokens_three_repeated_jobs" in report and "smavg_session_setup_tokens" in report


def _category_cards(events: List[Dict[str, object]]) -> List[Dict[str, object]]:
    definitions = [
        (
            "storage",
            "Storage",
            ("storage_gauntlet", "storage_archive", "pack", "archive"),
            "Disk/archive reduction. Exact restore and verification must stay visible.",
            ("disk_bytes", "apparent_bytes"),
        ),
        (
            "cleanup",
            "Cleanup / Quarantine",
            ("cleanup_quarantine", "safe_pack"),
            "Active-path cleanup and purge projection. Quarantine is not deletion.",
            ("disk_bytes", "tokens"),
        ),
        (
            "ai_context",
            "AI Context",
            ("context", "preflight", "run_receipt"),
            "Raw source tokens avoided by using a Smavg brief and exact expansion.",
            ("tokens",),
        ),
        (
            "agent_workflow",
            "Agent Workflow",
            ("gate", "gate_gauntlet", "codex_workload_gauntlet", "workflow_context"),
            "Repeated setup/workflow tokens avoided for agent work.",
            ("tokens", "repeated_tokens"),
        ),
        (
            "task_session",
            "Task Session Counter",
            ("task_session",),
            "Visible user/assistant/tool estimates for a task. Provider meter remains private.",
            ("tokens", "repeated_tokens"),
        ),
        (
            "mcp_skill_plugin",
            "MCP / Skill / Plugin Usage",
            ("mcp_call", "skill", "plugin", "workflow_context", "surface_gauntlet"),
            "Thin integration surfaces over the same verified Smavg core.",
            ("tokens",),
        ),
        (
            "weak_or_no_benefit",
            "Weak / No-Benefit Cases",
            (),
            "Honest weak cases are reported and never counted as wins.",
            ("tokens", "disk_bytes"),
        ),
    ]
    cards = []
    for category_id, title, kinds, truth, metrics in definitions:
        if category_id == "weak_or_no_benefit":
            selected = [event for event in events if _is_weak_case(event)]
        else:
            selected = [event for event in events if str(event.get("kind")) in set(kinds)]
        cards.append(_category_card(category_id, title, selected, truth, metrics))
    return cards


def _category_card(
    category_id: str,
    title: str,
    events: List[Dict[str, object]],
    truth: str,
    metrics: Iterable[str],
) -> Dict[str, object]:
    reductions = {
        metric: _before_after_saved(
            sum(_metric(event, "before", metric) for event in events),
            sum(_metric(event, "after", metric) for event in events),
        )
        for metric in metrics
    }
    exact_pass, exact_total = _quality_pair(events, "exact_expansion_pass", "exact_expansion_total")
    evidence_pass, evidence_total = _quality_pair(events, "evidence_task_pass", "evidence_task_total")
    restore_pass, restore_total = _quality_pair(events, "restore_pass", "restore_total")
    verify_pass, verify_total = _quality_pair(events, "verify_pass", "verify_total")
    weak_cases = sum(1 for event in events if _is_weak_case(event))
    failed = sum(1 for event in events if str(event.get("verification", {}).get("status")) == "failed")
    best = _best_events(events)
    return {
        "id": category_id,
        "title": title,
        "event_count": len(events),
        "reductions": reductions,
        "trust": {
            "exact_expansion": {"pass": exact_pass, "total": exact_total},
            "evidence_tasks": {"pass": evidence_pass, "total": evidence_total},
            "restore": {"pass": restore_pass, "total": restore_total},
            "verify": {"pass": verify_pass, "total": verify_total},
            "weak_cases": weak_cases,
            "failed_events": failed,
        },
        "best_events": best,
        "truth": truth,
    }


def _best_events(events: List[Dict[str, object]], limit: int = 3) -> List[Dict[str, object]]:
    rows = []
    for event in events:
        ratios = event.get("ratios", {})
        if not isinstance(ratios, dict):
            continue
        best_ratio = None
        best_metric = ""
        for key, value in ratios.items():
            numeric = _optional_float(value)
            if numeric is None:
                continue
            if best_ratio is None or numeric > best_ratio:
                best_ratio = numeric
                best_metric = str(key)
        if best_ratio is None:
            continue
        rows.append(
            {
                "label": str(event.get("label", "")),
                "kind": str(event.get("kind", "")),
                "metric": best_metric,
                "ratio": best_ratio,
            }
        )
    rows.sort(key=lambda item: float(item["ratio"]), reverse=True)
    return rows[:limit]


def _render_category_card(category: Dict[str, object]) -> List[str]:
    lines = [
        f"### {category['title']}",
        "",
        f"- Events: {category['event_count']}",
        f"- Truth: {category['truth']}",
    ]
    reductions = category.get("reductions", {})
    if isinstance(reductions, dict):
        for metric, values in reductions.items():
            if not isinstance(values, dict):
                continue
            lines.append(
                f"- {metric}: {values.get('before', 0)} -> {values.get('after', 0)} "
                f"(saved {values.get('saved', 0)}, {_format_ratio(values.get('ratio'))})"
            )
    trust = category.get("trust", {})
    if isinstance(trust, dict):
        exact = trust.get("exact_expansion", {})
        evidence = trust.get("evidence_tasks", {})
        restore = trust.get("restore", {})
        verify = trust.get("verify", {})
        lines.extend(
            [
                f"- Exact expansion: {exact.get('pass', 0)}/{exact.get('total', 0)}",
                f"- Evidence tasks: {evidence.get('pass', 0)}/{evidence.get('total', 0)}",
                f"- Restore: {restore.get('pass', 0)}/{restore.get('total', 0)}",
                f"- Verify: {verify.get('pass', 0)}/{verify.get('total', 0)}",
                f"- Weak cases: {trust.get('weak_cases', 0)}",
                f"- Failed events: {trust.get('failed_events', 0)}",
            ]
        )
    best = category.get("best_events", [])
    if best:
        lines.append("- Best events:")
        for item in best:
            lines.append(
                f"  - `{item.get('label')}`: {item.get('ratio')}x "
                f"on `{item.get('metric')}` ({item.get('kind')})"
            )
    lines.append("")
    return lines


def _write_task(task: Dict[str, object], tasks_dir: Optional[Path]) -> None:
    path = _task_path(str(task["id"]), tasks_dir)
    _write_json_atomic(path, task)


def _task_path(task_id: str, tasks_dir: Optional[Path]) -> Path:
    return Path(tasks_dir or default_tasks_dir()).expanduser() / f"{_slug(task_id)}.json"


def _write_current_task(task_id: str, tasks_dir: Optional[Path]) -> None:
    base = Path(tasks_dir or default_tasks_dir()).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(base / "current", task_id + "\n")


def _read_current_task(tasks_dir: Optional[Path]) -> str:
    path = Path(tasks_dir or default_tasks_dir()).expanduser() / "current"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise LedgerError("No current Smavg task session. Use `smavg task start`.") from exc
    if not value:
        raise LedgerError("Current Smavg task session is empty")
    return value


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


def _before_after_saved(before: int, after: int) -> Dict[str, object]:
    return {"before": before, "after": after, "saved": max(0, before - after), "ratio": _ratio(before, after)}


def _saved_from(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, int]:
    keys = set(before) | set(after)
    return {key: max(0, int(before.get(key, 0)) - int(after.get(key, 0))) for key in keys}


def _ratios_from(before: Dict[str, int], after: Dict[str, int]) -> Dict[str, Optional[float]]:
    keys = set(before) & set(after)
    return {key: _ratio(int(before.get(key, 0)), int(after.get(key, 0))) for key in keys if int(after.get(key, 0)) > 0}


def _ratio(before: int, after: int) -> Optional[float]:
    return round(before / after, 3) if before and after else None


def _format_ratio(value: object) -> str:
    return "n/a" if value is None else f"{value}x"


def _metric(event: Dict[str, object], section: str, key: str) -> int:
    value = event.get(section, {})
    if not isinstance(value, dict):
        return 0
    try:
        return int(value.get(key, 0))
    except (TypeError, ValueError):
        return 0


def _quality_pair(events: List[Dict[str, object]], pass_key: str, total_key: str) -> tuple[int, int]:
    passed = 0
    total = 0
    for event in events:
        quality = event.get("quality", {})
        if not isinstance(quality, dict):
            continue
        passed += _safe_int(quality.get(pass_key, 0))
        total += _safe_int(quality.get(total_key, 0))
    return passed, total


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _clean_ints(values: Dict[str, object]) -> Dict[str, int]:
    return {str(key): _safe_int(value) for key, value in values.items() if value is not None}


def _optional_float(value: object) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _filter_period(events: List[Dict[str, object]], *, period: str, now: Optional[datetime]) -> List[Dict[str, object]]:
    period = period.lower()
    if period == "all":
        return events
    now = now or datetime.now().astimezone()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    output = []
    for event in events:
        created = _parse_time(str(event.get("created_at", "")))
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        created = created.astimezone(now.tzinfo)
        if period == "day" and created.date() == now.date():
            output.append(event)
        elif period == "week" and created.isocalendar()[:2] == now.isocalendar()[:2]:
            output.append(event)
        elif period == "month" and created.year == now.year and created.month == now.month:
            output.append(event)
        elif period == "year" and created.year == now.year:
            output.append(event)
    return output


def _benefit_events(events: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return [event for event in events if not _is_failed_event(event)]


def _is_failed_event(event: Dict[str, object]) -> bool:
    return str(event.get("verification", {}).get("status", "")).lower() == "failed"


def _parse_time(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_weak_case(event: Dict[str, object]) -> bool:
    quality = event.get("quality", {})
    if not isinstance(quality, dict):
        return False
    return quality.get("weak_case") is True or quality.get("assessment") in {"weak", "no_text"}


def _kind_for_format(fmt: str) -> str:
    return {
        "smavg-gate-gauntlet": "gate_gauntlet",
        "smavg-codex-workload-gauntlet": "codex_workload_gauntlet",
        "smavg-safe-pack-report": "cleanup_quarantine",
        "smavg-run-receipt": "run_receipt",
        "smavg-preflight": "preflight",
        "smavg-context": "context",
        "smavg-gauntlet-v1": "storage_gauntlet",
        "smavg-gate": "gate",
        "smavg-workflow-token-summary": "workflow_context",
        "smavg-surface-gauntlet": "surface_gauntlet",
    }.get(fmt, "smavg_report")


def _label_for_report(path: Path, report: Dict[str, object], kind: str) -> str:
    for key in ("target_label", "target", "source", "root", "output_dir"):
        value = report.get(key)
        if isinstance(value, str) and value:
            return value
    return f"{kind}:{path.name}"


def _validate_role(role: str) -> str:
    role = role.strip().lower().replace("_", "-")
    allowed = {"user", "assistant", "tool-input", "tool-output", "note"}
    if role not in allowed:
        raise LedgerError(f"Unsupported task role: {role}")
    return role


def _slug(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._")
    return safe[:120] or "smavg"


def _event_id(kind: str, label: str, created_at: str) -> str:
    stamp = created_at.replace(":", "").replace("+", "Z").replace(".", "-")
    return f"{stamp}-{_slug(kind)}-{_slug(label)[:50]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
