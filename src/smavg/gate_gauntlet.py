"""Strict gate-mode gauntlet for Smavg input packets."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .codex_gauntlet import (
    CodexEvidenceTask,
    CodexWorkloadProbe,
    default_codex_workload_probes,
)
from .context import ContextError, expand_context_file
from .gate import GateError, run_gate
from .receipt import ReceiptError, append_expansion_to_receipt


class GateGauntletError(RuntimeError):
    """Raised when the strict gate gauntlet cannot run."""


def run_gate_gauntlet(
    output_dir: Path,
    *,
    probes: Optional[Iterable[CodexWorkloadProbe]] = None,
    budget_tokens: int = 3000,
    repeat_count: int = 3,
    reset: bool = False,
) -> Dict[str, object]:
    """Run strict raw-oracle versus gate+receipt evidence checks."""
    output_dir = Path(output_dir).expanduser().resolve()
    if reset and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = list(probes) if probes is not None else default_codex_workload_probes()
    if not selected:
        raise GateGauntletError("No gate gauntlet probes are available")
    if repeat_count < 1:
        raise GateGauntletError("repeat_count must be at least 1")

    results = [
        _run_probe(probe, output_dir, budget_tokens=budget_tokens, repeat_count=repeat_count)
        for probe in selected
    ]
    report = {
        "format": "smavg-gate-gauntlet",
        "version": 1,
        "generated_at": _now(),
        "output_dir": str(output_dir),
        "budget_tokens": budget_tokens,
        "repeat_count": repeat_count,
        "trust_rule": (
            "A gate result counts only when the gate packet exists, the gate and "
            "receipt both record that Smavg did not supply the full raw source, "
            "all required files expand through receipt-aware exact expansion, "
            "and gated exact evidence matches the raw local oracle evidence. "
            "Raw source is read by the gauntlet only as the scoring oracle."
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


def _run_probe(
    probe: CodexWorkloadProbe,
    output_dir: Path,
    *,
    budget_tokens: int,
    repeat_count: int,
) -> Dict[str, object]:
    run_id = _slug(probe.name)
    task = _probe_task(probe)
    result: Dict[str, object] = {
        "name": probe.name,
        "description": probe.description,
        "source": str(probe.source) if probe.source is not None else None,
        "workflow": probe.workflow,
        "required_paths": list(_probe_required_paths(probe)),
        "status": "FAIL",
        "failures": [],
        "warnings": [],
    }
    try:
        gate = run_gate(
            out_dir=output_dir,
            source=probe.source,
            workflow=probe.workflow,
            task=task,
            budget_tokens=budget_tokens,
            run_id=run_id,
        )
        files = gate["files"]
        context_json = Path(str(files["context_json"]))
        gate_md = Path(str(files["gate_markdown"]))
        gate_json = Path(str(files["gate_json"]))
        receipt_json = Path(str(files["receipt_json"]))
        exact_dir = Path(str(files["exact_dir"]))
        loaded_context = json.loads(context_json.read_text(encoding="utf-8"))
        markdown = Path(str(files["context_markdown"])).read_text(encoding="utf-8")
        files_by_path = _files_by_path(loaded_context)

        expansion_rows = []
        for relative in _probe_required_paths(probe):
            output = exact_dir / _safe_exact_name(relative)
            record = files_by_path.get(relative)
            row: Dict[str, object] = {
                "path": relative,
                "present_in_context_json": record is not None,
                "visible_in_context_markdown": relative in markdown,
                "expanded": False,
                "verified": False,
                "receipt_recorded": False,
                "estimated_tokens": int(record.get("estimated_tokens", 0)) if record else 0,
                "bytes": 0,
                "out": str(output),
            }
            if record is None:
                result["failures"].append(f"Required path missing from context JSON: {relative}")
            else:
                size = expand_context_file(context_json, relative, output)
                receipt = append_expansion_to_receipt(
                    receipt_json=receipt_json,
                    context_json=context_json,
                    relative_path=relative,
                    expanded_output=output,
                )
                row["bytes"] = size
                row["expanded"] = True
                row["verified"] = True
                row["receipt_recorded"] = _receipt_has_path(receipt, relative)
            expansion_rows.append(row)

        receipt = json.loads(receipt_json.read_text(encoding="utf-8"))
        tasks = _score_tasks(probe, loaded_context, files_by_path, expansion_rows)
        gate_ok = (
            gate_md.exists()
            and gate_json.exists()
            and gate.get("format") == "smavg-gate"
            and gate.get("measurement", {}).get("full_raw_source_supplied_by_smavg") is False
        )
        receipt_ok = (
            receipt.get("format") == "smavg-run-receipt"
            and receipt.get("supplied_to_agent", {}).get("full_raw_source_supplied_by_smavg") is False
            and all(row.get("receipt_recorded") for row in expansion_rows)
        )
        expansion_ok = all(row.get("verified") for row in expansion_rows)
        routing_ok = all(row.get("visible_in_context_markdown") for row in expansion_rows)
        tasks_ok = all(task.get("status") == "PASS" for task in tasks)

        raw_tokens = int(gate.get("measurement", {}).get("raw_tokens_estimate", 0))
        brief_tokens = int(gate.get("measurement", {}).get("brief_tokens_estimate", 0))
        receipt_tokens = int(receipt.get("supplied_to_agent", {}).get("total_tokens_estimate", 0))
        repeated_raw = raw_tokens * repeat_count
        status = "PASS" if gate_ok and receipt_ok and expansion_ok and routing_ok and tasks_ok and receipt_tokens < raw_tokens else "FAIL"
        if not gate_ok:
            result["failures"].append("Gate packet failed integrity checks")
        if not receipt_ok:
            result["failures"].append("Receipt did not record all exact expansions or raw-source boundary")
        if not expansion_ok:
            result["failures"].append("One or more exact expansions failed")
        if not routing_ok:
            result["failures"].append("One or more required paths were not visible in context markdown")
        if not tasks_ok:
            result["failures"].append("One or more evidence tasks failed")
        if receipt_tokens >= raw_tokens:
            result["failures"].append("Receipt-token path did not reduce tokens")

        result.update(
            {
                "status": status,
                "run_dir": gate.get("run_dir"),
                "gate_markdown": str(gate_md),
                "gate_json": str(gate_json),
                "context_markdown": str(files["context_markdown"]),
                "context_json": str(context_json),
                "receipt_json": str(receipt_json),
                "raw_tokens_estimate": raw_tokens,
                "brief_tokens_estimate": brief_tokens,
                "receipt_tokens_estimate": receipt_tokens,
                "brief_only_reduction_ratio": _ratio(raw_tokens, brief_tokens),
                "receipt_reduction_ratio": _ratio(raw_tokens, receipt_tokens),
                "repeat_count": repeat_count,
                "repeated_raw_tokens_estimate": repeated_raw,
                "repeated_gate_tokens_estimate": receipt_tokens,
                "repeated_reduction_ratio": _ratio(repeated_raw, receipt_tokens),
                "full_raw_source_supplied_by_smavg": False,
                "gate_integrity": "PASS" if gate_ok else "FAIL",
                "receipt_integrity": "PASS" if receipt_ok else "FAIL",
                "exact_expansion": "PASS" if expansion_ok else "FAIL",
                "model_routing": "PASS" if routing_ok else "FAIL",
                "tasks": tasks,
                "task_summary": _task_summary(tasks),
                "expansions": expansion_rows,
            }
        )
    except (ContextError, GateError, ReceiptError, OSError, json.JSONDecodeError) as exc:
        result["failures"].append(str(exc))
    return result


def _score_tasks(
    probe: CodexWorkloadProbe,
    report: Dict[str, object],
    files_by_path: Dict[str, Dict[str, object]],
    expansion_rows: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    tasks = probe.tasks or (
        CodexEvidenceTask(
            name="required-files-exact",
            question="Can the gate expand the required exact files?",
            required_paths=tuple(probe.required_paths),
            evidence_terms=tuple(Path(path).name for path in probe.required_paths),
        ),
    )
    expansion_by_path = {str(row["path"]): row for row in expansion_rows}
    scored = []
    for task in tasks:
        raw_text = _task_text_from_source(report, task.required_paths, files_by_path)
        gate_text = _task_text_from_expanded(task.required_paths, expansion_by_path)
        raw_hits = _term_hits(raw_text, task.evidence_terms)
        gate_hits = _term_hits(gate_text, task.evidence_terms)
        expanded = all(bool(expansion_by_path.get(path, {}).get("verified")) for path in task.required_paths)
        raw_correct = all(raw_hits.values()) if task.evidence_terms else bool(raw_text)
        gate_correct = all(gate_hits.values()) if task.evidence_terms else bool(gate_text)
        same = raw_hits == gate_hits
        scored.append(
            {
                "name": task.name,
                "question": task.question,
                "required_paths": list(task.required_paths),
                "evidence_terms": list(task.evidence_terms),
                "raw_correct": raw_correct,
                "gate_correct": gate_correct,
                "same_evidence": same,
                "expanded_paths_verified": expanded,
                "status": "PASS" if raw_correct and gate_correct and same and expanded else "FAIL",
                "raw_term_hits": raw_hits,
                "gate_term_hits": gate_hits,
                "evidence_snippets": _snippets(gate_text or raw_text, task.evidence_terms),
            }
        )
    return scored


def _summary(results: List[Dict[str, object]]) -> Dict[str, object]:
    passed = [item for item in results if item.get("status") == "PASS"]
    gate_integrity = [item for item in results if item.get("gate_integrity") == "PASS"]
    receipt_integrity = [item for item in results if item.get("receipt_integrity") == "PASS"]
    exact = [item for item in results if item.get("exact_expansion") == "PASS"]
    routing = [item for item in results if item.get("model_routing") == "PASS"]
    raw_tokens = sum(int(item.get("raw_tokens_estimate", 0)) for item in results)
    receipt_tokens = sum(int(item.get("receipt_tokens_estimate", 0)) for item in results)
    repeated_raw = sum(int(item.get("repeated_raw_tokens_estimate", 0)) for item in results)
    repeated_gate = sum(int(item.get("repeated_gate_tokens_estimate", 0)) for item in results)
    task_rows = [task for result in results for task in result.get("tasks", []) if isinstance(task, dict)]
    task_pass = [task for task in task_rows if task.get("status") == "PASS"]
    same_evidence = [task for task in task_rows if task.get("same_evidence")]
    return {
        "probes": len(results),
        "pass": len(passed),
        "fail": len(results) - len(passed),
        "gate_integrity_pass": len(gate_integrity),
        "receipt_integrity_pass": len(receipt_integrity),
        "exact_expansion_pass": len(exact),
        "model_routing_pass": len(routing),
        "evidence_tasks": len(task_rows),
        "evidence_task_pass": len(task_pass),
        "same_evidence": len(same_evidence),
        "raw_tokens_estimate": raw_tokens,
        "gate_receipt_tokens_estimate": receipt_tokens,
        "receipt_reduction_ratio": _ratio(raw_tokens, receipt_tokens),
        "repeated_raw_tokens_estimate": repeated_raw,
        "repeated_gate_tokens_estimate": repeated_gate,
        "repeated_reduction_ratio": _ratio(repeated_raw, repeated_gate),
        "full_raw_source_supplied_by_smavg": False,
    }


def _render_markdown(report: Dict[str, object]) -> str:
    summary = report["summary"]
    lines = [
        "# Smavg Gate Gauntlet",
        "",
        report["trust_rule"],
        "",
        "## Summary",
        "",
        f"- Probes: {summary['probes']}",
        f"- PASS: {summary['pass']}",
        f"- FAIL: {summary['fail']}",
        f"- Gate integrity PASS: {summary['gate_integrity_pass']}/{summary['probes']}",
        f"- Receipt integrity PASS: {summary['receipt_integrity_pass']}/{summary['probes']}",
        f"- Exact expansion PASS: {summary['exact_expansion_pass']}/{summary['probes']}",
        f"- Model routing PASS: {summary['model_routing_pass']}/{summary['probes']}",
        f"- Evidence tasks PASS: {summary['evidence_task_pass']}/{summary['evidence_tasks']}",
        f"- Same evidence: {summary['same_evidence']}/{summary['evidence_tasks']}",
        f"- Raw tokens estimate: {summary['raw_tokens_estimate']}",
        f"- Gate receipt tokens estimate: {summary['gate_receipt_tokens_estimate']}",
        f"- Receipt reduction: {_format_ratio(summary['receipt_reduction_ratio'])}",
        f"- Repeated-work reduction: {_format_ratio(summary['repeated_reduction_ratio'])}",
        f"- Full raw source supplied by Smavg: `{summary['full_raw_source_supplied_by_smavg']}`",
        "",
        "## Results",
        "",
    ]
    for item in report["results"]:
        lines.extend(
            [
                f"### {item['name']}",
                "",
                f"- Status: `{item.get('status')}`",
                f"- Gate: `{item.get('gate_integrity')}`",
                f"- Receipt: `{item.get('receipt_integrity')}`",
                f"- Exact expansion: `{item.get('exact_expansion')}`",
                f"- Routing: `{item.get('model_routing')}`",
                f"- Raw tokens: {item.get('raw_tokens_estimate', 0)}",
                f"- Receipt tokens: {item.get('receipt_tokens_estimate', 0)}",
                f"- Reduction: {_format_ratio(item.get('receipt_reduction_ratio'))}",
                f"- Run dir: `{item.get('run_dir')}`",
            ]
        )
        if item.get("failures"):
            lines.append("- Failures:")
            for failure in item["failures"]:
                lines.append(f"  - {failure}")
        lines.append("")
    return "\n".join(lines)


def _task_summary(tasks: List[Dict[str, object]]) -> Dict[str, object]:
    passed = [task for task in tasks if task.get("status") == "PASS"]
    same = [task for task in tasks if task.get("same_evidence")]
    return {"tasks": len(tasks), "pass": len(passed), "same_evidence": len(same)}


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
        source_path = record.get("source_path")
        if isinstance(source_path, str) and source_path:
            target = Path(source_path)
        else:
            target = Path(str(report.get("source_path", ""))) / relative
        chunks.append(_read_text_best_effort(target))
    return "\n".join(chunks)


def _task_text_from_expanded(paths: Iterable[str], expansion_by_path: Dict[str, Dict[str, object]]) -> str:
    chunks = []
    for relative in paths:
        output = expansion_by_path.get(relative, {}).get("out")
        if output:
            chunks.append(_read_text_best_effort(Path(str(output))))
    return "\n".join(chunks)


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


def _files_by_path(report: Dict[str, object]) -> Dict[str, Dict[str, object]]:
    return {
        str(item["path"]): item
        for item in report.get("files", [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }


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


def _probe_task(probe: CodexWorkloadProbe) -> str:
    questions = "; ".join(task.question for task in probe.tasks[:3])
    return (
        f"Use this Smavg gate packet for {probe.name}. "
        f"Answer these evidence tasks using exact expansions only when needed: {questions}"
    )


def _receipt_has_path(receipt: Dict[str, object], relative: str) -> bool:
    expansions = receipt.get("supplied_to_agent", {}).get("exact_expansions", [])
    return any(isinstance(item, dict) and item.get("path") == relative and item.get("verified") for item in expansions)


def _term_hits(text: str, terms: Iterable[str]) -> Dict[str, bool]:
    lowered = text.lower()
    return {term: term.lower() in lowered for term in terms}


def _snippets(text: str, terms: Iterable[str], limit: int = 8) -> List[Dict[str, str]]:
    lines = text.splitlines()
    output = []
    for term in terms:
        term_lower = term.lower()
        match = ""
        for line in lines:
            if term_lower in line.lower():
                match = line.strip()[:220]
                break
        output.append({"term": term, "line": match})
        if len(output) >= limit:
            break
    return output


def _ratio(before: int, after: int) -> Optional[float]:
    return round(before / after, 3) if before and after else None


def _format_ratio(value: object) -> str:
    return "n/a" if value is None else f"{value}x"


def _slug(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in "._-" else "-" for char in value).strip("-._")
    return safe[:80] or "probe"


def _safe_exact_name(path: str) -> str:
    return _slug(path.replace("/", "__")) or "exact-file"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
