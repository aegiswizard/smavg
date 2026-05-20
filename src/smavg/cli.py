"""Command line interface for Smavg Phase 1."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Dict, Iterable

from .autopilot import (
    AutopilotError,
    apply_safe_action,
    autopilot_status,
    default_autopilot_dir,
    load_latest_autopilot,
    render_autopilot_markdown,
    render_status_markdown,
    run_autopilot_scan,
    verify_autopilot,
)
from .container import (
    ContainerError,
    extract_container_file,
    pack_container,
    report_container,
    restore_container,
    verify_container,
)
from .context import (
    ContextError,
    build_context_report,
    expand_context_file,
    render_context_markdown,
    write_context_outputs,
)
from .codex_gauntlet import CodexGauntletError, run_codex_workload_gauntlet
from .daemon import (
    DaemonError,
    daemon_status,
    default_daemon_config_path,
    default_daemon_dir,
    render_daemon_status_markdown,
    run_daemon_loop,
    run_daemon_once,
    write_daemon_config,
    write_service_file,
)
from .gauntlet import GauntletError, run_gauntlet
from .gate import GateError, run_gate
from .gate_gauntlet import GateGauntletError, run_gate_gauntlet
from .ledger import (
    LedgerError,
    add_task_report,
    add_task_text,
    append_event,
    create_event,
    default_ledger_path,
    default_tasks_dir,
    end_task,
    event_from_report,
    import_reports,
    ledger_report,
    load_events,
    load_task,
    render_ledger_markdown,
    render_task_markdown,
    start_task,
    summarize_task,
)
from .preflight import run_preflight
from .plugin import (
    PluginError,
    build_plugin_bundle,
    default_plugin_dir,
    verify_plugin_bundle,
)
from .receipt import (
    ReceiptError,
    append_expansion_to_receipt,
    create_receipt_from_context,
    initialize_receipt_from_preflight,
)
from .realdata import (
    CISA_KEV_URL,
    LOGHUB_2K_FILES,
    write_cisa_kev_corpus,
    write_git_history_corpus,
    write_loghub_corpus,
    write_nvd_cve_corpus,
    write_weather_csv_corpus,
)
from .safe_ops import SafePackError, safe_pack, write_safe_pack_report
from .scan import ScanError, run_scan
from .store import SmavgError, SmavgStore, apparent_size, disk_size
from .surfaces import (
    SurfaceError,
    render_surface_registry_markdown,
    run_surface_gauntlet,
    scan_surfaces,
)
from .workflow_context import available_workflow_profiles, build_workflow_context_report
from .work import (
    WorkError,
    default_work_dir,
    end_work,
    expand_work,
    load_work,
    note_work,
    render_work_markdown,
    start_work,
    summarize_work,
)


def human_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{value} B"


def print_stats(stats: Dict[str, object]) -> None:
    print(f"Files: {stats['file_count']}")
    print(f"Objects: {stats['object_count']}")
    print(f"Snapshots: {stats['snapshot_count']}")
    print(f"Logical bytes: {stats['logical_bytes']} ({human_bytes(int(stats['logical_bytes']))})")
    print(f"Payload bytes: {stats['payload_bytes']} ({human_bytes(int(stats['payload_bytes']))})")
    print(
        "Store apparent bytes: "
        f"{stats['store_apparent_bytes']} ({human_bytes(int(stats['store_apparent_bytes']))})"
    )
    print(
        "Store disk bytes: "
        f"{stats['store_disk_bytes']} ({human_bytes(int(stats['store_disk_bytes']))})"
    )
    print(f"Payload ratio: {stats['payload_ratio']}")
    print(f"Apparent ratio: {stats['apparent_ratio']}")
    print(f"Disk ratio: {stats['disk_ratio']}")
    print(f"Object modes: {stats.get('object_modes', {})}")
    print(f"Snapshot pack file modes: {stats.get('snapshot_pack_file_modes', {})}")


def print_plan_summary(plan: Dict[str, object]) -> None:
    families = plan.get("families", [])
    fallback = plan.get("fallback", {})
    print(f"Planner: v{plan.get('planner_version')}")
    print(f"Families detected: {len(families)}")
    for family in families:
        print(
            "  "
            f"{family.get('family')} {family.get('label')}: "
            f"{family.get('files')} files, "
            f"{family.get('stored_payload_bytes')} payload bytes, "
            f"{family.get('payload_ratio')}x payload, "
            f"{family.get('codec')}"
        )
    print(
        "Fallback: "
        f"{fallback.get('files', 0)} files, "
        f"{fallback.get('plan', 'none')}"
    )


def print_snapshot_report(report: Dict[str, object]) -> None:
    snapshot = report["snapshot"]
    stats = report["stats"]
    print(f"Snapshot: {snapshot['id']}")
    print(f"Files: {snapshot['file_count']}")
    print(f"Logical bytes: {snapshot['logical_bytes']} ({human_bytes(int(snapshot['logical_bytes']))})")
    print(
        "Store apparent bytes: "
        f"{stats['store_apparent_bytes']} ({human_bytes(int(stats['store_apparent_bytes']))})"
    )
    print(f"Apparent ratio: {stats['apparent_ratio']}")
    planner = snapshot.get("planner")
    if planner:
        print_plan_summary(planner)
    print(f"Packs: {len(report['packs'])}")
    print(f"Fallback files: {len(report['files'])}")


def print_container_report(report: Dict[str, object]) -> None:
    print(f"Archive: {report['archive']}")
    print(f"Format: {report['format']} v{report['version']}")
    print(f"Files: {report['file_count']}")
    print(f"Logical bytes: {report['logical_bytes']} ({human_bytes(int(report['logical_bytes']))})")
    print(f"Archive bytes: {report['archive_bytes']} ({human_bytes(int(report['archive_bytes']))})")
    print(f"Ratio: {report['ratio']}")
    print(f"Payload ratio: {report['payload_ratio']}")
    print("Family detection:")
    families = report.get("families", [])
    if families:
        for family in families:
            print(
                "  "
                f"{family.get('kind')} {family.get('label')}: "
                f"{family.get('file_count')} files, "
                f"{family.get('length')} payload bytes, "
                f"{family.get('codec')}"
            )
    else:
        print("  none")
    print(f"Fallback files: {len(report.get('fallback_files', []))}")
    print("Integrity:")
    print(f"  Health: {report['integrity']['health']}")
    breakdown = report["overhead_breakdown"]
    print("Overhead breakdown:")
    for name in ("payload", "manifest", "header"):
        item = breakdown[name]
        print(f"  {name}: {item['bytes']} bytes ({item['percent']}%)")


def print_context_report(report: Dict[str, object]) -> None:
    assessment = report.get("assessment", {})
    ratio = report.get("token_reduction_ratio")
    print(f"Context: {report['source_path']}")
    print(f"Source kind: {report.get('source_kind', 'directory')}")
    print(f"Files: {report['file_count']}")
    print(f"Text files: {report['text_file_count']}")
    print(f"Binary files: {report['binary_file_count']}")
    if int(report.get("missing_source_count", 0)):
        print(f"Missing source inputs: {report['missing_source_count']}")
    print(f"Logical bytes: {report['logical_bytes']} ({human_bytes(int(report['logical_bytes']))})")
    print(f"Original text tokens estimate: {report['original_tokens_estimate']}")
    print(f"Brief tokens estimate: {report['brief_tokens_estimate']}")
    print(f"Token reduction: {'n/a' if ratio is None else f'{ratio}x'}")
    print(f"Families detected: {report['families_detected']}")
    print(f"Family token coverage: {report.get('family_coverage_percent', 0.0)}%")
    print(f"Assessment: {assessment.get('status', 'unknown')}")
    print(f"Recommendation: {assessment.get('recommendation', 'not evaluated')}")
    recommended = report.get("recommended_expansions", [])
    if recommended:
        print("Recommended exact files:")
        for item in recommended[:5]:
            reasons = ", ".join(item.get("reasons", [])) or "large/high-signal text file"
            print(
                "  "
                f"{item.get('path')}: "
                f"{item.get('estimated_tokens')} tokens, "
                f"{reasons}"
            )
    for family in report.get("families", [])[:10]:
        print(
            "  "
            f"{family.get('kind')} {family.get('display_label', family.get('label'))}: "
            f"{family.get('files')} files, "
            f"{family.get('estimated_tokens')} tokens, "
            f"stable_line_ratio={family.get('stable_line_ratio')}"
        )
    print(f"Source root SHA-256: {report['source_root_sha256']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smavg",
        description="Smavg Phase 1 local storage prototype.",
    )
    parser.add_argument(
        "--store",
        default=".smavg",
        help="Path to the Smavg store directory. Defaults to .smavg.",
    )
    parser.add_argument(
        "--no-json-template",
        action="store_true",
        help="Disable deterministic JSON template storage.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize the store.")

    pack_parser = sub.add_parser("pack", help="Create a compact single-file .smavg archive.")
    pack_parser.add_argument("source", type=Path)
    pack_parser.add_argument("--out", required=True, type=Path, help="Output .smavg archive path.")

    archive_parser = sub.add_parser("archive", help="Archive a directory as a durable snapshot.")
    archive_parser.add_argument("source", type=Path)
    archive_parser.add_argument("--snapshot-id", help="Optional explicit snapshot id.")

    import_parser = sub.add_parser("import", help="Import a directory into the store.")
    import_parser.add_argument("source", type=Path)

    put_parser = sub.add_parser("put", help="Store one file.")
    put_parser.add_argument("source", type=Path)
    put_parser.add_argument("--path", help="Logical path to use inside Smavg.")

    get_parser = sub.add_parser("get", help="Restore one stored file.")
    get_parser.add_argument("path")
    get_parser.add_argument("destination", type=Path)

    export_parser = sub.add_parser("export", help="Restore every stored file.")
    export_parser.add_argument("destination", type=Path)

    restore_parser = sub.add_parser("restore", help="Restore a snapshot or .smavg archive to a directory.")
    restore_parser.add_argument("target", type=Path)
    restore_parser.add_argument("destination", nargs="?", type=Path)
    restore_parser.add_argument(
        "--snapshot",
        default="latest",
        help="Snapshot id to restore for directory stores. Defaults to latest.",
    )

    extract_parser = sub.add_parser("extract", help="Extract one file from a .smavg archive.")
    extract_parser.add_argument("archive", type=Path)
    extract_parser.add_argument("path", help="Relative path inside the archive.")
    extract_parser.add_argument("--out", required=True, type=Path, help="Output file path.")

    context_parser = sub.add_parser(
        "context",
        help="Create a deterministic AI-readable repetition map for a folder.",
    )
    context_parser.add_argument("source", type=Path)
    context_parser.add_argument("--out", type=Path, help="Output markdown context brief.")
    context_parser.add_argument("--json", type=Path, help="Output machine-readable context JSON.")
    context_parser.add_argument(
        "--budget",
        type=int,
        help="Approximate maximum token budget for the markdown brief.",
    )
    context_parser.add_argument(
        "--print",
        action="store_true",
        help="Print the markdown context brief to stdout.",
    )

    workflow_context_parser = sub.add_parser(
        "workflow-context",
        help="Create a deterministic context brief for a named repetitive workflow.",
    )
    workflow_context_parser.add_argument("name", nargs="?", help="Workflow profile name.")
    workflow_context_parser.add_argument("--list", action="store_true", help="List known workflow profiles.")
    workflow_context_parser.add_argument("--out", type=Path, help="Output markdown context brief.")
    workflow_context_parser.add_argument("--json", type=Path, help="Output machine-readable context JSON.")
    workflow_context_parser.add_argument(
        "--budget",
        type=int,
        help="Approximate maximum token budget for the markdown brief.",
    )
    workflow_context_parser.add_argument(
        "--print",
        action="store_true",
        help="Print the markdown context brief to stdout.",
    )

    preflight_parser = sub.add_parser(
        "preflight",
        help="Create a timestamped Smavg preflight brief before repeated agent work.",
    )
    preflight_target = preflight_parser.add_mutually_exclusive_group(required=True)
    preflight_target.add_argument(
        "--workflow",
        help="Named workflow profile, such as x-browsermcp.",
    )
    preflight_target.add_argument(
        "--source",
        type=Path,
        help="Folder to scan for a directory preflight.",
    )
    preflight_parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path.home() / ".codex" / "smavg-preflights",
        help="Base output directory for timestamped preflight artifacts.",
    )
    preflight_parser.add_argument(
        "--budget",
        type=int,
        default=3000,
        help="Approximate maximum token budget for the context brief.",
    )
    preflight_parser.add_argument(
        "--run-id",
        help="Optional explicit run directory name under --out-dir.",
    )

    gate_parser = sub.add_parser(
        "gate",
        help="Create a Smavg-only input packet for an agent task.",
    )
    gate_target = gate_parser.add_mutually_exclusive_group(required=True)
    gate_target.add_argument("--workflow", help="Named workflow profile, such as x-browsermcp.")
    gate_target.add_argument("--source", type=Path, help="Folder to gate for agent work.")
    gate_parser.add_argument("--task", required=True, help="Task the receiving agent should perform.")
    gate_parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path.home() / ".codex" / "smavg-gates",
        help="Base output directory for gate artifacts.",
    )
    gate_parser.add_argument(
        "--budget",
        type=int,
        default=3000,
        help="Approximate token budget for the context brief.",
    )
    gate_parser.add_argument("--run-id", help="Optional explicit run directory name under --out-dir.")
    gate_parser.add_argument("--json", action="store_true", help="Print JSON summary.")

    work_parser = sub.add_parser(
        "work",
        help="Run a Smavg-first work session: gate, receipt, task counter, ledger.",
    )
    work_sub = work_parser.add_subparsers(dest="work_command", required=True)
    work_start = work_sub.add_parser("start", help="Start a Smavg Work Mode session.")
    work_target = work_start.add_mutually_exclusive_group(required=True)
    work_target.add_argument("--workflow", help="Named workflow profile, such as x-browsermcp.")
    work_target.add_argument("--source", type=Path, help="Folder to use as Smavg work context.")
    work_start.add_argument("--task", required=True, help="Task to perform through Smavg Work Mode.")
    work_start.add_argument("--work-dir", type=Path, default=default_work_dir())
    work_start.add_argument("--tasks-dir", type=Path, default=default_tasks_dir())
    work_start.add_argument("--budget", type=int, default=3000)
    work_start.add_argument("--id", help="Optional explicit work id.")
    work_start.add_argument("--json", action="store_true")

    work_expand = work_sub.add_parser("expand", help="Expand an exact file and update the work receipt.")
    work_expand.add_argument("path", help="Relative path inside the Smavg context.")
    work_expand.add_argument("--work-id", help="Work id. Defaults to current work session.")
    work_expand.add_argument("--work-dir", type=Path, default=default_work_dir())
    work_expand.add_argument("--out", type=Path, help="Optional exact output path.")
    work_expand.add_argument("--json", action="store_true")

    work_note = work_sub.add_parser("note", help="Record visible user/assistant/tool text for this work session.")
    work_note.add_argument("--work-id", help="Work id. Defaults to current work session.")
    work_note.add_argument("--work-dir", type=Path, default=default_work_dir())
    work_note.add_argument("--role", required=True, choices=["user", "assistant", "tool-input", "tool-output", "note"])
    work_note_source = work_note.add_mutually_exclusive_group(required=True)
    work_note_source.add_argument("--text")
    work_note_source.add_argument("--file", type=Path)
    work_note.add_argument("--label")
    work_note.add_argument("--json", action="store_true")

    work_end = work_sub.add_parser("end", help="End work session and record one task event in the ledger.")
    work_end.add_argument("--work-id", help="Work id. Defaults to current work session.")
    work_end.add_argument("--work-dir", type=Path, default=default_work_dir())
    work_end.add_argument("--ledger", type=Path, default=default_ledger_path())
    work_end.add_argument("--no-ledger", action="store_true", help="Do not append the final task event to the ledger.")
    work_end.add_argument("--out", type=Path, help="Optional work markdown report output.")
    work_end.add_argument("--json", action="store_true")

    work_report = work_sub.add_parser("report", help="Print the current or selected work-session report.")
    work_report.add_argument("--work-id", help="Work id. Defaults to current work session.")
    work_report.add_argument("--work-dir", type=Path, default=default_work_dir())
    work_report.add_argument("--out", type=Path, help="Optional work markdown report output.")
    work_report.add_argument("--json", action="store_true")

    scan_parser = sub.add_parser(
        "scan",
        help="Read-only discovery scan for Smavg storage/context candidates.",
    )
    scan_parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        help="Root directory to scan. If omitted, runs the short Smavg product scan on the home folder.",
    )
    scan_parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path.home() / ".codex" / "smavg-scans",
        help="Base output directory for scan artifacts.",
    )
    scan_parser.add_argument("--run-id", help="Optional explicit run directory name.")
    scan_parser.add_argument("--recursive", action="store_true", help="Inspect child directories too.")
    scan_parser.add_argument("--max-depth", type=int, default=1, help="Recursive directory depth.")
    scan_parser.add_argument("--max-dirs", type=int, default=40, help="Maximum directories to analyze.")
    scan_parser.add_argument("--min-files", type=int, default=2, help="Minimum files for child candidates.")
    scan_parser.add_argument(
        "--max-files-per-dir",
        type=int,
        default=2000,
        help="Skip candidate dirs above this file count.",
    )
    scan_parser.add_argument(
        "--max-bytes-per-dir",
        type=int,
        default=100 * 1024 * 1024,
        help="Skip candidate dirs above this logical byte count.",
    )
    scan_parser.add_argument(
        "--budget",
        type=int,
        default=3000,
        help="Approximate token budget for generated context briefs.",
    )
    scan_parser.add_argument(
        "--no-workflows",
        action="store_true",
        help="Do not scan built-in workflow context profiles.",
    )
    scan_parser.add_argument("--json", action="store_true", help="Print JSON summary.")

    apply_parser = sub.add_parser(
        "apply",
        help="Apply a verified safe Smavg action. This never deletes source data.",
    )
    apply_parser.add_argument("source", type=Path, help="Source directory to safe-pack.")
    apply_parser.add_argument("--out", required=True, type=Path, help="Output .smavg archive.")
    apply_parser.add_argument(
        "--work-dir",
        type=Path,
        default=default_autopilot_dir() / "apply-work",
        help="Work directory for restore comparison.",
    )
    apply_parser.add_argument("--report", type=Path, help="Optional JSON report path.")
    apply_parser.add_argument("--quarantine-dir", type=Path, help="Optional quarantine directory.")
    apply_parser.add_argument(
        "--move-to-quarantine",
        action="store_true",
        help="Move source to quarantine after pack/verify/restore-compare passes.",
    )
    apply_parser.add_argument("--json", action="store_true", help="Print JSON report.")

    status_parser = sub.add_parser(
        "status",
        help="Show the short Smavg status card: saved today, all time, trust, latest scan.",
    )
    status_parser.add_argument("--out-dir", type=Path, default=default_autopilot_dir())
    status_parser.add_argument("--ledger", type=Path, default=default_ledger_path())
    status_parser.add_argument("--out", type=Path, help="Optional markdown status output.")
    status_parser.add_argument("--json", action="store_true", help="Print JSON status.")

    autopilot_parser = sub.add_parser(
        "autopilot",
        help="Run or verify the Smavg autopilot product shell.",
    )
    autopilot_sub = autopilot_parser.add_subparsers(dest="autopilot_command")
    autopilot_run = autopilot_sub.add_parser("run", help="Run the default Smavg autopilot scan.")
    autopilot_run.add_argument("--root", type=Path, default=Path.home())
    autopilot_run.add_argument("--out-dir", type=Path, default=default_autopilot_dir())
    autopilot_run.add_argument("--run-id")
    autopilot_run.add_argument("--budget", type=int, default=3000)
    autopilot_run.add_argument("--max-depth", type=int, default=1)
    autopilot_run.add_argument("--max-dirs", type=int, default=40)
    autopilot_run.add_argument("--no-surfaces", action="store_true")
    autopilot_run.add_argument("--no-workflows", action="store_true")
    autopilot_run.add_argument("--json", action="store_true")

    autopilot_verify = autopilot_sub.add_parser("verify", help="Verify latest Smavg autopilot artifacts.")
    autopilot_verify.add_argument("--out-dir", type=Path, default=default_autopilot_dir())
    autopilot_verify.add_argument("--ledger", type=Path, default=default_ledger_path())
    autopilot_verify.add_argument("--json", action="store_true")

    daemon_parser = sub.add_parser(
        "daemon",
        help="Run the safe local Smavg background scan/report loop.",
    )
    daemon_sub = daemon_parser.add_subparsers(dest="daemon_command", required=True)
    daemon_init = daemon_sub.add_parser("init", help="Write a safe read-only daemon config.")
    daemon_init.add_argument("--config", type=Path, default=default_daemon_config_path())
    daemon_init.add_argument("--root", type=Path, default=Path.home())
    daemon_init.add_argument("--daemon-dir", type=Path, default=default_daemon_dir())
    daemon_init.add_argument("--interval-seconds", type=int, default=6 * 60 * 60)
    daemon_init.add_argument("--budget", type=int, default=3000)
    daemon_init.add_argument("--max-depth", type=int, default=1)
    daemon_init.add_argument("--max-dirs", type=int, default=40)
    daemon_init.add_argument("--no-surfaces", action="store_true")
    daemon_init.add_argument("--no-workflows", action="store_true")
    daemon_init.add_argument("--json", action="store_true")

    daemon_once = daemon_sub.add_parser("once", help="Run one safe daemon cycle now.")
    daemon_once.add_argument("--config", type=Path, default=default_daemon_config_path())
    daemon_once.add_argument("--root", type=Path)
    daemon_once.add_argument("--daemon-dir", type=Path)
    daemon_once.add_argument("--run-id")
    daemon_once.add_argument("--budget", type=int)
    daemon_once.add_argument("--max-depth", type=int)
    daemon_once.add_argument("--max-dirs", type=int)
    daemon_once.add_argument("--no-surfaces", action="store_true")
    daemon_once.add_argument("--no-workflows", action="store_true")
    daemon_once.add_argument("--json", action="store_true")

    daemon_run = daemon_sub.add_parser("run", help="Run the safe daemon loop.")
    daemon_run.add_argument("--config", type=Path, default=default_daemon_config_path())
    daemon_run.add_argument("--cycles", type=int, help="Stop after this many cycles.")
    daemon_run.add_argument("--sleep-seconds", type=int, help="Override sleep between cycles.")
    daemon_run.add_argument("--json", action="store_true")

    daemon_status_parser = daemon_sub.add_parser("status", help="Show safe daemon state.")
    daemon_status_parser.add_argument("--daemon-dir", type=Path, default=default_daemon_dir())
    daemon_status_parser.add_argument("--config", type=Path, default=default_daemon_config_path())
    daemon_status_parser.add_argument("--out", type=Path, help="Optional markdown status output.")
    daemon_status_parser.add_argument("--json", action="store_true")

    daemon_service = daemon_sub.add_parser("service", help="Write a service-manager file without loading it.")
    daemon_service.add_argument("--config", type=Path, default=default_daemon_config_path())
    daemon_service.add_argument("--platform", choices=["auto", "launchd", "systemd", "windows"], default="auto")
    daemon_service.add_argument("--out", type=Path)
    daemon_service.add_argument("--interval-seconds", type=int)
    daemon_service.add_argument("--json", action="store_true")

    plugin_parser = sub.add_parser(
        "plugin",
        help="Build or verify the thin Smavg skill/MCP/plugin bundle.",
    )
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_command", required=True)
    plugin_build = plugin_sub.add_parser("build", help="Build the local Smavg agent bundle.")
    plugin_build.add_argument("--out-dir", type=Path, default=default_plugin_dir())
    plugin_build.add_argument("--smavg-command", default="smavg")
    plugin_build.add_argument("--python", help="Python executable for MCP examples.")
    plugin_build.add_argument("--force", action="store_true")
    plugin_build.add_argument("--json", action="store_true")

    plugin_verify = plugin_sub.add_parser("verify", help="Verify a Smavg agent bundle.")
    plugin_verify.add_argument("--path", type=Path, default=default_plugin_dir())
    plugin_verify.add_argument("--json", action="store_true")

    safe_pack_parser = sub.add_parser(
        "safe-pack",
        help="Pack, verify, restore-compare, and optionally quarantine a source directory.",
    )
    safe_pack_parser.add_argument("source", type=Path)
    safe_pack_parser.add_argument("--out", required=True, type=Path, help="Output .smavg archive.")
    safe_pack_parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path.home() / ".codex" / "smavg-safe-pack",
        help="Work directory for temporary restore verification.",
    )
    safe_pack_parser.add_argument(
        "--report",
        type=Path,
        help="Optional JSON report path. Markdown is written beside it.",
    )
    safe_pack_parser.add_argument("--quarantine-dir", type=Path, help="Directory for optional source quarantine.")
    safe_pack_parser.add_argument(
        "--move-to-quarantine",
        action="store_true",
        help="Move source to quarantine only after pack/verify/restore-compare passes.",
    )
    safe_pack_parser.add_argument("--json", action="store_true", help="Print JSON report.")

    receipt_parser = sub.add_parser(
        "receipt",
        help="Create a Smavg run receipt from a preflight or context JSON.",
    )
    receipt_source = receipt_parser.add_mutually_exclusive_group(required=True)
    receipt_source.add_argument("--preflight-json", type=Path, help="Preflight JSON to convert.")
    receipt_source.add_argument("--context-json", type=Path, help="Context JSON to convert.")
    receipt_parser.add_argument("--out", required=True, type=Path, help="Output receipt JSON path.")
    receipt_parser.add_argument("--markdown", type=Path, help="Output receipt markdown path.")
    receipt_parser.add_argument("--context-markdown", type=Path, help="Optional context markdown path.")
    receipt_parser.add_argument("--target-label", help="Optional target label for context JSON receipts.")

    ledger_parser = sub.add_parser(
        "ledger",
        help="Append and report Smavg lifetime benefit events.",
    )
    ledger_sub = ledger_parser.add_subparsers(dest="ledger_command", required=True)
    ledger_add_report = ledger_sub.add_parser("add-report", help="Append a known Smavg JSON report to the benefit ledger.")
    ledger_add_report.add_argument("report", type=Path)
    ledger_add_report.add_argument("--ledger", type=Path, default=default_ledger_path())
    ledger_add_report.add_argument("--kind", help="Override event kind.")
    ledger_add_report.add_argument("--label", help="Override event label.")
    ledger_add_report.add_argument("--surface", default="cli", help="Surface that produced the event.")
    ledger_add_report.add_argument("--json", action="store_true", help="Print appended event JSON.")

    ledger_import = ledger_sub.add_parser(
        "import-reports",
        help="Import supported Smavg JSON reports under a folder without double-counting components.",
    )
    ledger_import.add_argument("root", type=Path)
    ledger_import.add_argument("--ledger", type=Path, default=default_ledger_path())
    ledger_import.add_argument("--surface", default="cli", help="Surface that produced the events.")
    ledger_import.add_argument("--json", action="store_true", help="Print import summary JSON.")

    ledger_add = ledger_sub.add_parser("add", help="Append a manual benefit event.")
    ledger_add.add_argument("--kind", required=True)
    ledger_add.add_argument("--label", required=True)
    ledger_add.add_argument("--surface", default="cli")
    ledger_add.add_argument("--ledger", type=Path, default=default_ledger_path())
    ledger_add.add_argument("--before-tokens", type=int, default=0)
    ledger_add.add_argument("--after-tokens", type=int, default=0)
    ledger_add.add_argument("--before-disk-bytes", type=int, default=0)
    ledger_add.add_argument("--after-disk-bytes", type=int, default=0)
    ledger_add.add_argument("--artifact", action="append", default=[])
    ledger_add.add_argument("--note", action="append", default=[])
    ledger_add.add_argument("--verified", action="store_true")
    ledger_add.add_argument("--json", action="store_true", help="Print appended event JSON.")

    ledger_report_parser = ledger_sub.add_parser("report", help="Print Smavg lifetime benefit totals.")
    ledger_report_parser.add_argument("--ledger", type=Path, default=default_ledger_path())
    ledger_report_parser.add_argument("--period", choices=["day", "week", "month", "year", "all"], default="all")
    ledger_report_parser.add_argument("--out", type=Path, help="Optional markdown report output.")
    ledger_report_parser.add_argument("--json", action="store_true", help="Emit JSON report.")

    ledger_list = ledger_sub.add_parser("list", help="List recent ledger events.")
    ledger_list.add_argument("--ledger", type=Path, default=default_ledger_path())
    ledger_list.add_argument("--limit", type=int, default=20)
    ledger_list.add_argument("--json", action="store_true")

    task_parser = sub.add_parser(
        "task",
        help="Track visible task/session tokens and Smavg reports.",
    )
    task_sub = task_parser.add_subparsers(dest="task_command", required=True)
    task_start = task_sub.add_parser("start", help="Start a Smavg task session counter.")
    task_start.add_argument("label")
    task_start.add_argument("--surface", default="codex")
    task_start.add_argument("--tasks-dir", type=Path, default=default_tasks_dir())
    task_start.add_argument("--id", help="Optional explicit task id.")
    task_start.add_argument("--json", action="store_true")

    task_add = task_sub.add_parser("add", help="Add visible user/assistant/tool text to a task.")
    task_add.add_argument("--task-id", help="Task id. Defaults to current task.")
    task_add.add_argument("--tasks-dir", type=Path, default=default_tasks_dir())
    task_add.add_argument("--role", required=True, choices=["user", "assistant", "tool-input", "tool-output", "note"])
    text_source = task_add.add_mutually_exclusive_group(required=True)
    text_source.add_argument("--text")
    text_source.add_argument("--file", type=Path)
    task_add.add_argument("--label")
    task_add.add_argument("--json", action="store_true")

    task_add_report = task_sub.add_parser("add-report", help="Attach a Smavg JSON report to a task.")
    task_add_report.add_argument("report", type=Path)
    task_add_report.add_argument("--task-id", help="Task id. Defaults to current task.")
    task_add_report.add_argument("--tasks-dir", type=Path, default=default_tasks_dir())
    task_add_report.add_argument("--kind")
    task_add_report.add_argument("--label")
    task_add_report.add_argument("--surface", default="cli")
    task_add_report.add_argument("--json", action="store_true")

    task_end = task_sub.add_parser("end", help="End a task and append its summary to the benefit ledger.")
    task_end.add_argument("--task-id", help="Task id. Defaults to current task.")
    task_end.add_argument("--tasks-dir", type=Path, default=default_tasks_dir())
    task_end.add_argument("--ledger", type=Path, default=default_ledger_path())
    task_end.add_argument("--no-ledger", action="store_true", help="Do not append the final task event to the ledger.")
    task_end.add_argument("--out", type=Path, help="Optional markdown task report output.")
    task_end.add_argument("--json", action="store_true")

    task_report = task_sub.add_parser("report", help="Print a current or saved task report.")
    task_report.add_argument("--task-id", help="Task id. Defaults to current task.")
    task_report.add_argument("--tasks-dir", type=Path, default=default_tasks_dir())
    task_report.add_argument("--out", type=Path, help="Optional markdown task report output.")
    task_report.add_argument("--json", action="store_true")

    sub.add_parser(
        "mcp-server",
        help="Run the dependency-free Smavg MCP stdio server.",
    )

    expand_context_parser = sub.add_parser(
        "expand-context",
        help="Restore one exact file from a Smavg context JSON after hash verification.",
    )
    expand_context_parser.add_argument("context_json", type=Path)
    expand_context_parser.add_argument("path", help="Relative path in the context source folder.")
    expand_context_parser.add_argument("--out", required=True, type=Path, help="Output file path.")
    expand_context_parser.add_argument(
        "--receipt",
        type=Path,
        help="Optional Smavg receipt JSON to update with this exact expansion.",
    )

    verify_parser = sub.add_parser("verify", help="Compare stored files or verify a .smavg archive.")
    verify_parser.add_argument("source", type=Path)
    verify_parser.add_argument(
        "--snapshot",
        help="Verify a snapshot against the source directory.",
    )

    verify_snapshot_parser = sub.add_parser(
        "verify-snapshot",
        help="Verify a snapshot can be reconstructed from the archive.",
    )
    verify_snapshot_parser.add_argument(
        "--snapshot",
        default="latest",
        help="Snapshot id to verify. Defaults to latest.",
    )

    stats_parser = sub.add_parser("stats", help="Print measured store stats.")
    stats_parser.add_argument("--json", action="store_true", help="Emit JSON.")

    report_parser = sub.add_parser("report", help="Print a human-readable snapshot or .smavg report.")
    report_parser.add_argument("archive", nargs="?", type=Path, help="Optional .smavg archive path.")
    report_parser.add_argument("--snapshot", default="latest", help="Snapshot id. Defaults to latest.")
    report_parser.add_argument("--json", action="store_true", help="Emit JSON.")

    sub.add_parser("list", help="List stored files.")
    sub.add_parser("snapshots", help="List archive snapshots.")

    bench_parser = sub.add_parser("benchmark", help="Import, verify, and print before/after sizes.")
    bench_parser.add_argument("source", type=Path)
    bench_parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the target store before benchmarking.",
    )

    gauntlet_parser = sub.add_parser(
        "gauntlet",
        help="Run real-corpus archive, restore, diff, and baseline checks.",
    )
    gauntlet_parser.add_argument("source", nargs="*", type=Path)
    gauntlet_parser.add_argument(
        "--preset",
        choices=["stage1-local-safe", "stage2-local-reality", "stage3-public", "all"],
        help="Add a curated gauntlet stage.",
    )
    gauntlet_parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output directory for archives, restores, JSON, and markdown report.",
    )
    gauntlet_parser.add_argument(
        "--baselines",
        choices=["none", "quick", "thorough"],
        default="thorough",
        help="Baseline compressor mode. Defaults to thorough.",
    )
    gauntlet_parser.add_argument(
        "--keep-baselines",
        action="store_true",
        help="Keep baseline compressed tar files after measuring them.",
    )
    gauntlet_parser.add_argument(
        "--allow-sensitive",
        action="store_true",
        help="Allow known-sensitive roots. Use only for explicitly approved local tests.",
    )
    gauntlet_parser.add_argument("--json", action="store_true", help="Print JSON summary.")

    codex_gauntlet_parser = sub.add_parser(
        "codex-gauntlet",
        help="Measure Smavg token savings and exact-file quality on local Codex workloads.",
    )
    codex_gauntlet_parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output directory for contexts, exact expansions, JSON, and markdown report.",
    )
    codex_gauntlet_parser.add_argument(
        "--budget",
        type=int,
        default=3000,
        help="Approximate token budget for each context brief.",
    )
    codex_gauntlet_parser.add_argument(
        "--repeat-count",
        type=int,
        default=3,
        help="Repeated-work count used for setup-token savings.",
    )
    codex_gauntlet_parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the output directory before running.",
    )
    codex_gauntlet_parser.add_argument("--json", action="store_true", help="Print JSON summary.")

    gate_gauntlet_parser = sub.add_parser(
        "gate-gauntlet",
        help="Run strict Smavg gate packet, receipt, and evidence checks.",
    )
    gate_gauntlet_parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output directory for gate packets, receipts, JSON, and markdown report.",
    )
    gate_gauntlet_parser.add_argument(
        "--budget",
        type=int,
        default=3000,
        help="Approximate token budget for each gate context brief.",
    )
    gate_gauntlet_parser.add_argument(
        "--repeat-count",
        type=int,
        default=3,
        help="Repeated-work count used for setup-token savings.",
    )
    gate_gauntlet_parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the output directory before running.",
    )
    gate_gauntlet_parser.add_argument("--json", action="store_true", help="Print JSON summary.")

    surfaces_parser = sub.add_parser(
        "surfaces",
        help="Inventory local skills, plugins, MCP/config surfaces, workflows, and memories.",
    )
    surfaces_sub = surfaces_parser.add_subparsers(dest="surfaces_command", required=True)
    surfaces_scan = surfaces_sub.add_parser("scan", help="Write a local Smavg surface registry.")
    surfaces_scan.add_argument(
        "--out-dir",
        type=Path,
        default=Path.home() / ".smavg" / "surfaces",
        help="Base output directory for surface registry artifacts.",
    )
    surfaces_scan.add_argument("--run-id", help="Optional explicit registry run id.")
    surfaces_scan.add_argument("--budget", type=int, default=3000, help="Token budget for each context brief.")
    surfaces_scan.add_argument("--json", action="store_true", help="Print registry JSON.")

    surfaces_report = surfaces_sub.add_parser("report", help="Render a saved surface registry JSON.")
    surfaces_report.add_argument("registry", type=Path, help="Path to surfaces.json.")
    surfaces_report.add_argument("--out", type=Path, help="Optional markdown output path.")
    surfaces_report.add_argument("--json", action="store_true", help="Print raw registry JSON.")

    surface_gauntlet_parser = sub.add_parser(
        "surface-gauntlet",
        help="Verify Smavg context/exact expansion across local skills, plugins, MCP configs, workflows, and memories.",
    )
    surface_gauntlet_parser.add_argument("--out", required=True, type=Path, help="Output directory for gauntlet artifacts.")
    surface_gauntlet_parser.add_argument("--budget", type=int, default=3000, help="Token budget for each context brief.")
    surface_gauntlet_parser.add_argument(
        "--repeat-count",
        type=int,
        default=3,
        help="Repeated-work count used for setup-token savings.",
    )
    surface_gauntlet_parser.add_argument("--reset", action="store_true", help="Delete and recreate --out before running.")
    surface_gauntlet_parser.add_argument("--json", action="store_true", help="Print JSON report.")

    demo_parser = sub.add_parser("demo", help="Generate similar local reports and benchmark them.")
    demo_parser.add_argument("workdir", type=Path)
    demo_parser.add_argument("--count", type=int, default=160)
    demo_parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the demo workdir before running.",
    )

    kev_parser = sub.add_parser(
        "fetch-cisa-kev",
        help="Download the real CISA KEV feed and write one JSON file per record.",
    )
    kev_parser.add_argument("output", type=Path)
    kev_parser.add_argument("--limit", type=int)
    kev_parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the output directory before fetching.",
    )

    kev_bench = sub.add_parser(
        "benchmark-cisa-kev",
        help="Download the real CISA KEV feed, import it, verify it, and report measured sizes.",
    )
    kev_bench.add_argument("workdir", type=Path)
    kev_bench.add_argument("--limit", type=int)
    kev_bench.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the workdir before benchmarking.",
    )

    nvd_parser = sub.add_parser(
        "fetch-nvd-cve",
        help="Download an official NVD CVE 2.0 feed and write one JSON file per record.",
    )
    nvd_parser.add_argument("output", type=Path)
    nvd_parser.add_argument("--feed", default="recent", help="recent, modified, or a year like 2026.")
    nvd_parser.add_argument("--limit", type=int)
    nvd_parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the output directory before fetching.",
    )

    nvd_bench = sub.add_parser(
        "benchmark-nvd-cve",
        help="Download an official NVD CVE 2.0 feed, import it, verify it, and report measured sizes.",
    )
    nvd_bench.add_argument("workdir", type=Path)
    nvd_bench.add_argument("--feed", default="recent", help="recent, modified, or a year like 2026.")
    nvd_bench.add_argument("--limit", type=int)
    nvd_bench.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the workdir before benchmarking.",
    )

    git_parser = sub.add_parser(
        "fetch-git-history",
        help="Extract exact historical versions of real files from a local Git repo.",
    )
    git_parser.add_argument("repo", type=Path)
    git_parser.add_argument("output", type=Path)
    git_parser.add_argument("--path", action="append", required=True)
    git_parser.add_argument("--limit", type=int)
    git_parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the output directory before extracting.",
    )

    git_bench = sub.add_parser(
        "benchmark-git-history",
        help="Extract real Git file histories, import them, verify them, and report measured sizes.",
    )
    git_bench.add_argument("repo", type=Path)
    git_bench.add_argument("workdir", type=Path)
    git_bench.add_argument("--path", action="append", required=True)
    git_bench.add_argument("--limit", type=int)
    git_bench.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the workdir before benchmarking.",
    )

    loghub_parser = sub.add_parser(
        "fetch-loghub",
        help="Download real Loghub 2k raw log files.",
    )
    loghub_parser.add_argument("output", type=Path)
    loghub_parser.add_argument(
        "--name",
        action="append",
        choices=sorted(LOGHUB_2K_FILES),
        help="Dataset name. Can be repeated. Defaults to several small real log datasets.",
    )
    loghub_parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the output directory before fetching.",
    )

    loghub_bench = sub.add_parser(
        "benchmark-loghub",
        help="Download real Loghub logs, import them, verify them, and report measured sizes.",
    )
    loghub_bench.add_argument("workdir", type=Path)
    loghub_bench.add_argument(
        "--name",
        action="append",
        choices=sorted(LOGHUB_2K_FILES),
        help="Dataset name. Can be repeated. Defaults to several small real log datasets.",
    )
    loghub_bench.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the workdir before benchmarking.",
    )

    weather_parser = sub.add_parser(
        "fetch-weather-csv",
        help="Download real public historical daily weather CSV files.",
    )
    weather_parser.add_argument("output", type=Path)
    weather_parser.add_argument("--city-id", action="append")
    weather_parser.add_argument("--limit", type=int)
    weather_parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the output directory before fetching.",
    )

    weather_bench = sub.add_parser(
        "benchmark-weather-csv",
        help="Download real weather CSV files, import them, verify them, and report measured sizes.",
    )
    weather_bench.add_argument("workdir", type=Path)
    weather_bench.add_argument("--city-id", action="append")
    weather_bench.add_argument("--limit", type=int)
    weather_bench.add_argument(
        "--reset",
        action="store_true",
        help="Delete and recreate the workdir before benchmarking.",
    )

    return parser


def generate_demo_docs(source: Path, count: int) -> None:
    source.mkdir(parents=True, exist_ok=True)
    for index in range(1, count + 1):
        day = ((index - 1) % 28) + 1
        risk_score = 40 + (index % 17)
        incidents = index % 5
        lines = [
            f"# Weekly Operations Report {index:03d}",
            "",
            f"Report date: 2026-05-{day:02d}",
            f"Risk score: {risk_score}",
            f"Open incidents: {incidents}",
            "",
            "## Executive Summary",
            "The operating picture remains stable across the monitored estate.",
            "The same reporting template is used every week for comparability.",
            "Only measured operational values change between these files.",
            "",
        ]

        for section in range(1, 90):
            lines.extend(
                [
                    f"### Control {section:02d}",
                    (
                        f"Control {section:02d} evidence text remains stable "
                        "for comparison across weekly versions."
                    ),
                    f"Evidence location: local archive control-{section:02d}.",
                    f"Decision: continue operating posture for control {section:02d}.",
                    f"Measured value: {(section * 7 + index) % 101}",
                    "",
                ]
            )

        lines.extend(
            [
                "## Closing Notes",
                "The next report should preserve this structure.",
                "Byte-perfect reconstruction is required for audit use.",
                "",
            ]
        )
        (source / f"report-{index:03d}.md").write_text("\n".join(lines), encoding="utf-8")


def run_benchmark(store: SmavgStore, source: Path, reset: bool = False) -> int:
    if reset:
        store.reset()
    else:
        store.init()

    source = source.resolve()
    before_apparent = apparent_size(source)
    before_disk = disk_size(source)
    results = store.import_dir(source)
    ok, failures = store.verify_dir(source)
    store.compact()
    stats = store.stats()

    print(f"Source: {source}")
    print(f"Imported files: {len(results)}")
    print(f"Original apparent bytes: {before_apparent} ({human_bytes(before_apparent)})")
    print(f"Original disk bytes: {before_disk} ({human_bytes(before_disk)})")
    print(
        "Smavg store apparent bytes: "
        f"{stats['store_apparent_bytes']} ({human_bytes(int(stats['store_apparent_bytes']))})"
    )
    print(
        "Smavg store disk bytes: "
        f"{stats['store_disk_bytes']} ({human_bytes(int(stats['store_disk_bytes']))})"
    )
    print(f"Payload bytes: {stats['payload_bytes']} ({human_bytes(int(stats['payload_bytes']))})")
    print(f"Object modes: {stats.get('object_modes', {})}")
    print(f"Snapshot pack file modes: {stats.get('snapshot_pack_file_modes', {})}")
    print(f"Byte-perfect verify: {'PASS' if ok else 'FAIL'}")

    apparent_smaller = int(stats["store_apparent_bytes"]) < before_apparent
    disk_smaller = int(stats["store_disk_bytes"]) < before_disk
    print(f"Apparent-size pass: {'PASS' if apparent_smaller else 'FAIL'}")
    print(f"Disk-size pass: {'PASS' if disk_smaller else 'FAIL'}")

    if failures:
        print("Failures:")
        for failure in failures[:20]:
            print(f"  {failure}")
        if len(failures) > 20:
            print(f"  ... {len(failures) - 20} more")
    return 0 if ok and apparent_smaller else 1


def command_main(args: argparse.Namespace) -> int:
    store = SmavgStore(Path(args.store), enable_json_templates=not args.no_json_template)

    if args.command == "init":
        store.init()
        print(f"Initialized Smavg store at {store.root}")
        return 0

    if args.command == "pack":
        try:
            report = pack_container(args.source, args.out)
        except ContainerError as exc:
            print(f"Pack failed: {exc}", file=sys.stderr)
            return 1
        print_container_report(report)
        return 0

    if args.command == "archive":
        before_apparent = apparent_size(args.source)
        before_disk = disk_size(args.source)
        result = store.archive_dir(args.source, snapshot_id=args.snapshot_id)
        ok, failures = store.verify_snapshot_against_dir(result.snapshot_id, args.source)
        store.compact()
        stats = store.stats()
        print(f"Snapshot: {result.snapshot_id}")
        print(f"Source: {result.source}")
        print(f"Files: {result.file_count}")
        print(f"Original apparent bytes: {before_apparent} ({human_bytes(before_apparent)})")
        print(f"Original disk bytes: {before_disk} ({human_bytes(before_disk)})")
        print(
            "Smavg store apparent bytes: "
            f"{stats['store_apparent_bytes']} ({human_bytes(int(stats['store_apparent_bytes']))})"
        )
        print(
            "Smavg store disk bytes: "
            f"{stats['store_disk_bytes']} ({human_bytes(int(stats['store_disk_bytes']))})"
        )
        print(f"Payload bytes: {stats['payload_bytes']} ({human_bytes(int(stats['payload_bytes']))})")
        print(f"Modes: {result.modes}")
        if result.plan:
            print_plan_summary(result.plan)
        print(f"Byte-perfect verify: {'PASS' if ok else 'FAIL'}")
        if failures:
            for failure in failures[:20]:
                print(failure)
        return 0 if ok else 1

    if args.command == "import":
        results = store.import_dir(args.source)
        print(f"Imported {len(results)} files into {store.root}")
        return 0

    if args.command == "put":
        result = store.put_file(args.source, args.path)
        print(
            f"Stored {result.path} as object {result.object_id} "
            f"({result.mode}, {result.stored_size} bytes)"
        )
        return 0

    if args.command == "get":
        store.write_file(args.path, args.destination)
        print(f"Restored {args.path} to {args.destination}")
        return 0

    if args.command == "export":
        count = store.export_dir(args.destination)
        print(f"Exported {count} files to {args.destination}")
        return 0

    if args.command == "restore":
        if args.destination is not None:
            try:
                count = restore_container(args.target, args.destination)
            except ContainerError as exc:
                print(f"Restore failed: {exc}", file=sys.stderr)
                return 1
            print(f"Restored archive {args.target} to {args.destination}")
            print(f"Files: {count}")
            return 0
        snapshot_id = store.resolve_snapshot_id(args.snapshot)
        count = store.restore_snapshot(snapshot_id, args.target)
        print(f"Restored snapshot {snapshot_id} to {args.target}")
        print(f"Files: {count}")
        return 0

    if args.command == "extract":
        try:
            size = extract_container_file(args.archive, args.path, args.out)
        except ContainerError as exc:
            print(f"Extract failed: {exc}", file=sys.stderr)
            return 1
        print(f"Extracted {args.path} to {args.out}")
        print(f"Bytes: {size}")
        return 0

    if args.command == "context":
        if args.out is None and args.json is None and not args.print:
            args.print = True
        try:
            report = build_context_report(args.source, budget_tokens=args.budget)
            write_context_outputs(report, args.out, args.json)
        except ContextError as exc:
            print(f"Context failed: {exc}", file=sys.stderr)
            return 1
        if args.print:
            print(render_context_markdown(report))
        else:
            print_context_report(report)
            if args.out is not None:
                print(f"Markdown: {args.out}")
            if args.json is not None:
                print(f"JSON: {args.json}")
        return 0

    if args.command == "workflow-context":
        if args.list:
            for profile in available_workflow_profiles():
                print(f"{profile['name']}: {profile['description']} ({profile['files']} files)")
            return 0
        if not args.name:
            print("Workflow context failed: missing workflow profile name", file=sys.stderr)
            return 1
        if args.out is None and args.json is None and not args.print:
            args.print = True
        try:
            report = build_workflow_context_report(args.name, budget_tokens=args.budget)
            write_context_outputs(report, args.out, args.json)
        except ContextError as exc:
            print(f"Workflow context failed: {exc}", file=sys.stderr)
            return 1
        if args.print:
            print(render_context_markdown(report))
        else:
            print_context_report(report)
            workflow = report.get("workflow", {})
            if workflow:
                print(f"Workflow: {workflow.get('name')}")
                print(f"Workflow files available: {workflow.get('available_files')}/{workflow.get('requested_files')}")
            if args.out is not None:
                print(f"Markdown: {args.out}")
            if args.json is not None:
                print(f"JSON: {args.json}")
        return 0

    if args.command == "preflight":
        try:
            summary = run_preflight(
                out_dir=args.out_dir,
                source=args.source,
                workflow=args.workflow,
                budget_tokens=args.budget,
                run_id=args.run_id,
            )
        except ContextError as exc:
            print(f"Preflight failed: {exc}", file=sys.stderr)
            return 1
        print(f"Smavg preflight: {summary['target_label']}")
        print(f"Run dir: {summary['run_dir']}")
        print(f"Context brief: {summary['context_markdown']}")
        print(f"Context JSON: {summary['context_json']}")
        print(f"Preflight summary: {summary['preflight_markdown']}")
        print(f"Run receipt: {summary['receipt_markdown']}")
        print(f"Receipt JSON: {summary['receipt_json']}")
        print(f"Raw setup tokens estimate: {summary['raw_tokens_estimate']}")
        print(f"Brief tokens estimate: {summary['brief_tokens_estimate']}")
        ratio = summary.get("token_reduction_ratio")
        print(f"Token reduction: {'n/a' if ratio is None else f'{ratio}x'}")
        assessment = summary.get("assessment", {})
        print(f"Assessment: {assessment.get('status', 'unknown')}")
        print(f"Recommendation: {assessment.get('recommendation', 'not evaluated')}")
        recommended = summary.get("recommended_expansions", [])
        if recommended:
            print("Recommended exact expansions:")
            for item in recommended[:5]:
                print(f"  {item['path']}: {item['expand_command']}")
        return 0

    if args.command == "gate":
        try:
            gate = run_gate(
                out_dir=args.out_dir,
                source=args.source,
                workflow=args.workflow,
                task=args.task,
                budget_tokens=args.budget,
                run_id=args.run_id,
            )
        except (GateError, ContextError) as exc:
            print(f"Gate failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(gate, indent=2, sort_keys=True))
        else:
            files = gate["files"]
            measurement = gate["measurement"]
            ratio = measurement.get("token_reduction_ratio")
            print(f"Smavg gate: {gate['target_label']}")
            print(f"Task: {gate['task']}")
            print(f"Run dir: {gate['run_dir']}")
            print(f"Gate packet: {files['gate_markdown']}")
            print(f"Gate JSON: {files['gate_json']}")
            print(f"Context brief: {files['context_markdown']}")
            print(f"Receipt JSON: {files['receipt_json']}")
            print(f"Raw setup tokens estimate: {measurement['raw_tokens_estimate']}")
            print(f"Brief tokens estimate: {measurement['brief_tokens_estimate']}")
            print(f"Token reduction: {'n/a' if ratio is None else f'{ratio}x'}")
            print("Full raw source supplied by Smavg: NO")
            recommended = gate.get("recommended_expansions", [])
            if recommended:
                print("Receipt-aware exact expansion commands:")
                for item in recommended[:5]:
                    print(f"  {item['path']}: {item['expand_command']}")
        return 0

    if args.command == "surfaces":
        try:
            if args.surfaces_command == "scan":
                registry = scan_surfaces(
                    out_dir=args.out_dir,
                    run_id=args.run_id,
                    budget_tokens=args.budget,
                )
                if args.json:
                    print(json.dumps(registry, indent=2, sort_keys=True))
                else:
                    summary = registry["summary"]
                    print("Smavg surface registry")
                    print(f"Run dir: {registry['run_dir']}")
                    print(f"Surfaces: {summary['surfaces']}")
                    print(f"Context groups: {summary['context_groups']}")
                    print(f"Config summaries: {summary['config_summaries']}")
                    print(f"Raw tokens estimate: {summary['raw_tokens_estimate']}")
                    print(f"Brief tokens estimate: {summary['brief_tokens_estimate']}")
                    ratio = summary.get("token_reduction_ratio")
                    print(f"Registry context reduction: {'n/a' if ratio is None else f'{ratio}x'}")
                    print(f"Registry Markdown: {registry['surfaces_markdown']}")
                    print(f"Registry JSON: {registry['surfaces_json']}")
                return 0
            if args.surfaces_command == "report":
                registry = json.loads(args.registry.read_text(encoding="utf-8"))
                if args.out is not None:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(render_surface_registry_markdown(registry), encoding="utf-8")
                if args.json:
                    print(json.dumps(registry, indent=2, sort_keys=True))
                else:
                    summary = registry.get("summary", {})
                    print("Smavg surface registry")
                    print(f"Surfaces: {summary.get('surfaces', 0)}")
                    print(f"Context groups: {summary.get('context_groups', 0)}")
                    print(f"Config summaries: {summary.get('config_summaries', 0)}")
                    ratio = summary.get("token_reduction_ratio")
                    print(f"Registry context reduction: {'n/a' if ratio is None else f'{ratio}x'}")
                    if args.out is not None:
                        print(f"Registry Markdown: {args.out}")
                return 0
        except (SurfaceError, ContextError, OSError, json.JSONDecodeError) as exc:
            print(f"Surfaces failed: {exc}", file=sys.stderr)
            return 1

    if args.command == "surface-gauntlet":
        try:
            report = run_surface_gauntlet(
                args.out,
                budget_tokens=args.budget,
                repeat_count=args.repeat_count,
                reset=args.reset,
            )
        except (SurfaceError, ContextError, OSError, json.JSONDecodeError) as exc:
            print(f"Surface gauntlet failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            summary = report["summary"]
            print("Smavg surface gauntlet")
            print(f"Output: {args.out}")
            print(f"Surfaces inventoried: {summary['surfaces']}")
            print(f"Context groups: {summary['context_groups']}")
            print(f"Verified groups: {summary['verified_groups']}/{summary['context_groups']}")
            print(f"Useful groups: {summary['useful_groups']}/{summary['context_groups']}")
            print(f"Exact expansion: {summary['exact_expansion_pass']}/{summary['exact_expansion_total']}")
            print(f"Configured unverified surfaces: {summary['configured_unverified_surfaces']}")
            print(f"Raw tokens estimate: {summary['raw_tokens_estimate']}")
            print(f"Smavg supplied tokens estimate: {summary['smavg_supplied_tokens_estimate']}")
            ratio = summary.get("first_time_reduction_ratio")
            repeated = summary.get("repeated_reduction_ratio")
            print(f"First-time reduction: {'n/a' if ratio is None else f'{ratio}x'}")
            print(f"Repeated-work reduction: {'n/a' if repeated is None else f'{repeated}x'}")
            print("Full raw source supplied by Smavg: NO")
            print(f"Report Markdown: {args.out / 'report.md'}")
            print(f"Report JSON: {args.out / 'results.json'}")
        return 0

    if args.command == "scan":
        if args.root is None:
            try:
                report = run_autopilot_scan(
                    root=Path.home(),
                    out_dir=default_autopilot_dir(),
                    run_id=args.run_id,
                    budget_tokens=args.budget,
                    recursive=args.recursive or True,
                    max_depth=args.max_depth,
                    max_dirs=args.max_dirs,
                    include_workflows=not args.no_workflows,
                )
            except (AutopilotError, ScanError, SurfaceError, ContextError, OSError, json.JSONDecodeError) as exc:
                print(f"Scan failed: {exc}", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                summary = report["summary"]
                print("Smavg scan")
                print(f"Root: {report['root']}")
                print(f"Run dir: {report['run_dir']}")
                print(f"Directory candidates: {summary['directory_candidates']}")
                print(f"Workflow candidates: {summary['workflow_candidates']}")
                print(f"Surfaces inventoried: {summary['surfaces']}")
                print(f"Surface context groups: {summary['surface_context_groups']}")
                best_dir = summary.get("best_directory_token_reduction")
                best_workflow = summary.get("best_workflow_token_reduction")
                print(f"Best directory reduction: {'n/a' if best_dir is None else f'{best_dir}x'}")
                print(f"Best workflow reduction: {'n/a' if best_workflow is None else f'{best_workflow}x'}")
                ratio = summary.get("surface_token_reduction_ratio")
                print(f"Surface registry reduction: {'n/a' if ratio is None else f'{ratio}x'}")
                print("Cleanup performed: NO")
                print(f"Report: {report['report_markdown']}")
            return 0
        try:
            summary = run_scan(
                root=args.root,
                out_dir=args.out_dir,
                run_id=args.run_id,
                recursive=args.recursive,
                max_depth=args.max_depth,
                max_dirs=args.max_dirs,
                min_files=args.min_files,
                max_files_per_dir=args.max_files_per_dir,
                max_bytes_per_dir=args.max_bytes_per_dir,
                budget_tokens=args.budget,
                include_workflows=not args.no_workflows,
            )
        except ScanError as exc:
            print(f"Scan failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            print(f"Smavg scan: {summary['root']}")
            print(f"Run dir: {summary['run_dir']}")
            print(f"Scan report: {summary['scan_markdown']}")
            print(f"Scan JSON: {summary['scan_json']}")
            print(f"Directories analyzed: {summary['directories_analyzed']}")
            print(f"Directory candidates: {summary['directory_candidates']}")
            print(f"Workflow candidates: {summary['workflow_candidates']}")
            print(f"Skipped directories: {summary['skipped_directories']}")
            print("Cleanup performed: NO")
        return 0

    if args.command == "apply":
        try:
            report = apply_safe_action(
                source=args.source,
                archive=args.out,
                work_dir=args.work_dir,
                report_path=args.report,
                quarantine_dir=args.quarantine_dir,
                move_to_quarantine=args.move_to_quarantine,
            )
        except (AutopilotError, SafePackError, ContainerError) as exc:
            print(f"Apply failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            archive_report = report["archive_report"]
            compare = report["restore_compare"]
            cleanup = report.get("cleanup_projection", {})
            purge = cleanup.get("purge_projection", {})
            tokens = cleanup.get("token_projection", {})
            print("Smavg apply")
            print(f"Source: {report['source']}")
            print(f"Archive: {report['archive']}")
            print(f"Files: {archive_report['file_count']}")
            print(f"Archive verify: {'PASS' if report.get('archive_verify', {}).get('pass') else 'FAIL'}")
            print(f"Restore compare: {'PASS' if compare.get('pass') else 'FAIL'}")
            print(f"Source moved to quarantine: {'YES' if report['source_moved_to_quarantine'] else 'NO'}")
            print(f"Delete performed: {'YES' if report.get('delete_performed') else 'NO'}")
            print(f"Net disk saved after purge while keeping archive: {human_bytes(int(purge.get('net_disk_bytes_saved_after_purge_and_archive_kept', 0)))}")
            ratio = tokens.get("token_reduction_ratio")
            print(f"Token reduction if agent uses Smavg brief: {'n/a' if ratio is None else f'{ratio}x'}")
            if args.report is not None:
                print(f"Report JSON: {args.report}")
                print(f"Report Markdown: {args.report.with_suffix('.md')}")
        return 0

    if args.command == "status":
        try:
            status = autopilot_status(out_dir=args.out_dir, ledger_path=args.ledger)
        except (AutopilotError, LedgerError, OSError, json.JSONDecodeError) as exc:
            print(f"Status failed: {exc}", file=sys.stderr)
            return 1
        if args.out is not None:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(render_status_markdown(status), encoding="utf-8")
        if args.json:
            print(json.dumps(status, indent=2, sort_keys=True))
        else:
            ledger = status.get("ledger", {})
            today = ledger.get("today", {}) if isinstance(ledger, dict) else {}
            all_time = ledger.get("all", {}) if isinstance(ledger, dict) else {}
            print("Smavg status")
            print(f"Tokens saved today: {today.get('tokens_saved', 0)}")
            print(f"Tokens saved all time: {all_time.get('tokens_saved', 0)}")
            print(f"Repeated-work tokens saved all time: {all_time.get('repeated_tokens_saved', 0)}")
            print(f"Disk saved all time: {human_bytes(int(all_time.get('disk_bytes_saved', 0)))}")
            print(f"Exact expansion: {all_time.get('exact_expansion_pass', 0)}/{all_time.get('exact_expansion_total', 0)}")
            print(f"Failures counted as wins: {all_time.get('failures_counted_as_wins', 0)}")
            latest = status.get("latest_scan")
            if isinstance(latest, dict):
                print(f"Latest scan: {latest.get('report_markdown')}")
            else:
                print("Latest scan: none")
            if args.out is not None:
                print(f"Status Markdown: {args.out}")
        return 0

    if args.command == "autopilot":
        command = args.autopilot_command or "run"
        if command == "run":
            try:
                report = run_autopilot_scan(
                    root=getattr(args, "root", Path.home()),
                    out_dir=getattr(args, "out_dir", default_autopilot_dir()),
                    run_id=getattr(args, "run_id", None),
                    budget_tokens=getattr(args, "budget", 3000),
                    recursive=True,
                    max_depth=getattr(args, "max_depth", 1),
                    max_dirs=getattr(args, "max_dirs", 40),
                    include_surfaces=not getattr(args, "no_surfaces", False),
                    include_workflows=not getattr(args, "no_workflows", False),
                )
            except (AutopilotError, ScanError, SurfaceError, ContextError, OSError, json.JSONDecodeError) as exc:
                print(f"Autopilot failed: {exc}", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                summary = report["summary"]
                print("Smavg autopilot")
                print(f"Run dir: {report['run_dir']}")
                print(f"Directory candidates: {summary['directory_candidates']}")
                print(f"Workflow candidates: {summary['workflow_candidates']}")
                print(f"Surfaces inventoried: {summary['surfaces']}")
                ratio = summary.get("surface_token_reduction_ratio")
                print(f"Surface registry reduction: {'n/a' if ratio is None else f'{ratio}x'}")
                print(f"Report: {report['report_markdown']}")
            return 0
        if command == "verify":
            try:
                report = verify_autopilot(out_dir=args.out_dir, ledger_path=args.ledger)
            except (AutopilotError, LedgerError, OSError, json.JSONDecodeError) as exc:
                print(f"Autopilot verify failed: {exc}", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print("Smavg autopilot verify")
                print(f"Status: {report['status']}")
                print(f"Checks: {report['pass']}/{report['total']}")
                for check in report["checks"]:
                    print(f"  {'PASS' if check['pass'] else 'FAIL'} {check['name']}: {check['note']}")
            return 0

    if args.command == "daemon":
        try:
            if args.daemon_command == "init":
                config = write_daemon_config(
                    config_path=args.config,
                    root=args.root,
                    daemon_dir=args.daemon_dir,
                    interval_seconds=args.interval_seconds,
                    budget_tokens=args.budget,
                    max_depth=args.max_depth,
                    max_dirs=args.max_dirs,
                    include_surfaces=not args.no_surfaces,
                    include_workflows=not args.no_workflows,
                )
                if args.json:
                    print(json.dumps(config, indent=2, sort_keys=True))
                else:
                    print("Smavg daemon init")
                    print(f"Config: {config['config_path']}")
                    print(f"Root: {config['root']}")
                    print(f"Interval seconds: {config['interval_seconds']}")
                    print("Cleanup performed: NO")
                    print("Delete enabled: NO")
                return 0
            if args.daemon_command == "once":
                report = run_daemon_once(
                    config_path=args.config,
                    root=args.root,
                    daemon_dir=args.daemon_dir,
                    run_id=args.run_id,
                    budget_tokens=args.budget,
                    max_depth=args.max_depth,
                    max_dirs=args.max_dirs,
                    include_surfaces=False if args.no_surfaces else None,
                    include_workflows=False if args.no_workflows else None,
                    create_config=True,
                )
                if args.json:
                    print(json.dumps(report, indent=2, sort_keys=True))
                else:
                    summary = report["autopilot_report"]["summary"]
                    best_dir = summary.get("best_directory_token_reduction")
                    surface_ratio = summary.get("surface_token_reduction_ratio")
                    print("Smavg daemon once")
                    print(f"Run dir: {report['run_dir']}")
                    print(f"Directory candidates: {summary['directory_candidates']}")
                    print(f"Workflow candidates: {summary['workflow_candidates']}")
                    print(f"Best directory reduction: {'n/a' if best_dir is None else f'{best_dir}x'}")
                    print(f"Surface registry reduction: {'n/a' if surface_ratio is None else f'{surface_ratio}x'}")
                    print("Cleanup performed: NO")
                    print("Delete performed: NO")
                    print(f"Report: {report['report_markdown']}")
                return 0
            if args.daemon_command == "run":
                result = run_daemon_loop(
                    config_path=args.config,
                    cycles=args.cycles,
                    sleep_seconds=args.sleep_seconds,
                    create_config=True,
                )
                if args.json:
                    print(json.dumps(result, indent=2, sort_keys=True))
                else:
                    print("Smavg daemon run")
                    print(f"Cycles completed: {result['cycles_completed']}")
                    last = result.get("last_run")
                    if isinstance(last, dict):
                        print(f"Last report: {last.get('report_markdown')}")
                return 0
            if args.daemon_command == "status":
                status = daemon_status(daemon_dir=args.daemon_dir, config_path=args.config)
                if args.out is not None:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(render_daemon_status_markdown(status), encoding="utf-8")
                if args.json:
                    print(json.dumps(status, indent=2, sort_keys=True))
                else:
                    state = status.get("state") if isinstance(status.get("state"), dict) else None
                    print("Smavg daemon status")
                    print(f"Daemon dir: {status['daemon_dir']}")
                    print(f"Running now: {status['running_now']}")
                    if state:
                        print(f"Last run: {state.get('last_run_id')}")
                        print(f"Last report: {state.get('last_report_markdown')}")
                        print(f"Delete performed: {'YES' if state.get('delete_performed') else 'NO'}")
                    else:
                        print("Last run: none")
                    if args.out is not None:
                        print(f"Status Markdown: {args.out}")
                return 0
            if args.daemon_command == "service":
                service = write_service_file(
                    platform_name=args.platform,
                    out=args.out,
                    config_path=args.config,
                    interval_seconds=args.interval_seconds,
                )
                if args.json:
                    print(json.dumps(service, indent=2, sort_keys=True))
                else:
                    print("Smavg daemon service")
                    print(f"Platform: {service['platform']}")
                    print(f"Service file: {service['path']}")
                    print("Loaded/enabled: NO")
                return 0
        except (DaemonError, AutopilotError, ScanError, SurfaceError, LedgerError, ContextError, OSError, json.JSONDecodeError) as exc:
            print(f"Daemon failed: {exc}", file=sys.stderr)
            return 1

    if args.command == "plugin":
        try:
            if args.plugin_command == "build":
                summary = build_plugin_bundle(
                    out_dir=args.out_dir,
                    smavg_command=args.smavg_command,
                    python_executable=args.python,
                    force=args.force,
                )
                if args.json:
                    print(json.dumps(summary, indent=2, sort_keys=True))
                else:
                    print("Smavg plugin build")
                    print(f"Bundle: {summary['out_dir']}")
                    print(f"Skill: {summary['files']['skill']}")
                    print(f"MCP config: {summary['files']['mcp']}")
                    print(f"Report: {Path(summary['out_dir']) / 'build.md'}")
                return 0
            if args.plugin_command == "verify":
                report = verify_plugin_bundle(args.path)
                if args.json:
                    print(json.dumps(report, indent=2, sort_keys=True))
                else:
                    print("Smavg plugin verify")
                    print(f"Status: {report['status']}")
                    print(f"Checks: {report['pass']}/{report['total']}")
                    for check in report["checks"]:
                        print(f"  {'PASS' if check['pass'] else 'FAIL'} {check['name']}: {check['note']}")
                return 0
        except (PluginError, OSError, json.JSONDecodeError) as exc:
            print(f"Plugin failed: {exc}", file=sys.stderr)
            return 1

    if args.command == "safe-pack":
        try:
            report = safe_pack(
                source=args.source,
                archive=args.out,
                work_dir=args.work_dir,
                quarantine_dir=args.quarantine_dir,
                move_to_quarantine=args.move_to_quarantine,
            )
        except (SafePackError, ContainerError) as exc:
            print(f"Safe pack failed: {exc}", file=sys.stderr)
            return 1
        if args.report is not None:
            write_safe_pack_report(report, args.report)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            archive_report = report["archive_report"]
            compare = report["restore_compare"]
            cleanup = report.get("cleanup_projection", {})
            quarantine = cleanup.get("quarantine", {})
            purge = cleanup.get("purge_projection", {})
            tokens = cleanup.get("token_projection", {})
            importance = report.get("importance_brief", {})
            print(f"Safe pack: {report['source']}")
            print(f"Archive: {report['archive']}")
            print(f"Files: {archive_report['file_count']}")
            print(f"Logical bytes: {archive_report['logical_bytes']} ({human_bytes(int(archive_report['logical_bytes']))})")
            print(f"Archive bytes: {archive_report['archive_bytes']} ({human_bytes(int(archive_report['archive_bytes']))})")
            print(f"Ratio: {archive_report['ratio']}")
            print("Archive verify: PASS")
            print(f"Restore compare: {'PASS' if compare['pass'] else 'FAIL'}")
            print(f"Source moved to quarantine: {'YES' if report['source_moved_to_quarantine'] else 'NO'}")
            if report.get("quarantined_path"):
                print(f"Quarantine path: {report['quarantined_path']}")
            print(f"Disk freed now: {human_bytes(int(quarantine.get('disk_bytes_freed_now', 0)))}")
            print(
                "Disk freed if quarantine purged: "
                f"{human_bytes(int(purge.get('additional_disk_bytes_freed_if_quarantine_purged_from_current_state', 0)))}"
            )
            print(
                "Net disk saved after purge while keeping archive: "
                f"{human_bytes(int(purge.get('net_disk_bytes_saved_after_purge_and_archive_kept', 0)))}"
            )
            print(f"Raw source tokens estimate: {tokens.get('raw_source_tokens_estimate', 0)}")
            print(f"Smavg brief tokens estimate: {tokens.get('smavg_brief_tokens_estimate', 0)}")
            token_ratio = tokens.get("token_reduction_ratio")
            print(f"Token reduction if agent uses Smavg brief: {'n/a' if token_ratio is None else f'{token_ratio}x'}")
            print(f"Importance rating: {importance.get('rating', 'unknown')}")
            print(f"Purge risk: {importance.get('purge_risk', 'unknown')}")
            if args.report is not None:
                print(f"Report JSON: {args.report}")
                print(f"Report Markdown: {args.report.with_suffix('.md')}")
            print("Delete performed: NO")
        return 0

    if args.command == "receipt":
        try:
            if args.preflight_json is not None:
                summary = json.loads(args.preflight_json.read_text(encoding="utf-8"))
                summary["receipt_json"] = str(args.out)
                summary["receipt_markdown"] = str(args.markdown or args.out.with_suffix(".md"))
                receipt = initialize_receipt_from_preflight(summary)
            else:
                receipt = create_receipt_from_context(
                    context_json=args.context_json,
                    receipt_json=args.out,
                    receipt_markdown=args.markdown,
                    context_markdown=args.context_markdown,
                    target_label=args.target_label,
                )
        except (OSError, json.JSONDecodeError, KeyError, ReceiptError) as exc:
            print(f"Receipt failed: {exc}", file=sys.stderr)
            return 1
        print(f"Receipt JSON: {args.out}")
        print(f"Receipt Markdown: {args.markdown or args.out.with_suffix('.md')}")
        supplied = receipt.get("supplied_to_agent", {})
        print(f"Raw tokens estimate: {receipt.get('raw_material', {}).get('raw_tokens_estimate', 0)}")
        print(f"Smavg-supplied tokens estimate: {supplied.get('total_tokens_estimate', 0)}")
        ratio = supplied.get("reduction_ratio")
        print(f"Reduction: {'n/a' if ratio is None else f'{ratio}x'}")
        return 0

    if args.command == "work":
        try:
            if args.work_command == "start":
                session = start_work(
                    task=args.task,
                    source=args.source,
                    workflow=args.workflow,
                    budget_tokens=args.budget,
                    work_dir=args.work_dir,
                    tasks_dir=args.tasks_dir,
                    work_id=args.id,
                )
                if args.json:
                    print(json.dumps(session, indent=2, sort_keys=True))
                else:
                    summary = summarize_work(session)
                    ratio = summary["reduction_ratio"]
                    print(f"Smavg work started: {session['id']}")
                    print(f"Task: {session['task']}")
                    print(f"Target: {session['target_label']}")
                    print(f"Raw setup tokens: {summary['raw_setup_tokens']}")
                    print(f"Smavg setup tokens: {summary['smavg_supplied_tokens']}")
                    print(f"Reduction: {'n/a' if ratio is None else f'{ratio}x'}")
                    print(f"Gate: {session['files']['gate_markdown']}")
                    print(f"Context: {session['files']['context_markdown']}")
                    print(f"Receipt: {session['files']['receipt_markdown']}")
                return 0
            if args.work_command == "expand":
                result = expand_work(
                    relative_path=args.path,
                    work_id=args.work_id,
                    work_dir=args.work_dir,
                    output=args.out,
                )
                if args.json:
                    print(json.dumps(result, indent=2, sort_keys=True))
                else:
                    expansion = result["expansion"]
                    supplied = result["receipt"].get("supplied_to_agent", {})
                    ratio = supplied.get("reduction_ratio")
                    print(f"Smavg work expanded: {expansion.get('path')}")
                    print(f"Output: {expansion.get('output')}")
                    print(f"Verified: {expansion.get('verified', False)}")
                    print(f"Expansion tokens: {expansion.get('tokens_estimate', 0)}")
                    print(f"Total Smavg-supplied tokens: {supplied.get('total_tokens_estimate', 0)}")
                    print(f"Current reduction: {'n/a' if ratio is None else f'{ratio}x'}")
                return 0
            if args.work_command == "note":
                text = args.text if args.text is not None else args.file.read_text(encoding="utf-8")
                result = note_work(
                    role=args.role,
                    text=text,
                    work_id=args.work_id,
                    work_dir=args.work_dir,
                    label=args.label,
                )
                if args.json:
                    print(json.dumps(result, indent=2, sort_keys=True))
                else:
                    summary = result["summary"]
                    print(f"Smavg work noted: {result['work']['id']}")
                    print(f"Messages: {summary['messages']}")
                    print(f"Visible total tokens: {summary['visible_total_tokens']}")
                return 0
            if args.work_command == "end":
                result = end_work(
                    work_id=args.work_id,
                    work_dir=args.work_dir,
                    ledger_path=args.ledger,
                    record_ledger=not args.no_ledger,
                    report_path=args.out,
                )
                if args.json:
                    print(json.dumps(result, indent=2, sort_keys=True))
                else:
                    session = result["work"]
                    summary = session["task_summary"]
                    ratio = summary["smavg_reduction_ratio"]
                    print(f"Smavg work ended: {session['id']}")
                    print(f"Smavg raw context tokens: {summary['smavg_raw_context_tokens']}")
                    print(f"Smavg supplied tokens: {summary['smavg_supplied_tokens']}")
                    print(f"Smavg saved tokens: {summary['smavg_saved_tokens']}")
                    print(f"Reduction: {'n/a' if ratio is None else f'{ratio}x'}")
                    print(f"Ledger recorded: {'NO' if args.no_ledger else 'YES'}")
                    if args.out is not None:
                        print(f"Work Markdown: {args.out}")
                return 0
            if args.work_command == "report":
                session = load_work(args.work_id, args.work_dir)
                if args.out is not None:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(render_work_markdown(session), encoding="utf-8")
                if args.json:
                    print(json.dumps(session, indent=2, sort_keys=True))
                else:
                    summary = summarize_work(session)
                    ratio = summary["reduction_ratio"]
                    print(f"Smavg work: {session['id']}")
                    print(f"Status: {session['status']}")
                    print(f"Target: {summary['target_label']}")
                    print(f"Raw setup tokens: {summary['raw_setup_tokens']}")
                    print(f"Smavg supplied tokens: {summary['smavg_supplied_tokens']}")
                    print(f"Reduction: {'n/a' if ratio is None else f'{ratio}x'}")
                    print(f"Exact expansions: {summary['exact_expansions']}")
                    if args.out is not None:
                        print(f"Work Markdown: {args.out}")
                return 0
        except (WorkError, GateError, ContextError, ReceiptError, LedgerError, OSError, json.JSONDecodeError) as exc:
            print(f"Work failed: {exc}", file=sys.stderr)
            return 1

    if args.command == "ledger":
        try:
            if args.ledger_command == "add-report":
                event = event_from_report(
                    args.report,
                    kind=args.kind,
                    label=args.label,
                    surface=args.surface,
                )
                append_event(event, args.ledger)
                if args.json:
                    print(json.dumps(event, indent=2, sort_keys=True))
                else:
                    ratio = event.get("ratios", {}).get("tokens")
                    disk_ratio = event.get("ratios", {}).get("disk_bytes")
                    print(f"Ledger event appended: {event['id']}")
                    print(f"Kind: {event['kind']}")
                    print(f"Label: {event['label']}")
                    print(f"Token reduction: {'n/a' if ratio is None else f'{ratio}x'}")
                    print(f"Disk reduction: {'n/a' if disk_ratio is None else f'{disk_ratio}x'}")
                    print(f"Ledger: {args.ledger}")
                return 0
            if args.ledger_command == "import-reports":
                summary = import_reports(args.root, ledger_path=args.ledger, surface=args.surface)
                if args.json:
                    print(json.dumps(summary, indent=2, sort_keys=True))
                else:
                    print(f"Smavg ledger import: {args.root}")
                    print(f"Scanned JSON: {summary['scanned_json']}")
                    print(f"Selected reports: {summary['selected_reports']}")
                    print(f"Suppressed component reports: {summary['suppressed_component_reports']}")
                    print(f"Imported: {summary['imported']}")
                    print(f"Skipped duplicates: {summary['skipped_duplicate']}")
                    print(f"Skipped unsupported: {summary['skipped_unsupported']}")
                    print(f"Failures: {summary['failures']}")
                    print(f"Ledger: {args.ledger}")
                return 0
            if args.ledger_command == "add":
                event = create_event(
                    kind=args.kind,
                    label=args.label,
                    surface=args.surface,
                    before={
                        "tokens": args.before_tokens,
                        "disk_bytes": args.before_disk_bytes,
                    },
                    after={
                        "tokens": args.after_tokens,
                        "disk_bytes": args.after_disk_bytes,
                    },
                    verification={"status": "verified" if args.verified else "reported"},
                    artifacts=args.artifact,
                    notes=args.note,
                )
                append_event(event, args.ledger)
                if args.json:
                    print(json.dumps(event, indent=2, sort_keys=True))
                else:
                    print(f"Ledger event appended: {event['id']}")
                    print(f"Token reduction: {event['ratios'].get('tokens') or 'n/a'}")
                    print(f"Disk reduction: {event['ratios'].get('disk_bytes') or 'n/a'}")
                    print(f"Ledger: {args.ledger}")
                return 0
            if args.ledger_command == "report":
                report = ledger_report(ledger_path=args.ledger, period=args.period)
                if args.out is not None:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(render_ledger_markdown(report), encoding="utf-8")
                if args.json:
                    print(json.dumps(report, indent=2, sort_keys=True))
                else:
                    ai = report["ai_tokens"]
                    repeated = report["repeated_work_tokens"]
                    storage = report["storage_disk"]
                    visible = report["visible_session_tokens"]
                    trust = report["trust"]
                    headline = report["headline"]
                    print(f"Smavg Benefit Ledger: {args.period}")
                    print(f"Events: {report['event_count']}")
                    print(f"Tokens saved today: {headline['tokens_saved_today']}")
                    print(f"Tokens saved all time: {headline['tokens_saved_all_time']}")
                    print(f"Repeated-work tokens saved today: {headline['repeated_tokens_saved_today']}")
                    print(f"Repeated-work tokens saved all time: {headline['repeated_tokens_saved_all_time']}")
                    print(f"Disk saved today: {human_bytes(int(headline['disk_bytes_saved_today']))}")
                    print(f"Disk saved all time: {human_bytes(int(headline['disk_bytes_saved_all_time']))}")
                    ai_ratio = "n/a" if ai["ratio"] is None else f"{ai['ratio']}x"
                    repeated_ratio = "n/a" if repeated["ratio"] is None else f"{repeated['ratio']}x"
                    storage_ratio = "n/a" if storage["ratio"] is None else f"{storage['ratio']}x"
                    print(f"AI tokens: {ai['before']} -> {ai['after']} ({ai_ratio})")
                    print(f"Repeated tokens: {repeated['before']} -> {repeated['after']} ({repeated_ratio})")
                    print(f"Storage disk: {human_bytes(int(storage['before']))} -> {human_bytes(int(storage['after']))} ({storage_ratio})")
                    print(f"Visible user input tokens: {visible['user_input_tokens']}")
                    print(f"Visible assistant output tokens: {visible['assistant_output_tokens']}")
                    print(f"Visible tool tokens: {visible['tool_tokens']}")
                    print(f"Exact expansion: {trust['exact_expansion']['pass']}/{trust['exact_expansion']['total']}")
                    print(f"Evidence tasks: {trust['evidence_tasks']['pass']}/{trust['evidence_tasks']['total']}")
                    print(f"Failures counted as wins: {trust['failures_counted_as_wins']}")
                    print(f"Ledger: {args.ledger}")
                    if args.out is not None:
                        print(f"Report Markdown: {args.out}")
                return 0
            if args.ledger_command == "list":
                events = load_events(args.ledger)[-max(0, args.limit):]
                if args.json:
                    print(json.dumps(events, indent=2, sort_keys=True))
                else:
                    for event in events:
                        ratio = event.get("ratios", {}).get("tokens")
                        print(f"{event.get('created_at')} {event.get('kind')} {event.get('label')} tokens={ratio or 'n/a'}x")
                return 0
        except (LedgerError, OSError, json.JSONDecodeError) as exc:
            print(f"Ledger failed: {exc}", file=sys.stderr)
            return 1

    if args.command == "task":
        try:
            if args.task_command == "start":
                task = start_task(
                    label=args.label,
                    surface=args.surface,
                    tasks_dir=args.tasks_dir,
                    task_id=args.id,
                )
                if args.json:
                    print(json.dumps(task, indent=2, sort_keys=True))
                else:
                    print(f"Smavg task started: {task['id']}")
                    print(f"Label: {task['label']}")
                    print(f"Task file: {default_tasks_dir() / (str(task['id']) + '.json') if args.tasks_dir == default_tasks_dir() else args.tasks_dir / (str(task['id']) + '.json')}")
                return 0
            if args.task_command == "add":
                if args.text is not None:
                    text = args.text
                else:
                    text = args.file.read_text(encoding="utf-8")
                task = add_task_text(
                    task_id=args.task_id,
                    role=args.role,
                    text=text,
                    tasks_dir=args.tasks_dir,
                    label=args.label,
                )
                summary = summarize_task(task)
                if args.json:
                    print(json.dumps(task, indent=2, sort_keys=True))
                else:
                    print(f"Task updated: {task['id']}")
                    print(f"Messages: {summary['messages']}")
                    print(f"Visible total tokens: {summary['visible_total_tokens']}")
                return 0
            if args.task_command == "add-report":
                task = add_task_report(
                    task_id=args.task_id,
                    report_path=args.report,
                    kind=args.kind,
                    label=args.label,
                    surface=args.surface,
                    tasks_dir=args.tasks_dir,
                )
                summary = summarize_task(task)
                if args.json:
                    print(json.dumps(task, indent=2, sort_keys=True))
                else:
                    ratio = summary["smavg_reduction_ratio"]
                    print(f"Task report attached: {task['id']}")
                    print(f"Smavg events: {summary['smavg_events']}")
                    print(f"Context reduction: {'n/a' if ratio is None else f'{ratio}x'}")
                return 0
            if args.task_command == "end":
                task = end_task(
                    task_id=args.task_id,
                    tasks_dir=args.tasks_dir,
                    ledger_path=args.ledger,
                    record_ledger=not args.no_ledger,
                )
                if args.out is not None:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(render_task_markdown(task), encoding="utf-8")
                if args.json:
                    print(json.dumps(task, indent=2, sort_keys=True))
                else:
                    summary = task["summary"]
                    ratio = summary["smavg_reduction_ratio"]
                    print(f"Smavg task ended: {task['id']}")
                    print(f"Visible input tokens: {summary['visible_user_input_tokens']}")
                    print(f"Visible output tokens: {summary['visible_assistant_output_tokens']}")
                    print(f"Smavg raw context tokens: {summary['smavg_raw_context_tokens']}")
                    print(f"Smavg supplied tokens: {summary['smavg_supplied_tokens']}")
                    print(f"Smavg reduction: {'n/a' if ratio is None else f'{ratio}x'}")
                    print(f"Ledger recorded: {'NO' if args.no_ledger else 'YES'}")
                    if args.out is not None:
                        print(f"Task Markdown: {args.out}")
                return 0
            if args.task_command == "report":
                task = load_task(args.task_id, args.tasks_dir)
                task["summary"] = task.get("summary") or summarize_task(task)
                if args.out is not None:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(render_task_markdown(task), encoding="utf-8")
                if args.json:
                    print(json.dumps(task, indent=2, sort_keys=True))
                else:
                    summary = task["summary"]
                    ratio = summary["smavg_reduction_ratio"]
                    print(f"Smavg task: {task['id']}")
                    print(f"Label: {task['label']}")
                    print(f"Messages: {summary['messages']}")
                    print(f"Visible total tokens: {summary['visible_total_tokens']}")
                    print(f"Smavg reduction: {'n/a' if ratio is None else f'{ratio}x'}")
                    if args.out is not None:
                        print(f"Task Markdown: {args.out}")
                return 0
        except (LedgerError, OSError, json.JSONDecodeError) as exc:
            print(f"Task failed: {exc}", file=sys.stderr)
            return 1

    if args.command == "mcp-server":
        from .mcp_server import main as mcp_main

        return mcp_main([])

    if args.command == "expand-context":
        try:
            size = expand_context_file(args.context_json, args.path, args.out)
            if args.receipt is not None:
                append_expansion_to_receipt(
                    receipt_json=args.receipt,
                    context_json=args.context_json,
                    relative_path=args.path,
                    expanded_output=args.out,
                )
        except ContextError as exc:
            print(f"Expand context failed: {exc}", file=sys.stderr)
            return 1
        except ReceiptError as exc:
            print(f"Expand context receipt failed: {exc}", file=sys.stderr)
            return 1
        print(f"Expanded {args.path} to {args.out}")
        print(f"Bytes: {size}")
        print("Verified: PASS")
        if args.receipt is not None:
            print(f"Receipt updated: {args.receipt}")
        return 0

    if args.command == "verify":
        if args.source.is_file() and args.snapshot is None:
            ok, failures = verify_container(args.source)
            if ok:
                print("Archive verify: PASS")
                return 0
            print("Archive verify: FAIL")
            for failure in failures:
                print(failure)
            return 1
        if args.snapshot:
            ok, failures = store.verify_snapshot_against_dir(args.snapshot, args.source)
        else:
            ok, failures = store.verify_dir(args.source)
        if ok:
            print("Byte-perfect verify: PASS")
            return 0
        print("Byte-perfect verify: FAIL")
        for failure in failures:
            print(failure)
        return 1

    if args.command == "verify-snapshot":
        snapshot_id = store.resolve_snapshot_id(args.snapshot)
        ok, failures = store.verify_snapshot_integrity(snapshot_id)
        if ok:
            print(f"Snapshot {snapshot_id} verify: PASS")
            return 0
        print(f"Snapshot {snapshot_id} verify: FAIL")
        for failure in failures:
            print(failure)
        return 1

    if args.command == "stats":
        stats = store.stats()
        if args.json:
            print(json.dumps(stats, indent=2, sort_keys=True))
        else:
            print_stats(stats)
        return 0

    if args.command == "report":
        if args.archive is not None:
            try:
                report = report_container(args.archive)
            except ContainerError as exc:
                print(f"Report failed: {exc}", file=sys.stderr)
                return 1
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print_container_report(report)
            return 0
        if args.snapshot == "latest":
            try:
                report = load_latest_autopilot(default_autopilot_dir())
                if args.json:
                    print(json.dumps(report, indent=2, sort_keys=True))
                else:
                    print(render_autopilot_markdown(report))
                return 0
            except AutopilotError:
                try:
                    ledger = ledger_report(ledger_path=default_ledger_path(), period="all")
                except LedgerError as exc:
                    print(f"Report failed: {exc}", file=sys.stderr)
                    return 1
                if args.json:
                    print(json.dumps(ledger, indent=2, sort_keys=True))
                else:
                    print(render_ledger_markdown(ledger))
                return 0
        report = store.snapshot_report(args.snapshot)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print_snapshot_report(report)
        return 0

    if args.command == "list":
        for item in store.list_files():
            print(
                f"{item['path']}\tobject={item['object_id']}\tmode={item['mode']}"
                f"\tlogical={item['logical_size']}\tstored={item['stored_size']}"
            )
        return 0

    if args.command == "snapshots":
        for snapshot in store.list_snapshots():
            print(
                f"{snapshot['id']}\tfiles={snapshot['file_count']}"
                f"\tlogical={snapshot['logical_bytes']}\tsource={snapshot['source_path']}"
            )
        return 0

    if args.command == "benchmark":
        return run_benchmark(store, args.source, reset=args.reset)

    if args.command == "gauntlet":
        try:
            report = run_gauntlet(
                args.source,
                args.out,
                preset=args.preset,
                baselines=args.baselines,
                allow_sensitive=args.allow_sensitive,
                keep_baselines=args.keep_baselines,
            )
        except GauntletError as exc:
            print(f"Gauntlet failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report["summary"], indent=2, sort_keys=True))
        else:
            summary = report["summary"]
            print(f"Gauntlet report: {Path(report['output_dir']) / 'report.md'}")
            print(f"Corpora: {summary['corpora']}")
            print(f"Counted: {summary['counted']}")
            print(f"Not counted: {summary['not_counted']}")
            print(f"Verify PASS: {summary['verify_pass']}")
            print(f"Restore PASS: {summary['restore_pass']}")
            print(f"Diff PASS: {summary['diff_pass']}")
            print(f"Beats best baseline: {summary['beats_best_baseline']}")
        return 0

    if args.command == "codex-gauntlet":
        try:
            report = run_codex_workload_gauntlet(
                args.out,
                budget_tokens=args.budget,
                repeat_count=args.repeat_count,
                reset=args.reset,
            )
        except CodexGauntletError as exc:
            print(f"Codex gauntlet failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report["summary"], indent=2, sort_keys=True))
        else:
            summary = report["summary"]
            totals = summary["totals"]
            print(f"Codex gauntlet report: {Path(report['output_dir']) / 'report.md'}")
            print(f"Probes: {summary['probes']}")
            print(f"Exact expansion pass: {summary['exact_expansion_pass']}/{summary['probes']}")
            print(f"Model-routing pass: {summary['model_routing_pass']}/{summary['probes']}")
            print(f"First-time useful: {summary['first_time_useful']}/{summary['probes']}")
            print(f"Repeated useful: {summary['repeated_useful']}/{summary['probes']}")
            print(f"Raw tokens estimate: {totals['raw_tokens_estimate']}")
            print(f"Brief tokens estimate: {totals['brief_tokens_estimate']}")
            print(f"Brief-only reduction: {totals['brief_only_reduction_ratio']}x")
            print(f"First-time reduction: {totals['first_time_reduction_ratio']}x")
            print(f"Repeated-work reduction: {totals['repeated_reduction_ratio']}x")
            task_ab = summary.get("task_ab", {})
            print(f"A/B evidence tasks: {task_ab.get('pass', 0)}/{task_ab.get('tasks', 0)} PASS")
            ratio = task_ab.get("token_reduction_ratio")
            print(f"A/B token reduction: {'n/a' if ratio is None else f'{ratio}x'}")
        return 0

    if args.command == "gate-gauntlet":
        try:
            report = run_gate_gauntlet(
                args.out,
                budget_tokens=args.budget,
                repeat_count=args.repeat_count,
                reset=args.reset,
            )
        except GateGauntletError as exc:
            print(f"Gate gauntlet failed: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(report["summary"], indent=2, sort_keys=True))
        else:
            summary = report["summary"]
            print(f"Gate gauntlet report: {Path(report['output_dir']) / 'report.md'}")
            print(f"Probes: {summary['probes']}")
            print(f"PASS: {summary['pass']}/{summary['probes']}")
            print(f"Gate integrity PASS: {summary['gate_integrity_pass']}/{summary['probes']}")
            print(f"Receipt integrity PASS: {summary['receipt_integrity_pass']}/{summary['probes']}")
            print(f"Exact expansion PASS: {summary['exact_expansion_pass']}/{summary['probes']}")
            print(f"Model routing PASS: {summary['model_routing_pass']}/{summary['probes']}")
            print(f"Evidence tasks PASS: {summary['evidence_task_pass']}/{summary['evidence_tasks']}")
            print(f"Same evidence: {summary['same_evidence']}/{summary['evidence_tasks']}")
            print(f"Raw tokens estimate: {summary['raw_tokens_estimate']}")
            print(f"Gate receipt tokens estimate: {summary['gate_receipt_tokens_estimate']}")
            ratio = summary.get("receipt_reduction_ratio")
            print(f"Receipt reduction: {'n/a' if ratio is None else f'{ratio}x'}")
            repeated_ratio = summary.get("repeated_reduction_ratio")
            print(f"Repeated-work reduction: {'n/a' if repeated_ratio is None else f'{repeated_ratio}x'}")
            print("Full raw source supplied by Smavg: NO")
        return 0

    if args.command == "demo":
        workdir = args.workdir.resolve()
        if args.reset and workdir.exists():
            shutil.rmtree(workdir)
        source = workdir / "source"
        demo_store = SmavgStore(workdir / "store")
        generate_demo_docs(source, args.count)
        return run_benchmark(demo_store, source, reset=True)

    if args.command == "fetch-cisa-kev":
        output = args.output.resolve()
        if args.reset and output.exists():
            shutil.rmtree(output)
        manifest = write_cisa_kev_corpus(output, limit=args.limit)
        print(f"Source: {CISA_KEV_URL}")
        print(f"Catalog version: {manifest.get('catalog_version')}")
        print(f"Date released: {manifest.get('date_released')}")
        print(f"Records written: {manifest.get('count_written')}")
        print(f"Output: {output / 'records'}")
        return 0

    if args.command == "benchmark-cisa-kev":
        workdir = args.workdir.resolve()
        if args.reset and workdir.exists():
            shutil.rmtree(workdir)
        corpus = workdir / "corpus"
        manifest = write_cisa_kev_corpus(corpus, limit=args.limit)
        print(f"Source: {CISA_KEV_URL}")
        print(f"Catalog version: {manifest.get('catalog_version')}")
        print(f"Date released: {manifest.get('date_released')}")
        print(f"Records written: {manifest.get('count_written')}")
        kev_store = SmavgStore(
            workdir / "store",
            enable_json_templates=not args.no_json_template,
        )
        return run_benchmark(kev_store, corpus / "records", reset=True)

    if args.command == "fetch-nvd-cve":
        output = args.output.resolve()
        if args.reset and output.exists():
            shutil.rmtree(output)
        manifest = write_nvd_cve_corpus(output, feed=args.feed, limit=args.limit)
        print(f"Source: {manifest.get('source')}")
        print(f"Feed: {manifest.get('feed')}")
        print(f"Version: {manifest.get('version')}")
        print(f"Timestamp: {manifest.get('timestamp')}")
        print(f"Records written: {manifest.get('count_written')}")
        print(f"Output: {output / 'records'}")
        return 0

    if args.command == "benchmark-nvd-cve":
        workdir = args.workdir.resolve()
        if args.reset and workdir.exists():
            shutil.rmtree(workdir)
        corpus = workdir / "corpus"
        manifest = write_nvd_cve_corpus(corpus, feed=args.feed, limit=args.limit)
        print(f"Source: {manifest.get('source')}")
        print(f"Feed: {manifest.get('feed')}")
        print(f"Version: {manifest.get('version')}")
        print(f"Timestamp: {manifest.get('timestamp')}")
        print(f"Records written: {manifest.get('count_written')}")
        nvd_store = SmavgStore(
            workdir / "store",
            enable_json_templates=not args.no_json_template,
        )
        return run_benchmark(nvd_store, corpus / "records", reset=True)

    if args.command == "fetch-git-history":
        output = args.output.resolve()
        if args.reset and output.exists():
            shutil.rmtree(output)
        manifest = write_git_history_corpus(
            args.repo,
            output,
            args.path,
            limit=args.limit,
        )
        print(f"Source repo: {manifest.get('source')}")
        print(f"Records written: {manifest.get('count_written')}")
        for item in manifest.get("files", []):
            print(f"{item['path']}: {item['versions']} versions")
        print(f"Output: {output / 'records'}")
        return 0

    if args.command == "benchmark-git-history":
        workdir = args.workdir.resolve()
        if args.reset and workdir.exists():
            shutil.rmtree(workdir)
        corpus = workdir / "corpus"
        manifest = write_git_history_corpus(
            args.repo,
            corpus,
            args.path,
            limit=args.limit,
        )
        print(f"Source repo: {manifest.get('source')}")
        print(f"Records written: {manifest.get('count_written')}")
        for item in manifest.get("files", []):
            print(f"{item['path']}: {item['versions']} versions")
        git_store = SmavgStore(
            workdir / "store",
            enable_json_templates=not args.no_json_template,
        )
        return run_benchmark(git_store, corpus / "records", reset=True)

    if args.command == "fetch-loghub":
        output = args.output.resolve()
        if args.reset and output.exists():
            shutil.rmtree(output)
        manifest = write_loghub_corpus(output, names=args.name)
        print(f"Source: {manifest.get('source')}")
        print(f"Records written: {manifest.get('count_written')}")
        for item in manifest.get("files", []):
            print(f"{item['name']}: {item['bytes']} bytes")
        print(f"Output: {output / 'records'}")
        return 0

    if args.command == "benchmark-loghub":
        workdir = args.workdir.resolve()
        if args.reset and workdir.exists():
            shutil.rmtree(workdir)
        corpus = workdir / "corpus"
        manifest = write_loghub_corpus(corpus, names=args.name)
        print(f"Source: {manifest.get('source')}")
        print(f"Records written: {manifest.get('count_written')}")
        for item in manifest.get("files", []):
            print(f"{item['name']}: {item['bytes']} bytes")
        log_store = SmavgStore(
            workdir / "store",
            enable_json_templates=not args.no_json_template,
        )
        return run_benchmark(log_store, corpus / "records", reset=True)

    if args.command == "fetch-weather-csv":
        output = args.output.resolve()
        if args.reset and output.exists():
            shutil.rmtree(output)
        manifest = write_weather_csv_corpus(
            output,
            city_ids=args.city_id,
            limit=args.limit,
        )
        print(f"Source: {manifest.get('source')}")
        print(f"Records written: {manifest.get('count_written')}")
        for item in manifest.get("files", []):
            print(f"{item['city_id']}: {item['bytes']} bytes")
        print(f"Output: {output / 'records'}")
        return 0

    if args.command == "benchmark-weather-csv":
        workdir = args.workdir.resolve()
        if args.reset and workdir.exists():
            shutil.rmtree(workdir)
        corpus = workdir / "corpus"
        manifest = write_weather_csv_corpus(
            corpus,
            city_ids=args.city_id,
            limit=args.limit,
        )
        print(f"Source: {manifest.get('source')}")
        print(f"Records written: {manifest.get('count_written')}")
        for item in manifest.get("files", []):
            print(f"{item['city_id']}: {item['bytes']} bytes")
        weather_store = SmavgStore(
            workdir / "store",
            enable_json_templates=not args.no_json_template,
        )
        return run_benchmark(weather_store, corpus / "records", reset=True)

    raise SmavgError(f"Unknown command: {args.command}")


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return command_main(args)
    except SmavgError as exc:
        print(f"smavg: {exc}", file=sys.stderr)
        return 2
    except GauntletError as exc:
        print(f"smavg: {exc}", file=sys.stderr)
        return 2
    except ContextError as exc:
        print(f"smavg: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
