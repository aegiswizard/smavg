"""Smavg Work Mode: gate, receipt, task counter, and ledger in one loop."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional

from .context import ContextError, expand_context_file
from .gate import GateError, run_gate
from .ledger import (
    LedgerError,
    add_task_report,
    add_task_text,
    default_ledger_path,
    default_tasks_dir,
    end_task,
    load_task,
    render_task_markdown,
    start_task,
    summarize_task,
)
from .receipt import ReceiptError, append_expansion_to_receipt


class WorkError(RuntimeError):
    """Raised when a Smavg work session cannot be operated."""


def default_work_dir() -> Path:
    return Path.home() / ".smavg" / "work"


def start_work(
    *,
    task: str,
    source: Optional[Path] = None,
    workflow: Optional[str] = None,
    budget_tokens: int = 3000,
    work_dir: Optional[Path] = None,
    tasks_dir: Optional[Path] = None,
    work_id: Optional[str] = None,
) -> Dict[str, object]:
    """Start a Smavg-first work session."""
    if not task.strip():
        raise WorkError("Work task cannot be empty")
    if (source is None) == (workflow is None):
        raise WorkError("Work start requires exactly one of source or workflow")
    base = Path(work_dir or default_work_dir()).expanduser()
    task_store = Path(tasks_dir or default_tasks_dir()).expanduser()
    target_slug = workflow if workflow is not None else Path(source or "source").name
    session_id = work_id or _default_work_id(target_slug)
    run_root = base / "runs"
    gate = run_gate(
        out_dir=run_root,
        task=task,
        source=source,
        workflow=workflow,
        budget_tokens=budget_tokens,
        run_id=session_id,
    )
    task_session = start_task(
        label=task,
        surface="smavg-work",
        tasks_dir=task_store,
        task_id=session_id,
    )
    files = gate.get("files", {})
    session = {
        "format": "smavg-work-session",
        "version": 1,
        "id": session_id,
        "task": task,
        "task_id": task_session["id"],
        "started_at": _now(),
        "ended_at": None,
        "status": "active",
        "target_kind": gate.get("target_kind"),
        "target_label": gate.get("target_label"),
        "source": str(Path(source).expanduser().resolve()) if source is not None else None,
        "workflow": workflow,
        "budget_tokens": budget_tokens,
        "work_dir": str(base),
        "tasks_dir": str(task_store),
        "gate": gate,
        "files": files,
        "exact_expansions": [],
        "notes": [
            "Use gate.md/context.md as setup.",
            "Use work expand for exact files so receipt accounting stays current.",
            "End the work session to record one task_session event in the ledger.",
        ],
    }
    _write_work(session, base)
    _write_current_work(str(session["id"]), base)
    return session


def load_work(work_id: Optional[str] = None, work_dir: Optional[Path] = None) -> Dict[str, object]:
    base = Path(work_dir or default_work_dir()).expanduser()
    if work_id is None:
        work_id = _read_current_work(base)
    path = _work_path(str(work_id), base)
    try:
        session = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkError(f"Could not read Smavg work session: {path}") from exc
    if session.get("format") != "smavg-work-session":
        raise WorkError("Unsupported Smavg work session format")
    return session


def expand_work(
    *,
    relative_path: str,
    work_id: Optional[str] = None,
    work_dir: Optional[Path] = None,
    output: Optional[Path] = None,
) -> Dict[str, object]:
    """Expand one exact file through the active work receipt."""
    session = load_work(work_id, work_dir)
    if session.get("status") != "active":
        raise WorkError("Cannot expand files for an ended work session")
    files = _session_files(session)
    context_json = Path(str(files["context_json"]))
    receipt_json = Path(str(files["receipt_json"]))
    exact_dir = Path(str(files["exact_dir"]))
    out = Path(output) if output is not None else exact_dir / _safe_expansion_name(relative_path)
    bytes_written = expand_context_file(context_json, relative_path, out)
    receipt = append_expansion_to_receipt(
        receipt_json=receipt_json,
        context_json=context_json,
        relative_path=relative_path,
        expanded_output=out,
    )
    expansions = [
        item
        for item in receipt.get("supplied_to_agent", {}).get("exact_expansions", [])
        if isinstance(item, dict)
    ]
    expansion = expansions[-1] if expansions else {"path": relative_path, "output": str(out), "bytes": bytes_written}
    session.setdefault("exact_expansions", []).append(expansion)
    session["updated_at"] = _now()
    _write_work(session, Path(str(session["work_dir"])))
    return {"work": session, "receipt": receipt, "expansion": expansion}


def note_work(
    *,
    role: str,
    text: str,
    work_id: Optional[str] = None,
    work_dir: Optional[Path] = None,
    label: Optional[str] = None,
) -> Dict[str, object]:
    """Record visible task text against the work session."""
    session = load_work(work_id, work_dir)
    if session.get("status") != "active":
        raise WorkError("Cannot add notes to an ended work session")
    task = add_task_text(
        task_id=str(session["task_id"]),
        role=role,
        text=text,
        tasks_dir=Path(str(session["tasks_dir"])),
        label=label,
    )
    session["updated_at"] = _now()
    _write_work(session, Path(str(session["work_dir"])))
    return {"work": session, "task": task, "summary": summarize_task(task)}


def end_work(
    *,
    work_id: Optional[str] = None,
    work_dir: Optional[Path] = None,
    ledger_path: Optional[Path] = None,
    record_ledger: bool = True,
    report_path: Optional[Path] = None,
) -> Dict[str, object]:
    """End the active work session and append one task event to the ledger."""
    session = load_work(work_id, work_dir)
    if session.get("status") == "ended":
        raise WorkError("Work session has already ended")
    files = _session_files(session)
    receipt_json = Path(str(files["receipt_json"]))
    gate_json = Path(str(files["gate_json"]))
    work_json = _work_path(str(session["id"]), Path(str(session["work_dir"])))
    task = add_task_report(
        task_id=str(session["task_id"]),
        report_path=receipt_json,
        kind="run_receipt",
        label=f"work:{session['id']}",
        surface="smavg-work",
        tasks_dir=Path(str(session["tasks_dir"])),
    )
    task = end_task(
        task_id=str(session["task_id"]),
        tasks_dir=Path(str(session["tasks_dir"])),
        ledger_path=Path(ledger_path or default_ledger_path()).expanduser(),
        record_ledger=record_ledger,
        artifacts=[str(receipt_json), str(gate_json), str(work_json)],
        notes=[
            "Recorded by Smavg Work Mode.",
            "Work Mode records one task_session event; receipt/gate are artifacts, not separate wins.",
        ],
    )
    session["status"] = "ended"
    session["ended_at"] = _now()
    session["task_summary"] = task["summary"]
    session["task_report"] = render_task_markdown(task)
    if report_path is not None:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text(render_work_markdown(session), encoding="utf-8")
        session["work_report_markdown"] = str(report_path)
    _write_work(session, Path(str(session["work_dir"])))
    return {"work": session, "task": task}


def summarize_work(session: Dict[str, object]) -> Dict[str, object]:
    files = _session_files(session)
    receipt_path = Path(str(files["receipt_json"]))
    receipt = _read_json(receipt_path) if receipt_path.exists() else {}
    supplied = receipt.get("supplied_to_agent", {}) if isinstance(receipt, dict) else {}
    raw = receipt.get("raw_material", {}) if isinstance(receipt, dict) else {}
    task_summary = session.get("task_summary")
    if not isinstance(task_summary, dict):
        try:
            task_summary = summarize_task(load_task(str(session["task_id"]), Path(str(session["tasks_dir"]))))
        except (LedgerError, OSError):
            task_summary = {}
    return {
        "id": session.get("id"),
        "status": session.get("status"),
        "target_label": session.get("target_label"),
        "raw_setup_tokens": int(raw.get("raw_tokens_estimate", 0)),
        "smavg_supplied_tokens": int(supplied.get("total_tokens_estimate", 0)),
        "brief_tokens": int(supplied.get("brief_tokens_estimate", 0)),
        "exact_expansion_tokens": int(supplied.get("exact_expansion_tokens_estimate", 0)),
        "reduction_ratio": supplied.get("reduction_ratio"),
        "exact_expansions": len(supplied.get("exact_expansions", [])),
        "full_raw_source_supplied_by_smavg": bool(supplied.get("full_raw_source_supplied_by_smavg", False)),
        "visible_user_input_tokens": int(task_summary.get("visible_user_input_tokens", 0)),
        "visible_assistant_output_tokens": int(task_summary.get("visible_assistant_output_tokens", 0)),
        "visible_tool_tokens": int(task_summary.get("visible_tool_tokens", 0)),
    }


def render_work_markdown(session: Dict[str, object]) -> str:
    summary = summarize_work(session)
    ratio = summary.get("reduction_ratio")
    ratio_text = "n/a" if ratio is None else f"{ratio}x"
    files = _session_files(session)
    lines = [
        f"# Smavg Work Session: {session.get('task')}",
        "",
        f"- Work id: `{session.get('id')}`",
        f"- Status: `{session.get('status')}`",
        f"- Target: `{summary['target_label']}`",
        f"- Started: `{session.get('started_at')}`",
        f"- Ended: `{session.get('ended_at')}`",
        "",
        "## Smavg Setup",
        "",
        f"- Raw setup tokens: {summary['raw_setup_tokens']}",
        f"- Brief tokens: {summary['brief_tokens']}",
        f"- Exact expansion tokens: {summary['exact_expansion_tokens']}",
        f"- Total Smavg-supplied tokens: {summary['smavg_supplied_tokens']}",
        f"- Reduction: {ratio_text}",
        f"- Full raw source supplied by Smavg: `{summary['full_raw_source_supplied_by_smavg']}`",
        "",
        "## Visible Task Tokens",
        "",
        f"- User input: {summary['visible_user_input_tokens']}",
        f"- Assistant output: {summary['visible_assistant_output_tokens']}",
        f"- Tool text: {summary['visible_tool_tokens']}",
        "",
        "## Files",
        "",
        f"- Gate: `{files.get('gate_markdown')}`",
        f"- Context: `{files.get('context_markdown')}`",
        f"- Receipt: `{files.get('receipt_markdown')}`",
        f"- Work JSON: `{_work_path(str(session.get('id')), Path(str(session.get('work_dir'))))}`",
        "",
        "## Exact Expansions",
        "",
    ]
    expansions = session.get("exact_expansions", [])
    if expansions:
        for item in expansions:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- `{item.get('path')}` -> `{item.get('output')}` "
                f"({item.get('tokens_estimate', 0)} tokens, verified `{item.get('verified', False)}`)"
            )
    else:
        lines.append("No exact expansions recorded.")
    lines.extend(
        [
            "",
            "## Truth Boundary",
            "",
            "Smavg Work Mode records Smavg-supplied context and visible task text. "
            "It does not claim private provider billing-meter visibility.",
            "",
        ]
    )
    return "\n".join(lines)


def _session_files(session: Dict[str, object]) -> Dict[str, object]:
    files = session.get("files", {})
    if not isinstance(files, dict):
        raise WorkError("Work session is missing file paths")
    required = ("context_json", "receipt_json", "gate_json", "gate_markdown", "context_markdown", "receipt_markdown", "exact_dir")
    for key in required:
        if not files.get(key):
            raise WorkError(f"Work session is missing {key}")
    return files


def _write_work(session: Dict[str, object], work_dir: Path) -> None:
    _write_json_atomic(_work_path(str(session["id"]), work_dir), session)


def _work_path(work_id: str, work_dir: Path) -> Path:
    return Path(work_dir).expanduser() / "sessions" / f"{_slug(work_id)}.json"


def _write_current_work(work_id: str, work_dir: Path) -> None:
    base = Path(work_dir).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(base / "current", work_id + "\n")


def _read_current_work(work_dir: Path) -> str:
    path = Path(work_dir).expanduser() / "current"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise WorkError("No current Smavg work session. Use `smavg work start`.") from exc
    if not value:
        raise WorkError("Current Smavg work session is empty")
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


def _read_json(path: Path) -> Dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkError(f"Could not read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise WorkError(f"Expected object JSON: {path}")
    return value


def _default_work_id(slug: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{_slug(slug)}-work"


def _safe_expansion_name(path: str) -> str:
    return _slug(path.replace("/", "__")) or "exact-file"


def _slug(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._")
    return safe[:120] or "smavg-work"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
