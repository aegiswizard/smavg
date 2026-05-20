"""Safe local Smavg daemon loop.

The daemon layer is intentionally boring: it runs the same read-only product
scan as `smavg scan`, records the latest state, and never deletes, quarantines,
or rewrites user data. Long-running service managers can wrap this module, but
the safety boundary stays inside the core.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .autopilot import (
    TRUTH_BOUNDARY as AUTOPILOT_TRUTH_BOUNDARY,
    autopilot_status,
    default_autopilot_dir,
    render_status_markdown,
    run_autopilot_scan,
)
from .ledger import default_ledger_path


class DaemonError(RuntimeError):
    """Raised when the safe daemon loop cannot continue."""


DAEMON_TRUTH_BOUNDARY = (
    AUTOPILOT_TRUTH_BOUNDARY
    + " Smavg daemon v1 is read-only: it scans and reports only. It does not "
    "delete, quarantine, archive active paths, or send data off-machine."
)


def default_daemon_dir() -> Path:
    return Path.home() / ".smavg" / "daemon"


def default_daemon_config_path() -> Path:
    return default_daemon_dir() / "config.json"


def default_daemon_config(
    *,
    root: Optional[Path] = None,
    daemon_dir: Optional[Path] = None,
    interval_seconds: int = 6 * 60 * 60,
    budget_tokens: int = 3000,
    max_depth: int = 1,
    max_dirs: int = 40,
    include_surfaces: bool = True,
    include_workflows: bool = True,
) -> Dict[str, object]:
    if interval_seconds <= 0:
        raise DaemonError("interval_seconds must be positive")
    if budget_tokens <= 0:
        raise DaemonError("budget_tokens must be positive")
    base = Path(daemon_dir or default_daemon_dir()).expanduser()
    return {
        "format": "smavg-daemon-config",
        "version": 1,
        "created_at": _now(),
        "root": str(Path(root or Path.home()).expanduser()),
        "daemon_dir": str(base),
        "autopilot_dir": str(base / "autopilot"),
        "ledger": str(default_ledger_path()),
        "interval_seconds": interval_seconds,
        "budget_tokens": budget_tokens,
        "max_depth": max_depth,
        "max_dirs": max_dirs,
        "include_surfaces": include_surfaces,
        "include_workflows": include_workflows,
        "apply_enabled": False,
        "delete_enabled": False,
        "network_required": False,
        "truth_boundary": DAEMON_TRUTH_BOUNDARY,
    }


def write_daemon_config(
    *,
    config_path: Optional[Path] = None,
    root: Optional[Path] = None,
    daemon_dir: Optional[Path] = None,
    interval_seconds: int = 6 * 60 * 60,
    budget_tokens: int = 3000,
    max_depth: int = 1,
    max_dirs: int = 40,
    include_surfaces: bool = True,
    include_workflows: bool = True,
) -> Dict[str, object]:
    path = Path(config_path or default_daemon_config_path()).expanduser()
    config = default_daemon_config(
        root=root,
        daemon_dir=daemon_dir or path.parent,
        interval_seconds=interval_seconds,
        budget_tokens=budget_tokens,
        max_depth=max_depth,
        max_dirs=max_dirs,
        include_surfaces=include_surfaces,
        include_workflows=include_workflows,
    )
    config["config_path"] = str(path)
    _write_json_atomic(path, config)
    return config


def load_daemon_config(config_path: Optional[Path] = None, *, create: bool = False) -> Dict[str, object]:
    path = Path(config_path or default_daemon_config_path()).expanduser()
    if not path.exists():
        if create:
            return write_daemon_config(config_path=path)
        raise DaemonError("No Smavg daemon config found. Run `smavg daemon init` first.")
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DaemonError(f"Cannot read daemon config: {path}") from exc
    if config.get("format") != "smavg-daemon-config":
        raise DaemonError(f"Unsupported daemon config format: {path}")
    config["config_path"] = str(path)
    return config


def run_daemon_once(
    *,
    config_path: Optional[Path] = None,
    root: Optional[Path] = None,
    daemon_dir: Optional[Path] = None,
    run_id: Optional[str] = None,
    budget_tokens: Optional[int] = None,
    max_depth: Optional[int] = None,
    max_dirs: Optional[int] = None,
    include_surfaces: Optional[bool] = None,
    include_workflows: Optional[bool] = None,
    create_config: bool = True,
) -> Dict[str, object]:
    """Run exactly one safe read-only daemon cycle."""
    config = load_daemon_config(config_path, create=create_config)
    if daemon_dir is not None:
        config["daemon_dir"] = str(Path(daemon_dir).expanduser())
        config["autopilot_dir"] = str(Path(daemon_dir).expanduser() / "autopilot")
    base = Path(str(config.get("daemon_dir") or default_daemon_dir())).expanduser()
    run_id = run_id or _default_run_id("daemon")
    root_path = Path(root or str(config.get("root") or Path.home())).expanduser()
    autopilot_dir = Path(str(config.get("autopilot_dir") or (base / "autopilot"))).expanduser()
    budget = int(budget_tokens or config.get("budget_tokens", 3000))
    depth = int(max_depth if max_depth is not None else config.get("max_depth", 1))
    dirs = int(max_dirs if max_dirs is not None else config.get("max_dirs", 40))
    surfaces = bool(config.get("include_surfaces", True)) if include_surfaces is None else include_surfaces
    workflows = bool(config.get("include_workflows", True)) if include_workflows is None else include_workflows

    report = run_autopilot_scan(
        root=root_path,
        out_dir=autopilot_dir,
        run_id=run_id,
        budget_tokens=budget,
        recursive=True,
        max_depth=depth,
        max_dirs=dirs,
        include_surfaces=surfaces,
        include_workflows=workflows,
    )
    status = autopilot_status(
        out_dir=autopilot_dir,
        ledger_path=Path(str(config.get("ledger") or default_ledger_path())).expanduser(),
    )
    daemon_report = {
        "format": "smavg-daemon-run",
        "version": 1,
        "generated_at": _now(),
        "run_id": run_id,
        "daemon_dir": str(base),
        "config_path": str(config.get("config_path")),
        "root": str(root_path),
        "autopilot_report": report,
        "status": status,
        "actions": {
            "scan_performed": True,
            "cleanup_performed": False,
            "archive_performed": False,
            "quarantine_performed": False,
            "delete_performed": False,
        },
        "next_recommended_command": "smavg report",
        "truth_boundary": DAEMON_TRUTH_BOUNDARY,
    }
    run_dir = base / "runs" / run_id
    daemon_report["run_dir"] = str(run_dir)
    daemon_report["report_json"] = str(run_dir / "daemon.json")
    daemon_report["report_markdown"] = str(run_dir / "daemon.md")
    _write_json_atomic(run_dir / "daemon.json", daemon_report)
    _write_text_atomic(run_dir / "daemon.md", render_daemon_run_markdown(daemon_report))
    _write_json_atomic(base / "state.json", _state_from_run(daemon_report, config))
    _write_text_atomic(base / "status.md", render_daemon_status_markdown(daemon_status(daemon_dir=base, config_path=config_path)))
    return daemon_report


def run_daemon_loop(
    *,
    config_path: Optional[Path] = None,
    cycles: Optional[int] = None,
    sleep_seconds: Optional[int] = None,
    create_config: bool = True,
) -> Dict[str, object]:
    """Run the safe daemon loop until interrupted or cycles are exhausted."""
    config = load_daemon_config(config_path, create=create_config)
    interval = int(sleep_seconds or config.get("interval_seconds", 6 * 60 * 60))
    if interval <= 0:
        raise DaemonError("sleep_seconds must be positive")
    completed = 0
    last: Optional[Dict[str, object]] = None
    while cycles is None or completed < cycles:
        last = run_daemon_once(config_path=Path(str(config["config_path"])), create_config=False)
        completed += 1
        if cycles is not None and completed >= cycles:
            break
        time.sleep(interval)
    return {
        "format": "smavg-daemon-loop",
        "version": 1,
        "generated_at": _now(),
        "cycles_completed": completed,
        "last_run": last,
        "truth_boundary": DAEMON_TRUTH_BOUNDARY,
    }


def daemon_status(
    *,
    daemon_dir: Optional[Path] = None,
    config_path: Optional[Path] = None,
) -> Dict[str, object]:
    base = Path(daemon_dir or default_daemon_dir()).expanduser()
    config = None
    try:
        config = load_daemon_config(config_path, create=False)
    except DaemonError:
        config = None
    state_path = base / "state.json"
    state = None
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = None
    return {
        "format": "smavg-daemon-status",
        "version": 1,
        "generated_at": _now(),
        "daemon_dir": str(base),
        "config": config,
        "state": state,
        "running_now": False,
        "truth_boundary": DAEMON_TRUTH_BOUNDARY,
    }


def write_service_file(
    *,
    platform_name: str = "auto",
    out: Optional[Path] = None,
    config_path: Optional[Path] = None,
    interval_seconds: Optional[int] = None,
) -> Dict[str, object]:
    """Write a service-manager file without loading/enabling it."""
    config = load_daemon_config(config_path, create=True)
    selected = _select_platform(platform_name)
    path = Path(out).expanduser() if out is not None else _default_service_path(selected)
    content = _service_content(
        selected,
        config_path=Path(str(config["config_path"])),
        interval_seconds=interval_seconds or int(config.get("interval_seconds", 6 * 60 * 60)),
    )
    _write_text_atomic(path, content)
    return {
        "format": "smavg-daemon-service",
        "version": 1,
        "generated_at": _now(),
        "platform": selected,
        "path": str(path),
        "config_path": str(config["config_path"]),
        "installed": False,
        "loaded": False,
        "truth_boundary": (
            "Service file was written only. Smavg did not load, enable, or start "
            "the background process."
        ),
    }


def render_daemon_run_markdown(report: Dict[str, object]) -> str:
    summary = report.get("autopilot_report", {}).get("summary", {})
    actions = report.get("actions", {})
    return "\n".join(
        [
            "# Smavg Daemon Run",
            "",
            f"- Run id: `{report.get('run_id')}`",
            f"- Root: `{report.get('root')}`",
            f"- Directory candidates: {summary.get('directory_candidates', 0)}",
            f"- Workflow candidates: {summary.get('workflow_candidates', 0)}",
            f"- Surface groups: {summary.get('surface_context_groups', 0)}",
            f"- Best directory reduction: {_format_ratio(summary.get('best_directory_token_reduction'))}",
            f"- Best workflow reduction: {_format_ratio(summary.get('best_workflow_token_reduction'))}",
            f"- Surface registry reduction: {_format_ratio(summary.get('surface_token_reduction_ratio'))}",
            f"- Cleanup performed: `{actions.get('cleanup_performed', False)}`",
            f"- Delete performed: `{actions.get('delete_performed', False)}`",
            f"- Autopilot report: `{report.get('autopilot_report', {}).get('report_markdown')}`",
            "",
            "## Truth Boundary",
            "",
            str(report.get("truth_boundary", DAEMON_TRUTH_BOUNDARY)),
            "",
        ]
    )


def render_daemon_status_markdown(status: Dict[str, object]) -> str:
    state = status.get("state") if isinstance(status.get("state"), dict) else None
    lines = [
        "# Smavg Daemon Status",
        "",
        f"- Daemon dir: `{status.get('daemon_dir')}`",
        f"- Running now: `{status.get('running_now', False)}`",
    ]
    if state:
        lines.extend(
            [
                f"- Last run: `{state.get('last_run_id')}`",
                f"- Last run at: `{state.get('last_run_at')}`",
                f"- Last report: `{state.get('last_report_markdown')}`",
                f"- Cleanup performed: `{state.get('cleanup_performed', False)}`",
                f"- Delete performed: `{state.get('delete_performed', False)}`",
            ]
        )
    else:
        lines.append("- Last run: none")
    lines.extend(["", "## Truth Boundary", "", str(status.get("truth_boundary", DAEMON_TRUTH_BOUNDARY)), ""])
    return "\n".join(lines)


def _state_from_run(report: Dict[str, object], config: Dict[str, object]) -> Dict[str, object]:
    actions = report.get("actions", {}) if isinstance(report.get("actions"), dict) else {}
    return {
        "format": "smavg-daemon-state",
        "version": 1,
        "updated_at": _now(),
        "last_run_id": report.get("run_id"),
        "last_run_at": report.get("generated_at"),
        "last_report_json": report.get("report_json"),
        "last_report_markdown": report.get("report_markdown"),
        "last_autopilot_report": report.get("autopilot_report", {}).get("report_markdown"),
        "config_path": config.get("config_path"),
        "cleanup_performed": bool(actions.get("cleanup_performed", False)),
        "delete_performed": bool(actions.get("delete_performed", False)),
        "truth_boundary": DAEMON_TRUTH_BOUNDARY,
    }


def _service_content(platform_name: str, *, config_path: Path, interval_seconds: int) -> str:
    executable = sys.executable or "python3"
    module_command = f"{executable} -m smavg.cli daemon run --config {config_path} --cycles 1"
    if platform_name == "launchd":
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.aegiswizard.smavg.daemon</string>
  <key>ProgramArguments</key>
  <array>
    <string>{executable}</string>
    <string>-m</string>
    <string>smavg.cli</string>
    <string>daemon</string>
    <string>run</string>
    <string>--config</string>
    <string>{config_path}</string>
    <string>--cycles</string>
    <string>1</string>
  </array>
  <key>StartInterval</key>
  <integer>{interval_seconds}</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>{default_daemon_dir()}/daemon.out.log</string>
  <key>StandardErrorPath</key>
  <string>{default_daemon_dir()}/daemon.err.log</string>
</dict>
</plist>
"""
    if platform_name == "systemd":
        return f"""[Unit]
Description=Smavg safe local repetition scan

[Service]
Type=oneshot
ExecStart={module_command}

[Install]
WantedBy=default.target
"""
    if platform_name == "windows":
        return f"""# Smavg Windows scheduled task command
# Register manually with Task Scheduler if desired. This file does not install anything.
{module_command}
"""
    raise DaemonError(f"Unsupported service platform: {platform_name}")


def _select_platform(platform_name: str) -> str:
    value = platform_name.lower()
    if value != "auto":
        if value not in {"launchd", "systemd", "windows"}:
            raise DaemonError("platform must be auto, launchd, systemd, or windows")
        return value
    system = platform.system().lower()
    if system == "darwin":
        return "launchd"
    if system == "windows":
        return "windows"
    return "systemd"


def _default_service_path(platform_name: str) -> Path:
    if platform_name == "launchd":
        return Path.home() / "Library" / "LaunchAgents" / "com.aegiswizard.smavg.daemon.plist"
    if platform_name == "systemd":
        return Path.home() / ".config" / "systemd" / "user" / "smavg-daemon.service"
    return default_daemon_dir() / "smavg-daemon-windows-task.txt"


def _format_ratio(value: object) -> str:
    return "n/a" if value is None else f"{value}x"


def _default_run_id(label: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{label}"


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
