"""Agent plugin bundle builder for Smavg.

The bundle is deliberately thin. It packages instructions, MCP configuration,
and command examples, while all behavior remains in the verified Smavg core.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


class PluginError(RuntimeError):
    """Raised when a Smavg agent bundle cannot be built or verified."""


PLUGIN_TRUTH_BOUNDARY = (
    "The Smavg agent bundle contains wrapper instructions and MCP config only. "
    "It does not fork compression logic. All storage, context, exact expansion, "
    "daemon, and ledger behavior must call the local Smavg CLI/MCP core."
)

SMAVG_LICENSE_NAME = "Smavg Modified MIT License, Version Genesis 1.0 2026"


def default_plugin_dir() -> Path:
    return Path.home() / ".smavg" / "plugin" / "smavg-agent"


def build_plugin_bundle(
    *,
    out_dir: Optional[Path] = None,
    smavg_command: str = "smavg",
    python_executable: Optional[str] = None,
    force: bool = False,
) -> Dict[str, object]:
    target = Path(out_dir or default_plugin_dir()).expanduser()
    if target.exists() and any(target.iterdir()) and not force:
        raise PluginError(f"Plugin bundle already exists. Use --force to rebuild: {target}")
    target.mkdir(parents=True, exist_ok=True)
    py = python_executable or sys.executable or "python3"
    files = {
        "manifest": target / "manifest.json",
        "readme": target / "README.md",
        "skill": target / "skills" / "smavg-repetition-firewall" / "SKILL.md",
        "mcp": target / "mcp" / "smavg-mcp.json",
        "codex": target / "examples" / "codex-mcp.json",
        "kimi": target / "examples" / "kimi-smavg.md",
        "gemini": target / "examples" / "gemini-smavg.md",
    }
    manifest = _manifest(target=target, smavg_command=smavg_command, python_executable=py, files=files)
    _write_json_atomic(files["manifest"], manifest)
    _write_text_atomic(files["readme"], _readme(smavg_command))
    _write_text_atomic(files["skill"], _skill_markdown(smavg_command))
    _write_json_atomic(files["mcp"], _mcp_config(py))
    _write_json_atomic(files["codex"], _codex_mcp_config(py))
    _write_text_atomic(files["kimi"], _generic_agent_markdown("Kimi", smavg_command))
    _write_text_atomic(files["gemini"], _generic_agent_markdown("Gemini", smavg_command))
    summary = {
        "format": "smavg-plugin-bundle",
        "version": 1,
        "generated_at": _now(),
        "out_dir": str(target),
        "smavg_command": smavg_command,
        "python_executable": py,
        "files": {key: str(path) for key, path in files.items()},
        "surfaces": ["skill", "mcp", "codex-example", "kimi-notes", "gemini-notes"],
        "truth_boundary": PLUGIN_TRUTH_BOUNDARY,
    }
    _write_json_atomic(target / "build.json", summary)
    _write_text_atomic(target / "build.md", render_plugin_markdown(summary))
    return summary


def verify_plugin_bundle(path: Optional[Path] = None) -> Dict[str, object]:
    root = Path(path or default_plugin_dir()).expanduser()
    checks = []
    required = [
        "manifest.json",
        "README.md",
        "skills/smavg-repetition-firewall/SKILL.md",
        "mcp/smavg-mcp.json",
        "examples/codex-mcp.json",
        "examples/kimi-smavg.md",
        "examples/gemini-smavg.md",
        "build.json",
        "build.md",
    ]
    for rel in required:
        item = root / rel
        checks.append(_check(rel, item.exists(), str(item)))
    manifest = None
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        checks.append(_check("manifest_format", manifest.get("format") == "smavg-agent-plugin", "manifest.json"))
    except (OSError, json.JSONDecodeError) as exc:
        checks.append(_check("manifest_format", False, str(exc)))
    if isinstance(manifest, dict):
        checks.append(_check("core_wrapped", manifest.get("logic_policy") == "wrap-smavg-core-only", "no forked logic"))
    passed = sum(1 for item in checks if item["pass"])
    return {
        "format": "smavg-plugin-verify",
        "version": 1,
        "generated_at": _now(),
        "path": str(root),
        "status": "PASS" if passed == len(checks) else "FAIL",
        "pass": passed,
        "total": len(checks),
        "checks": checks,
        "truth_boundary": PLUGIN_TRUTH_BOUNDARY,
    }


def render_plugin_markdown(summary: Dict[str, object]) -> str:
    files = summary.get("files", {}) if isinstance(summary.get("files"), dict) else {}
    lines = [
        "# Smavg Agent Plugin Bundle",
        "",
        "This bundle exposes Smavg as a skill/MCP/plugin wrapper around the local core.",
        "",
        "## Surfaces",
        "",
        "- Skill: teaches an agent to map first, exact-expand second, verify always.",
        "- MCP: exposes Smavg tools to MCP-compatible agents.",
        "- Agent notes: minimal setup text for Kimi, Gemini, and similar CLI agents.",
        "",
        "## Files",
        "",
    ]
    for key, value in sorted(files.items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Hard Rule",
            "",
            "The bundle does not implement Smavg logic. It calls the local Smavg CLI/MCP core.",
            "",
            "## Truth Boundary",
            "",
            str(summary.get("truth_boundary", PLUGIN_TRUTH_BOUNDARY)),
            "",
        ]
    )
    return "\n".join(lines)


def _manifest(
    *,
    target: Path,
    smavg_command: str,
    python_executable: str,
    files: Dict[str, Path],
) -> Dict[str, object]:
    return {
        "format": "smavg-agent-plugin",
        "version": 1,
        "name": "smavg",
        "title": "Smavg Repetition Firewall",
        "description": "Local-first repetition firewall for data and AI agents.",
        "generated_at": _now(),
        "root": str(target),
        "brand": "Smavg",
        "builder": "Aegis Wizard",
        "founder": "Roman Mataru",
        "license": SMAVG_LICENSE_NAME,
        "logic_policy": "wrap-smavg-core-only",
        "commands": {
            "scan": f"{smavg_command} scan",
            "report": f"{smavg_command} report",
            "status": f"{smavg_command} status",
            "apply": f"{smavg_command} apply SOURCE --out archive.smavg",
            "daemon_once": f"{smavg_command} daemon once",
            "mcp": f"{python_executable} -m smavg.mcp_server",
        },
        "files": {key: str(value) for key, value in files.items()},
        "truth_boundary": PLUGIN_TRUTH_BOUNDARY,
    }


def _readme(smavg_command: str) -> str:
    return f"""# Smavg Agent Bundle

Smavg is a local-first repetition firewall for data and AI agents.

Use it like this:

```bash
{smavg_command} scan
{smavg_command} report
{smavg_command} status
{smavg_command} daemon once
```

For agent work:

1. Read the Smavg map first.
2. Exact-expand only the files needed for the task.
3. Verify exact bytes.
4. Record the X reduction in the ledger.

No cloud, no API keys, and no internet are required for the core.

License: {SMAVG_LICENSE_NAME}

Truth boundary: {PLUGIN_TRUTH_BOUNDARY}
"""


def _skill_markdown(smavg_command: str) -> str:
    return f"""---
name: smavg-repetition-firewall
description: Use when reducing repeated AI context, building Smavg context maps, exact-expanding files, running Smavg status/report, or preparing repeated agent workflows.
---

# Smavg Repetition Firewall

Use Smavg before reading large repeated folders, skills, memories, runbooks, or workflow histories.

Core rule:

- Map first.
- Exact expand second.
- Verify always.
- Count X saved.
- Never regenerate exact file contents with AI.

This skill does not replace Smavg core verification; it calls the local core.

Primary commands:

```bash
{smavg_command} scan
{smavg_command} report
{smavg_command} status
{smavg_command} work start --source /path --task "..."
{smavg_command} work expand relative/path.txt
{smavg_command} work end
```

MCP command:

```bash
{sys.executable or "python3"} -m smavg.mcp_server
```

If Smavg reports weak repetition, say so and read the source directly or choose a narrower folder.
"""


def _mcp_config(python_executable: str) -> Dict[str, object]:
    return {
        "mcpServers": {
            "smavg": {
                "command": python_executable,
                "args": ["-m", "smavg.mcp_server"],
                "description": "Smavg local repetition firewall MCP server.",
            }
        }
    }


def _codex_mcp_config(python_executable: str) -> Dict[str, object]:
    return {
        "servers": {
            "smavg": {
                "command": python_executable,
                "args": ["-m", "smavg.mcp_server"],
            }
        }
    }


def _generic_agent_markdown(agent_name: str, smavg_command: str) -> str:
    return f"""# Smavg for {agent_name}

Before reading a repeated folder or workflow setup, run:

```bash
{smavg_command} scan
{smavg_command} report
```

For a specific task, use:

```bash
{smavg_command} work start --source /path/to/folder --task "task"
{smavg_command} work expand relative/file.txt
{smavg_command} work end
```

The agent should read the Smavg map first and request exact files only when
needed. Smavg does not ask the model to recreate exact contents.
"""


def _check(name: str, ok: bool, note: str) -> Dict[str, object]:
    return {"name": name, "pass": bool(ok), "note": note}


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
