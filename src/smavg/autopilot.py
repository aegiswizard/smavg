"""Product-grade Smavg command shell.

Autopilot is the user-facing loop over the proven Smavg core. It keeps normal
commands short (`smavg scan`, `smavg report`, `smavg apply`, `smavg status`)
while preserving the strict safety model underneath.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .ledger import default_ledger_path, ledger_report
from .safe_ops import SafePackError, safe_pack, write_safe_pack_report
from .scan import ScanError, run_scan
from .surfaces import SurfaceError, scan_surfaces


class AutopilotError(RuntimeError):
    """Raised when the Smavg product shell cannot complete safely."""


TRUTH_BOUNDARY = (
    "Smavg scan/status/report are local Smavg-visible measurements. They do "
    "not expose provider billing meters, hidden AI runtime context, account-side "
    "app access, or secrets. Smavg apply never deletes source data."
)


def default_autopilot_dir() -> Path:
    return Path.home() / ".smavg" / "autopilot"


def run_autopilot_scan(
    *,
    root: Optional[Path] = None,
    out_dir: Optional[Path] = None,
    run_id: Optional[str] = None,
    budget_tokens: int = 3000,
    recursive: bool = True,
    max_depth: int = 1,
    max_dirs: int = 40,
    include_surfaces: bool = True,
    include_workflows: bool = True,
) -> Dict[str, object]:
    """Run the short `smavg scan` product path."""
    if budget_tokens <= 0:
        raise AutopilotError("budget_tokens must be positive")
    base = Path(out_dir or default_autopilot_dir()).expanduser().resolve()
    run_id = run_id or _default_run_id("scan")
    run_dir = base / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    root = Path(root or Path.home()).expanduser().resolve()

    scan_summary = run_scan(
        root=root,
        out_dir=run_dir / "scan",
        run_id="local",
        recursive=recursive,
        max_depth=max_depth,
        max_dirs=max_dirs,
        budget_tokens=budget_tokens,
        include_workflows=include_workflows,
    )
    surfaces = None
    if include_surfaces:
        surfaces = scan_surfaces(
            out_dir=run_dir / "surfaces",
            run_id="local",
            budget_tokens=budget_tokens,
        )

    report = _autopilot_report(
        run_dir=run_dir,
        root=root,
        scan_summary=scan_summary,
        surfaces=surfaces,
        budget_tokens=budget_tokens,
    )
    report_json = run_dir / "report.json"
    report_md = run_dir / "report.md"
    report["report_json"] = str(report_json)
    report["report_markdown"] = str(report_md)
    _write_json_atomic(report_json, report)
    _write_text_atomic(report_md, render_autopilot_markdown(report))
    _write_text_atomic(base / "latest", str(report_json) + "\n")
    return report


def load_latest_autopilot(out_dir: Optional[Path] = None) -> Dict[str, object]:
    base = Path(out_dir or default_autopilot_dir()).expanduser()
    latest = base / "latest"
    try:
        report_path = Path(latest.read_text(encoding="utf-8").strip())
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutopilotError("No Smavg scan report found. Run `smavg scan` first.") from exc
    if report.get("format") != "smavg-autopilot-report":
        raise AutopilotError("Latest Smavg report has an unsupported format")
    return report


def autopilot_status(
    *,
    out_dir: Optional[Path] = None,
    ledger_path: Optional[Path] = None,
) -> Dict[str, object]:
    """Return the user-facing status card."""
    latest = None
    try:
        latest = load_latest_autopilot(out_dir)
    except AutopilotError:
        latest = None
    ledger = ledger_report(ledger_path=ledger_path or default_ledger_path(), period="all")
    today = ledger_report(ledger_path=ledger_path or default_ledger_path(), period="day")
    return {
        "format": "smavg-status",
        "version": 1,
        "generated_at": _now(),
        "latest_scan": latest,
        "ledger": {
            "all": _compact_ledger(ledger),
            "today": _compact_ledger(today),
        },
        "truth_boundary": TRUTH_BOUNDARY,
    }


def render_status_markdown(status: Dict[str, object]) -> str:
    all_time = status.get("ledger", {}).get("all", {}) if isinstance(status.get("ledger"), dict) else {}
    today = status.get("ledger", {}).get("today", {}) if isinstance(status.get("ledger"), dict) else {}
    latest = status.get("latest_scan")
    lines = [
        "# Smavg Status",
        "",
        "## Today",
        "",
        f"- Tokens saved: {today.get('tokens_saved', 0)}",
        f"- Repeated-work tokens saved: {today.get('repeated_tokens_saved', 0)}",
        f"- Disk saved: {today.get('disk_bytes_saved', 0)} bytes",
        "",
        "## All Time",
        "",
        f"- Tokens saved: {all_time.get('tokens_saved', 0)}",
        f"- Repeated-work tokens saved: {all_time.get('repeated_tokens_saved', 0)}",
        f"- Disk saved: {all_time.get('disk_bytes_saved', 0)} bytes",
        f"- AI/context reduction: {_format_ratio(all_time.get('ai_token_ratio'))}",
        f"- Repeated-work reduction: {_format_ratio(all_time.get('repeated_token_ratio'))}",
        f"- Storage reduction: {_format_ratio(all_time.get('storage_disk_ratio'))}",
        f"- Exact expansion: {all_time.get('exact_expansion_pass', 0)}/{all_time.get('exact_expansion_total', 0)}",
        f"- Evidence tasks: {all_time.get('evidence_task_pass', 0)}/{all_time.get('evidence_task_total', 0)}",
        f"- Failures counted as wins: {all_time.get('failures_counted_as_wins', 0)}",
        "",
        "## Latest Scan",
        "",
    ]
    if isinstance(latest, dict):
        summary = latest.get("summary", {}) if isinstance(latest.get("summary"), dict) else {}
        lines.extend(
            [
                f"- Run: `{latest.get('run_dir')}`",
                f"- Root: `{latest.get('root')}`",
                f"- Directory candidates: {summary.get('directory_candidates', 0)}",
                f"- Workflow candidates: {summary.get('workflow_candidates', 0)}",
                f"- Surfaces inventoried: {summary.get('surfaces', 0)}",
                f"- Surface context groups: {summary.get('surface_context_groups', 0)}",
                f"- Best directory reduction: {_format_ratio(summary.get('best_directory_token_reduction'))}",
                f"- Surface registry reduction: {_format_ratio(summary.get('surface_token_reduction_ratio'))}",
                f"- Report: `{latest.get('report_markdown')}`",
            ]
        )
    else:
        lines.append("- No scan has been run yet. Use `smavg scan`.")
    lines.extend(["", "## Truth Boundary", "", str(status.get("truth_boundary", TRUTH_BOUNDARY)), ""])
    return "\n".join(lines)


def render_autopilot_markdown(report: Dict[str, object]) -> str:
    summary = report.get("summary", {})
    files = report.get("files", {})
    lines = [
        "# Smavg Report",
        "",
        "This is the short product report. It is generated from the verified Smavg core.",
        "",
        "## Summary",
        "",
        f"- Root scanned: `{report.get('root')}`",
        f"- Directory candidates: {summary.get('directory_candidates', 0)}",
        f"- Workflow candidates: {summary.get('workflow_candidates', 0)}",
        f"- Skipped directories: {summary.get('skipped_directories', 0)}",
        f"- Surfaces inventoried: {summary.get('surfaces', 0)}",
        f"- Surface context groups: {summary.get('surface_context_groups', 0)}",
        f"- Best directory token reduction: {_format_ratio(summary.get('best_directory_token_reduction'))}",
        f"- Best workflow token reduction: {_format_ratio(summary.get('best_workflow_token_reduction'))}",
        f"- Surface registry reduction: {_format_ratio(summary.get('surface_token_reduction_ratio'))}",
        f"- Cleanup performed: `{summary.get('cleanup_performed', False)}`",
        "",
        "## Action Rule",
        "",
        "Smavg scan is read-only. Use `smavg apply SOURCE --out archive.smavg` for a verified archive path. Use quarantine only after reviewing the report.",
        "",
        "## Artifacts",
        "",
        f"- Scan report: `{files.get('scan_markdown')}`",
        f"- Scan JSON: `{files.get('scan_json')}`",
        f"- Surface report: `{files.get('surfaces_markdown')}`",
        f"- Surface JSON: `{files.get('surfaces_json')}`",
        "",
        "## Truth Boundary",
        "",
        str(report.get("truth_boundary", TRUTH_BOUNDARY)),
        "",
    ]
    return "\n".join(lines)


def apply_safe_action(
    *,
    source: Path,
    archive: Path,
    work_dir: Optional[Path] = None,
    report_path: Optional[Path] = None,
    quarantine_dir: Optional[Path] = None,
    move_to_quarantine: bool = False,
) -> Dict[str, object]:
    """Run the short `smavg apply` safe archive/quarantine path."""
    report = safe_pack(
        source=source,
        archive=archive,
        work_dir=work_dir or (default_autopilot_dir() / "apply-work"),
        quarantine_dir=quarantine_dir,
        move_to_quarantine=move_to_quarantine,
    )
    if report_path is not None:
        write_safe_pack_report(report, report_path)
        report["report_json"] = str(report_path)
        report["report_markdown"] = str(report_path.with_suffix(".md"))
    return report


def verify_autopilot(
    *,
    out_dir: Optional[Path] = None,
    ledger_path: Optional[Path] = None,
) -> Dict[str, object]:
    """Verify latest product-shell artifacts are readable and trust counters are sane."""
    checks = []
    latest = None
    try:
        latest = load_latest_autopilot(out_dir)
        checks.append(_check("latest_scan", True, "Latest scan report loaded."))
    except AutopilotError as exc:
        checks.append(_check("latest_scan", False, str(exc)))
    if isinstance(latest, dict):
        for key in ("report_json", "report_markdown"):
            path = Path(str(latest.get(key, "")))
            checks.append(_check(key, path.exists(), str(path)))
        files = latest.get("files", {}) if isinstance(latest.get("files"), dict) else {}
        for key in ("scan_json", "scan_markdown", "surfaces_json", "surfaces_markdown"):
            value = files.get(key)
            if value:
                path = Path(str(value))
                checks.append(_check(key, path.exists(), str(path)))
    ledger = ledger_report(ledger_path=ledger_path or default_ledger_path(), period="all")
    trust = ledger.get("trust", {})
    failures = int(trust.get("failures_counted_as_wins", 0)) if isinstance(trust, dict) else 0
    checks.append(_check("ledger_failures_counted_as_wins", failures == 0, str(failures)))
    passed = sum(1 for item in checks if item["pass"])
    return {
        "format": "smavg-autopilot-verify",
        "version": 1,
        "generated_at": _now(),
        "status": "PASS" if passed == len(checks) else "FAIL",
        "pass": passed,
        "total": len(checks),
        "checks": checks,
        "truth_boundary": TRUTH_BOUNDARY,
    }


def _autopilot_report(
    *,
    run_dir: Path,
    root: Path,
    scan_summary: Dict[str, object],
    surfaces: Optional[Dict[str, object]],
    budget_tokens: int,
) -> Dict[str, object]:
    surface_summary = surfaces.get("summary", {}) if isinstance(surfaces, dict) else {}
    summary = {
        "directory_candidates": int(scan_summary.get("directory_candidates", 0)),
        "workflow_candidates": int(scan_summary.get("workflow_candidates", 0)),
        "skipped_directories": int(scan_summary.get("skipped_directories", 0)),
        "best_directory_token_reduction": scan_summary.get("best_directory_token_reduction"),
        "best_workflow_token_reduction": scan_summary.get("best_workflow_token_reduction"),
        "cleanup_performed": False,
        "surfaces": int(surface_summary.get("surfaces", 0)),
        "surface_context_groups": int(surface_summary.get("context_groups", 0)),
        "surface_token_reduction_ratio": surface_summary.get("token_reduction_ratio"),
        "surface_raw_tokens_estimate": int(surface_summary.get("raw_tokens_estimate", 0)),
        "surface_brief_tokens_estimate": int(surface_summary.get("brief_tokens_estimate", 0)),
    }
    return {
        "format": "smavg-autopilot-report",
        "version": 1,
        "generated_at": _now(),
        "run_dir": str(run_dir),
        "root": str(root),
        "budget_tokens": budget_tokens,
        "summary": summary,
        "files": {
            "scan_json": scan_summary.get("scan_json"),
            "scan_markdown": scan_summary.get("scan_markdown"),
            "surfaces_json": surfaces.get("surfaces_json") if isinstance(surfaces, dict) else None,
            "surfaces_markdown": surfaces.get("surfaces_markdown") if isinstance(surfaces, dict) else None,
        },
        "truth_boundary": TRUTH_BOUNDARY,
    }


def _compact_ledger(report: Dict[str, object]) -> Dict[str, object]:
    headline = report.get("headline", {}) if isinstance(report.get("headline"), dict) else {}
    ai = report.get("ai_tokens", {}) if isinstance(report.get("ai_tokens"), dict) else {}
    repeated = report.get("repeated_work_tokens", {}) if isinstance(report.get("repeated_work_tokens"), dict) else {}
    storage = report.get("storage_disk", {}) if isinstance(report.get("storage_disk"), dict) else {}
    trust = report.get("trust", {}) if isinstance(report.get("trust"), dict) else {}
    exact = trust.get("exact_expansion", {}) if isinstance(trust.get("exact_expansion"), dict) else {}
    evidence = trust.get("evidence_tasks", {}) if isinstance(trust.get("evidence_tasks"), dict) else {}
    return {
        "tokens_saved": int(headline.get("tokens_saved_all_time", ai.get("saved", 0))) if report.get("period") == "all" else int(ai.get("saved", 0)),
        "repeated_tokens_saved": int(headline.get("repeated_tokens_saved_all_time", repeated.get("saved", 0))) if report.get("period") == "all" else int(repeated.get("saved", 0)),
        "disk_bytes_saved": int(headline.get("disk_bytes_saved_all_time", storage.get("saved", 0))) if report.get("period") == "all" else int(storage.get("saved", 0)),
        "ai_token_ratio": ai.get("ratio"),
        "repeated_token_ratio": repeated.get("ratio"),
        "storage_disk_ratio": storage.get("ratio"),
        "exact_expansion_pass": int(exact.get("pass", 0)),
        "exact_expansion_total": int(exact.get("total", 0)),
        "evidence_task_pass": int(evidence.get("pass", 0)),
        "evidence_task_total": int(evidence.get("total", 0)),
        "failures_counted_as_wins": int(trust.get("failures_counted_as_wins", 0)),
    }


def _check(name: str, ok: bool, note: str) -> Dict[str, object]:
    return {"name": name, "pass": bool(ok), "note": note}


def _default_run_id(label: str) -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{_slug(label)}"


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._")[:100] or "smavg"


def _format_ratio(value: object) -> str:
    return "n/a" if value is None else f"{value}x"


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
