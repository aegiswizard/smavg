"""Minimal MCP stdio server for Smavg.

This intentionally avoids third-party dependencies. It implements the small
JSON-RPC surface needed to expose Smavg's verified CLI/core routines as MCP
tools over newline-delimited stdio.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .autopilot import AutopilotError, autopilot_status, default_autopilot_dir, run_autopilot_scan
from .container import ContainerError, report_container, verify_container
from .context import (
    ContextError,
    build_context_report,
    expand_context_file,
    write_context_outputs,
)
from .daemon import DaemonError, daemon_status, default_daemon_dir, run_daemon_once
from .gate import GateError, run_gate
from .ledger import LedgerError, default_ledger_path
from .preflight import run_preflight
from .plugin import PluginError, build_plugin_bundle, default_plugin_dir, verify_plugin_bundle
from .receipt import ReceiptError, append_expansion_to_receipt, create_receipt_from_context
from .safe_ops import SafePackError, safe_pack, write_safe_pack_report
from .scan import ScanError, run_scan
from .surfaces import SurfaceError, run_surface_gauntlet, scan_surfaces
from .workflow_context import available_workflow_profiles


PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "smavg"
SERVER_VERSION = "0.1.0"

JSONValue = Dict[str, Any]


def serve(input_stream: Any = None, output_stream: Any = None) -> None:
    """Run the newline-delimited stdio MCP server loop."""
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    for line in input_stream:
        line = line.strip()
        if not line:
            continue
        response = handle_raw_message(line)
        if response is None:
            continue
        output_stream.write(json.dumps(response, separators=(",", ":")) + "\n")
        output_stream.flush()


def handle_raw_message(raw: str) -> Optional[Any]:
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _error_response(None, -32700, f"Parse error: {exc}")
    if isinstance(message, list):
        responses = [
            response
            for item in message
            if (response := handle_message(item)) is not None
        ]
        return responses or None
    return handle_message(message)


def handle_message(message: Any) -> Optional[JSONValue]:
    if not isinstance(message, dict):
        return _error_response(None, -32600, "Invalid Request")
    has_id = "id" in message
    request_id = message.get("id")
    method = message.get("method")
    if not isinstance(method, str):
        return _error_response(request_id, -32600, "Invalid Request")

    if method == "notifications/initialized":
        return None
    if not has_id:
        return None
    if method == "initialize":
        return _result_response(request_id, _initialize_result(message.get("params", {})))
    if method == "ping":
        return _result_response(request_id, {})
    if method == "tools/list":
        return _result_response(request_id, {"tools": _tools()})
    if method == "tools/call":
        try:
            return _result_response(request_id, _call_tool(message.get("params", {})))
        except KeyError as exc:
            return _error_response(request_id, -32602, str(exc))
        except Exception as exc:  # Tool-originated failures are visible to the model.
            return _result_response(
                request_id,
                _tool_error(str(exc), {"error_type": exc.__class__.__name__}),
            )

    return _error_response(request_id, -32601, f"Method not found: {method}")


def _initialize_result(params: Any) -> JSONValue:
    requested = ""
    if isinstance(params, dict):
        requested = str(params.get("protocolVersion", ""))
    return {
        "protocolVersion": requested or PROTOCOL_VERSION,
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
    }


def _tools() -> List[JSONValue]:
    return [
        {
            "name": "smavg_preflight",
            "title": "Smavg Preflight",
            "description": (
                "Create a timestamped Smavg preflight before repeated agent work. "
                "Use either workflow or source. Returns raw-vs-brief token counts, "
                "assessment, artifact paths, and exact expansion commands."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workflow": {
                        "type": "string",
                        "description": "Named workflow profile, such as x-browsermcp.",
                    },
                    "source": {
                        "type": "string",
                        "description": "Folder path for a directory preflight.",
                    },
                    "out_dir": {
                        "type": "string",
                        "description": "Base output directory for preflight artifacts.",
                        "default": "~/.codex/smavg-preflights",
                    },
                    "budget": {
                        "type": "integer",
                        "description": "Approximate token budget for the context brief.",
                        "default": 3000,
                    },
                    "run_id": {
                        "type": "string",
                        "description": "Optional explicit run directory name.",
                    },
                },
            },
        },
        {
            "name": "smavg_gate",
            "title": "Smavg Gate",
            "description": (
                "Create a Smavg-only input packet for an agent task. The packet "
                "contains gate.md, context.md/json, preflight, receipt, and "
                "receipt-aware exact expansion commands."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "workflow": {"type": "string", "description": "Named workflow profile."},
                    "source": {"type": "string", "description": "Folder path to gate."},
                    "task": {"type": "string", "description": "Task the receiving agent should perform."},
                    "out_dir": {
                        "type": "string",
                        "description": "Base output directory for gate artifacts.",
                        "default": "~/.codex/smavg-gates",
                    },
                    "budget": {"type": "integer", "description": "Context brief budget.", "default": 3000},
                    "run_id": {"type": "string", "description": "Optional explicit run directory name."},
                },
                "required": ["task"],
            },
        },
        {
            "name": "smavg_context",
            "title": "Smavg Context",
            "description": (
                "Build a deterministic context report for a folder. Optionally write "
                "Markdown and JSON outputs. Exact retrieval remains hash verified."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Folder to scan."},
                    "markdown_out": {
                        "type": "string",
                        "description": "Optional path for context.md output.",
                    },
                    "json_out": {
                        "type": "string",
                        "description": "Optional path for context.json output.",
                    },
                    "budget": {
                        "type": "integer",
                        "description": "Approximate token budget for the context brief.",
                    },
                },
                "required": ["source"],
            },
        },
        {
            "name": "smavg_expand",
            "title": "Smavg Expand Context File",
            "description": (
                "Expand one exact file from a Smavg context JSON after SHA-256 verification. "
                "Optionally update a Smavg receipt JSON."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "context_json": {"type": "string", "description": "Path to context JSON."},
                    "path": {"type": "string", "description": "Relative file path in the context."},
                    "out": {"type": "string", "description": "Output file path for exact bytes."},
                    "receipt_json": {
                        "type": "string",
                        "description": "Optional receipt JSON to update with the exact expansion.",
                    },
                },
                "required": ["context_json", "path", "out"],
            },
        },
        {
            "name": "smavg_scan",
            "title": "Smavg Scan",
            "description": (
                "Run a read-only discovery scan. It writes scan.md/scan.json plus context "
                "artifacts for candidate folders/workflows. It never moves or deletes data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root": {"type": "string", "description": "Root directory to scan."},
                    "out_dir": {
                        "type": "string",
                        "description": "Base output directory for scan artifacts.",
                        "default": "~/.codex/smavg-scans",
                    },
                    "run_id": {"type": "string", "description": "Optional explicit run id."},
                    "recursive": {"type": "boolean", "description": "Inspect child directories.", "default": False},
                    "max_depth": {"type": "integer", "description": "Recursive depth.", "default": 1},
                    "max_dirs": {"type": "integer", "description": "Maximum directories to analyze.", "default": 40},
                    "budget": {"type": "integer", "description": "Token budget for candidate briefs.", "default": 3000},
                },
                "required": ["root"],
            },
        },
        {
            "name": "smavg_safe_pack",
            "title": "Smavg Safe Pack",
            "description": (
                "Pack, verify, restore-compare, and optionally move a source directory to "
                "quarantine. This tool never deletes source data."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "Source directory."},
                    "archive": {"type": "string", "description": "Output .smavg archive."},
                    "work_dir": {
                        "type": "string",
                        "description": "Work directory for restore comparison.",
                        "default": "~/.codex/smavg-safe-pack",
                    },
                    "report": {"type": "string", "description": "Optional report JSON path."},
                    "quarantine_dir": {"type": "string", "description": "Optional quarantine directory."},
                    "move_to_quarantine": {
                        "type": "boolean",
                        "description": "Move source to quarantine after verification.",
                        "default": False,
                    },
                },
                "required": ["source", "archive"],
            },
        },
        {
            "name": "smavg_receipt",
            "title": "Smavg Receipt",
            "description": "Create a Smavg run receipt from a context JSON.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "context_json": {"type": "string", "description": "Context JSON path."},
                    "receipt_json": {"type": "string", "description": "Output receipt JSON path."},
                    "context_markdown": {"type": "string", "description": "Optional context markdown path."},
                    "target_label": {"type": "string", "description": "Optional receipt label."},
                },
                "required": ["context_json", "receipt_json"],
            },
        },
        {
            "name": "smavg_workflows",
            "title": "Smavg Workflow Profiles",
            "description": "List known Smavg workflow-context profiles.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "smavg_surface_scan",
            "title": "Smavg Surface Scan",
            "description": (
                "Inventory local skills, plugin-cache skills, workflow profiles, memories, "
                "and sanitized MCP/config summaries. Separates discovered/configured from "
                "locally verified surfaces."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "out_dir": {
                        "type": "string",
                        "description": "Base output directory for surface registry artifacts.",
                        "default": "~/.smavg/surfaces",
                    },
                    "run_id": {"type": "string", "description": "Optional explicit registry run id."},
                    "budget": {"type": "integer", "description": "Context brief budget.", "default": 3000},
                },
            },
        },
        {
            "name": "smavg_surface_gauntlet",
            "title": "Smavg Surface Gauntlet",
            "description": (
                "Run exact-expansion checks and token measurements across local skills, "
                "plugins, workflow profiles, memories, and sanitized MCP/config summaries."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "out": {"type": "string", "description": "Output directory for gauntlet artifacts."},
                    "budget": {"type": "integer", "description": "Context brief budget.", "default": 3000},
                    "repeat_count": {"type": "integer", "description": "Repeated-work count.", "default": 3},
                    "reset": {"type": "boolean", "description": "Delete and recreate output directory.", "default": False},
                },
                "required": ["out"],
            },
        },
        {
            "name": "smavg_status",
            "title": "Smavg Status",
            "description": "Return saved-today, saved-all-time, trust counters, and latest scan.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "autopilot_dir": {
                        "type": "string",
                        "description": "Optional Smavg autopilot directory.",
                    },
                    "ledger": {"type": "string", "description": "Optional ledger JSONL path."},
                },
            },
        },
        {
            "name": "smavg_autopilot",
            "title": "Smavg Autopilot Scan",
            "description": "Run the short read-only Smavg product scan. It never deletes data.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "root": {"type": "string", "description": "Root directory. Defaults to home."},
                    "out_dir": {"type": "string", "description": "Autopilot output directory."},
                    "run_id": {"type": "string", "description": "Optional explicit run id."},
                    "budget": {"type": "integer", "description": "Context brief budget.", "default": 3000},
                    "max_depth": {"type": "integer", "description": "Scan depth.", "default": 1},
                    "max_dirs": {"type": "integer", "description": "Maximum directories.", "default": 40},
                    "include_surfaces": {"type": "boolean", "description": "Include surface registry.", "default": True},
                    "include_workflows": {"type": "boolean", "description": "Include workflow profiles.", "default": True},
                },
            },
        },
        {
            "name": "smavg_daemon_once",
            "title": "Smavg Daemon Once",
            "description": "Run one safe daemon scan/report cycle. It does not delete or quarantine data.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "config": {"type": "string", "description": "Optional daemon config path."},
                    "root": {"type": "string", "description": "Optional root override."},
                    "daemon_dir": {"type": "string", "description": "Optional daemon state directory."},
                    "run_id": {"type": "string", "description": "Optional explicit run id."},
                    "budget": {"type": "integer", "description": "Context brief budget."},
                    "max_depth": {"type": "integer", "description": "Scan depth."},
                    "max_dirs": {"type": "integer", "description": "Maximum directories."},
                },
            },
        },
        {
            "name": "smavg_daemon_status",
            "title": "Smavg Daemon Status",
            "description": "Return latest safe daemon state and truth boundary.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "daemon_dir": {"type": "string", "description": "Optional daemon state directory."},
                    "config": {"type": "string", "description": "Optional daemon config path."},
                },
            },
        },
        {
            "name": "smavg_plugin_build",
            "title": "Smavg Plugin Build",
            "description": "Build the thin local skill/MCP/plugin bundle around the Smavg core.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "out_dir": {"type": "string", "description": "Output bundle directory."},
                    "smavg_command": {"type": "string", "description": "Command shown in examples.", "default": "smavg"},
                    "python": {"type": "string", "description": "Python executable for MCP examples."},
                    "force": {"type": "boolean", "description": "Overwrite existing bundle.", "default": False},
                },
            },
        },
        {
            "name": "smavg_plugin_verify",
            "title": "Smavg Plugin Verify",
            "description": "Verify the thin local Smavg agent bundle exists and wraps the core.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Bundle path."},
                },
            },
        },
        {
            "name": "smavg_verify_archive",
            "title": "Smavg Verify Archive",
            "description": "Verify a .smavg archive and return pass/fail plus failures.",
            "inputSchema": {
                "type": "object",
                "properties": {"archive": {"type": "string", "description": "Path to .smavg archive."}},
                "required": ["archive"],
            },
        },
        {
            "name": "smavg_report_archive",
            "title": "Smavg Report Archive",
            "description": "Return the structured report for a .smavg archive.",
            "inputSchema": {
                "type": "object",
                "properties": {"archive": {"type": "string", "description": "Path to .smavg archive."}},
                "required": ["archive"],
            },
        },
    ]


def _call_tool(params: Any) -> JSONValue:
    if not isinstance(params, dict):
        raise KeyError("tools/call params must be an object")
    name = params.get("name")
    arguments = params.get("arguments", {})
    if not isinstance(name, str):
        raise KeyError("tools/call requires string params.name")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise KeyError("tools/call params.arguments must be an object")

    if name == "smavg_preflight":
        return _tool_success(_tool_preflight(arguments))
    if name == "smavg_gate":
        return _tool_success(_tool_gate(arguments))
    if name == "smavg_context":
        return _tool_success(_tool_context(arguments))
    if name == "smavg_expand":
        return _tool_success(_tool_expand(arguments))
    if name == "smavg_scan":
        return _tool_success(_tool_scan(arguments))
    if name == "smavg_safe_pack":
        return _tool_success(_tool_safe_pack(arguments))
    if name == "smavg_receipt":
        return _tool_success(_tool_receipt(arguments))
    if name == "smavg_workflows":
        return _tool_success({"workflows": available_workflow_profiles()})
    if name == "smavg_surface_scan":
        return _tool_success(_tool_surface_scan(arguments))
    if name == "smavg_surface_gauntlet":
        return _tool_success(_tool_surface_gauntlet(arguments))
    if name == "smavg_status":
        return _tool_success(_tool_status(arguments))
    if name == "smavg_autopilot":
        return _tool_success(_tool_autopilot(arguments))
    if name == "smavg_daemon_once":
        return _tool_success(_tool_daemon_once(arguments))
    if name == "smavg_daemon_status":
        return _tool_success(_tool_daemon_status(arguments))
    if name == "smavg_plugin_build":
        return _tool_success(_tool_plugin_build(arguments))
    if name == "smavg_plugin_verify":
        return _tool_success(_tool_plugin_verify(arguments))
    if name == "smavg_verify_archive":
        return _tool_success(_tool_verify_archive(arguments))
    if name == "smavg_report_archive":
        return _tool_success(_tool_report_archive(arguments))

    raise KeyError(f"Unknown tool: {name}")


def _tool_preflight(arguments: JSONValue) -> JSONValue:
    workflow = _optional_string(arguments, "workflow")
    source = _optional_path(arguments, "source")
    if (workflow is None) == (source is None):
        raise ContextError("smavg_preflight requires exactly one of workflow or source")
    out_dir = _optional_path(arguments, "out_dir") or (Path.home() / ".codex" / "smavg-preflights")
    budget = _optional_int(arguments, "budget", default=3000)
    run_id = _optional_string(arguments, "run_id")
    return run_preflight(
        out_dir=out_dir,
        source=source,
        workflow=workflow,
        budget_tokens=budget,
        run_id=run_id,
    )


def _tool_gate(arguments: JSONValue) -> JSONValue:
    workflow = _optional_string(arguments, "workflow")
    source = _optional_path(arguments, "source")
    if (workflow is None) == (source is None):
        raise ContextError("smavg_gate requires exactly one of workflow or source")
    task = _required_string(arguments, "task")
    out_dir = _optional_path(arguments, "out_dir") or (Path.home() / ".codex" / "smavg-gates")
    budget = _optional_int(arguments, "budget", default=3000)
    run_id = _optional_string(arguments, "run_id")
    return run_gate(
        out_dir=out_dir,
        source=source,
        workflow=workflow,
        task=task,
        budget_tokens=budget,
        run_id=run_id,
    )


def _tool_context(arguments: JSONValue) -> JSONValue:
    source = _required_path(arguments, "source")
    markdown_out = _optional_path(arguments, "markdown_out")
    json_out = _optional_path(arguments, "json_out")
    budget = _optional_int(arguments, "budget")
    report = build_context_report(source, budget_tokens=budget)
    if markdown_out is not None or json_out is not None:
        write_context_outputs(report, markdown_out, json_out)
    return {
        "source": str(source),
        "markdown_out": str(markdown_out) if markdown_out is not None else None,
        "json_out": str(json_out) if json_out is not None else None,
        "files": report.get("file_count", 0),
        "raw_tokens_estimate": report.get("original_tokens_estimate", 0),
        "brief_tokens_estimate": report.get("brief_tokens_estimate", 0),
        "token_reduction_ratio": report.get("token_reduction_ratio"),
        "assessment": report.get("assessment", {}),
        "recommended_expansions": report.get("recommended_expansions", [])[:8],
    }


def _tool_expand(arguments: JSONValue) -> JSONValue:
    context_json = _required_path(arguments, "context_json")
    relative_path = _required_string(arguments, "path")
    out = _required_path(arguments, "out")
    receipt_json = _optional_path(arguments, "receipt_json")
    size = expand_context_file(context_json, relative_path, out)
    if receipt_json is not None:
        append_expansion_to_receipt(
            receipt_json=receipt_json,
            context_json=context_json,
            relative_path=relative_path,
            expanded_output=out,
        )
    return {
        "context_json": str(context_json),
        "path": relative_path,
        "out": str(out),
        "receipt_json": str(receipt_json) if receipt_json is not None else None,
        "bytes": size,
        "verified": True,
    }


def _tool_scan(arguments: JSONValue) -> JSONValue:
    root = _required_path(arguments, "root")
    out_dir = _optional_path(arguments, "out_dir") or (Path.home() / ".codex" / "smavg-scans")
    run_id = _optional_string(arguments, "run_id")
    recursive = _optional_bool(arguments, "recursive", default=False)
    max_depth = _optional_int(arguments, "max_depth", default=1)
    max_dirs = _optional_int(arguments, "max_dirs", default=40)
    budget = _optional_int(arguments, "budget", default=3000)
    return run_scan(
        root=root,
        out_dir=out_dir,
        run_id=run_id,
        recursive=recursive,
        max_depth=max_depth or 1,
        max_dirs=max_dirs or 40,
        budget_tokens=budget,
    )


def _tool_safe_pack(arguments: JSONValue) -> JSONValue:
    source = _required_path(arguments, "source")
    archive = _required_path(arguments, "archive")
    work_dir = _optional_path(arguments, "work_dir") or (Path.home() / ".codex" / "smavg-safe-pack")
    report_path = _optional_path(arguments, "report")
    quarantine_dir = _optional_path(arguments, "quarantine_dir")
    move_to_quarantine = _optional_bool(arguments, "move_to_quarantine", default=False)
    report = safe_pack(
        source=source,
        archive=archive,
        work_dir=work_dir,
        quarantine_dir=quarantine_dir,
        move_to_quarantine=move_to_quarantine,
    )
    if report_path is not None:
        write_safe_pack_report(report, report_path)
        report["report_json"] = str(report_path)
        report["report_markdown"] = str(report_path.with_suffix(".md"))
    return report


def _tool_receipt(arguments: JSONValue) -> JSONValue:
    context_json = _required_path(arguments, "context_json")
    receipt_json = _required_path(arguments, "receipt_json")
    context_markdown = _optional_path(arguments, "context_markdown")
    target_label = _optional_string(arguments, "target_label")
    return create_receipt_from_context(
        context_json=context_json,
        receipt_json=receipt_json,
        context_markdown=context_markdown,
        target_label=target_label,
    )


def _tool_surface_scan(arguments: JSONValue) -> JSONValue:
    out_dir = _optional_path(arguments, "out_dir") or (Path.home() / ".smavg" / "surfaces")
    run_id = _optional_string(arguments, "run_id")
    budget = _optional_int(arguments, "budget", default=3000)
    registry = scan_surfaces(out_dir=out_dir, run_id=run_id, budget_tokens=budget or 3000)
    summary = registry.get("summary", {})
    return {
        "run_dir": registry.get("run_dir"),
        "surfaces_json": registry.get("surfaces_json"),
        "surfaces_markdown": registry.get("surfaces_markdown"),
        "summary": summary,
        "truth_boundary": registry.get("truth_boundary"),
    }


def _tool_surface_gauntlet(arguments: JSONValue) -> JSONValue:
    out = _required_path(arguments, "out")
    budget = _optional_int(arguments, "budget", default=3000)
    repeat_count = _optional_int(arguments, "repeat_count", default=3)
    reset = _optional_bool(arguments, "reset", default=False)
    report = run_surface_gauntlet(
        out,
        budget_tokens=budget or 3000,
        repeat_count=repeat_count or 3,
        reset=reset,
    )
    return {
        "output_dir": report.get("output_dir"),
        "results_json": str(out / "results.json"),
        "report_markdown": str(out / "report.md"),
        "registry_json": report.get("registry_json"),
        "summary": report.get("summary", {}),
        "trust_rule": report.get("trust_rule"),
    }


def _tool_status(arguments: JSONValue) -> JSONValue:
    autopilot_dir = _optional_path(arguments, "autopilot_dir") or default_autopilot_dir()
    ledger = _optional_path(arguments, "ledger") or default_ledger_path()
    return autopilot_status(out_dir=autopilot_dir, ledger_path=ledger)


def _tool_autopilot(arguments: JSONValue) -> JSONValue:
    root = _optional_path(arguments, "root") or Path.home()
    out_dir = _optional_path(arguments, "out_dir") or default_autopilot_dir()
    run_id = _optional_string(arguments, "run_id")
    budget = _optional_int(arguments, "budget", default=3000)
    max_depth = _optional_int(arguments, "max_depth", default=1)
    max_dirs = _optional_int(arguments, "max_dirs", default=40)
    include_surfaces = _optional_bool(arguments, "include_surfaces", default=True)
    include_workflows = _optional_bool(arguments, "include_workflows", default=True)
    return run_autopilot_scan(
        root=root,
        out_dir=out_dir,
        run_id=run_id,
        budget_tokens=budget or 3000,
        recursive=True,
        max_depth=max_depth or 1,
        max_dirs=max_dirs or 40,
        include_surfaces=include_surfaces,
        include_workflows=include_workflows,
    )


def _tool_daemon_once(arguments: JSONValue) -> JSONValue:
    return run_daemon_once(
        config_path=_optional_path(arguments, "config"),
        root=_optional_path(arguments, "root"),
        daemon_dir=_optional_path(arguments, "daemon_dir"),
        run_id=_optional_string(arguments, "run_id"),
        budget_tokens=_optional_int(arguments, "budget"),
        max_depth=_optional_int(arguments, "max_depth"),
        max_dirs=_optional_int(arguments, "max_dirs"),
        create_config=True,
    )


def _tool_daemon_status(arguments: JSONValue) -> JSONValue:
    return daemon_status(
        daemon_dir=_optional_path(arguments, "daemon_dir") or default_daemon_dir(),
        config_path=_optional_path(arguments, "config"),
    )


def _tool_plugin_build(arguments: JSONValue) -> JSONValue:
    return build_plugin_bundle(
        out_dir=_optional_path(arguments, "out_dir") or default_plugin_dir(),
        smavg_command=_optional_string(arguments, "smavg_command") or "smavg",
        python_executable=_optional_string(arguments, "python"),
        force=_optional_bool(arguments, "force", default=False),
    )


def _tool_plugin_verify(arguments: JSONValue) -> JSONValue:
    return verify_plugin_bundle(_optional_path(arguments, "path") or default_plugin_dir())


def _tool_verify_archive(arguments: JSONValue) -> JSONValue:
    archive = _required_path(arguments, "archive")
    ok, failures = verify_container(archive)
    return {"archive": str(archive), "verified": ok, "failures": failures}


def _tool_report_archive(arguments: JSONValue) -> JSONValue:
    archive = _required_path(arguments, "archive")
    return report_container(archive)


def _tool_success(structured: JSONValue) -> JSONValue:
    return {
        "content": [{"type": "text", "text": json.dumps(structured, indent=2, sort_keys=True)}],
        "structuredContent": structured,
        "isError": False,
    }


def _tool_error(message: str, structured: Optional[JSONValue] = None) -> JSONValue:
    payload: JSONValue = {"message": message}
    if structured:
        payload.update(structured)
    return {
        "content": [{"type": "text", "text": message}],
        "structuredContent": payload,
        "isError": True,
    }


def _result_response(request_id: Any, result: Any) -> JSONValue:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error_response(request_id: Any, code: int, message: str) -> JSONValue:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _required_string(arguments: JSONValue, key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ContextError(f"Missing required string argument: {key}")
    return value


def _optional_string(arguments: JSONValue, key: str) -> Optional[str]:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ContextError(f"Argument must be a non-empty string: {key}")
    return value


def _required_path(arguments: JSONValue, key: str) -> Path:
    return _path_from_string(_required_string(arguments, key))


def _optional_path(arguments: JSONValue, key: str) -> Optional[Path]:
    value = _optional_string(arguments, key)
    return None if value is None else _path_from_string(value)


def _path_from_string(value: str) -> Path:
    return Path(value).expanduser()


def _optional_int(arguments: JSONValue, key: str, default: Optional[int] = None) -> Optional[int]:
    value = arguments.get(key, default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContextError(f"Argument must be an integer: {key}")
    if value <= 0:
        raise ContextError(f"Argument must be positive: {key}")
    return value


def _optional_bool(arguments: JSONValue, key: str, default: bool = False) -> bool:
    value = arguments.get(key, default)
    if not isinstance(value, bool):
        raise ContextError(f"Argument must be a boolean: {key}")
    return value


def main(argv: Iterable[str] | None = None) -> int:
    del argv
    try:
        serve()
    except (BrokenPipeError, KeyboardInterrupt):
        return 0
    except (
        AutopilotError,
        ContainerError,
        ContextError,
        DaemonError,
        LedgerError,
        PluginError,
        SurfaceError,
    ) as exc:
        print(f"smavg-mcp: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
