"""Smavg input-gate packets for agent work."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .context import ContextError
from .preflight import run_preflight


class GateError(RuntimeError):
    """Raised when a Smavg gate packet cannot be built."""


def run_gate(
    *,
    out_dir: Path,
    task: str,
    source: Optional[Path] = None,
    workflow: Optional[str] = None,
    budget_tokens: Optional[int] = 3000,
    run_id: Optional[str] = None,
) -> Dict[str, object]:
    """Create the explicit Smavg-only setup packet for an agent task."""
    if not task.strip():
        raise GateError("Gate task cannot be empty")
    if (source is None) == (workflow is None):
        raise GateError("Gate requires exactly one of source or workflow")

    slug = workflow if workflow is not None else Path(source or "source").name
    preflight = run_preflight(
        out_dir=Path(out_dir),
        source=source,
        workflow=workflow,
        budget_tokens=budget_tokens,
        run_id=run_id or _default_run_id(slug),
    )
    run_dir = Path(str(preflight["run_dir"]))
    exact_dir = run_dir / "exact"
    exact_dir.mkdir(exist_ok=True)
    gate_json = run_dir / "gate.json"
    gate_md = run_dir / "gate.md"
    gate = _gate_summary(
        preflight=preflight,
        task=task,
        gate_md=gate_md,
        gate_json=gate_json,
        exact_dir=exact_dir,
    )
    _write_text_atomic(gate_json, json.dumps(gate, indent=2, sort_keys=True) + "\n")
    _write_text_atomic(gate_md, render_gate_markdown(gate))
    return gate


def render_gate_markdown(gate: Dict[str, object]) -> str:
    measurement = gate.get("measurement", {})
    ratio = measurement.get("token_reduction_ratio")
    ratio_text = "n/a" if ratio is None else f"{ratio}x"
    files = gate.get("files", {})
    lines = [
        f"# Smavg Gate: {gate.get('target_label')}",
        "",
        "This is the input packet for the agent task. Use it as the setup context.",
        "Do not read the raw source tree for setup. Expand exact files through Smavg only when needed.",
        "",
        "## Task",
        "",
        str(gate.get("task", "")),
        "",
        "## Gate Rule",
        "",
        "- Treat `context.md` as the map.",
        "- Treat `receipt.json` as the accounting trail.",
        "- Use `smavg expand-context ... --receipt receipt.json` for exact files.",
        "- Do not ask an AI model to regenerate exact file contents.",
        "- This gate proves Smavg-supplied context only; it cannot audit unrelated app history.",
        "",
        "## Measurement",
        "",
        f"- Raw setup tokens estimate: {measurement.get('raw_tokens_estimate', 0)}",
        f"- Gate brief tokens estimate: {measurement.get('brief_tokens_estimate', 0)}",
        f"- Current Smavg-supplied tokens estimate: {measurement.get('current_smavg_supplied_tokens_estimate', 0)}",
        f"- Token reduction: {ratio_text}",
        f"- Full raw source supplied by Smavg: `{measurement.get('full_raw_source_supplied_by_smavg', False)}`",
        f"- Assessment: `{measurement.get('assessment', {}).get('status', 'unknown')}`",
        "",
        "## Packet Files",
        "",
        f"- Gate markdown: `{files.get('gate_markdown')}`",
        f"- Gate JSON: `{files.get('gate_json')}`",
        f"- Context markdown: `{files.get('context_markdown')}`",
        f"- Context JSON: `{files.get('context_json')}`",
        f"- Preflight markdown: `{files.get('preflight_markdown')}`",
        f"- Receipt markdown: `{files.get('receipt_markdown')}`",
        f"- Receipt JSON: `{files.get('receipt_json')}`",
        f"- Exact expansion directory: `{files.get('exact_dir')}`",
        "",
        "## Recommended Exact Expansions",
        "",
    ]
    recommended = gate.get("recommended_expansions", [])
    if recommended:
        for item in recommended:
            lines.extend(
                [
                    f"### `{item.get('path')}`",
                    "",
                    f"- Estimated tokens: {item.get('estimated_tokens', 0)}",
                    f"- Reasons: {', '.join(item.get('reasons', [])) or 'high-signal file'}",
                    "",
                    "```bash",
                    str(item.get("expand_command")),
                    "```",
                    "",
                ]
            )
    else:
        lines.append("No recommended exact expansions were identified.")
        lines.append("")
    return "\n".join(lines)


def _gate_summary(
    *,
    preflight: Dict[str, object],
    task: str,
    gate_md: Path,
    gate_json: Path,
    exact_dir: Path,
) -> Dict[str, object]:
    recommended = []
    context_json = Path(str(preflight["context_json"]))
    receipt_json = Path(str(preflight["receipt_json"]))
    for item in preflight.get("recommended_expansions", []):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", ""))
        if not path:
            continue
        output = exact_dir / _safe_expansion_name(path)
        recommended.append(
            {
                "path": path,
                "estimated_tokens": int(item.get("estimated_tokens", 0)),
                "reasons": item.get("reasons", []),
                "output": str(output),
                "expand_command": (
                    "smavg expand-context "
                    f"{context_json} {path} --out {output} --receipt {receipt_json}"
                ),
            }
        )

    raw_tokens = int(preflight.get("raw_tokens_estimate", 0))
    brief_tokens = int(preflight.get("brief_tokens_estimate", 0))
    ratio = round(raw_tokens / brief_tokens, 3) if raw_tokens and brief_tokens else None
    return {
        "format": "smavg-gate",
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "target_kind": preflight.get("target_kind"),
        "target_label": preflight.get("target_label"),
        "run_dir": preflight.get("run_dir"),
        "files": {
            "gate_markdown": str(gate_md),
            "gate_json": str(gate_json),
            "context_markdown": preflight.get("context_markdown"),
            "context_json": preflight.get("context_json"),
            "preflight_markdown": preflight.get("preflight_markdown"),
            "preflight_json": preflight.get("preflight_json"),
            "receipt_markdown": preflight.get("receipt_markdown"),
            "receipt_json": preflight.get("receipt_json"),
            "exact_dir": str(exact_dir),
        },
        "measurement": {
            "raw_tokens_estimate": raw_tokens,
            "brief_tokens_estimate": brief_tokens,
            "current_smavg_supplied_tokens_estimate": brief_tokens,
            "token_reduction_ratio": ratio,
            "full_raw_source_supplied_by_smavg": False,
            "assessment": preflight.get("assessment", {}),
        },
        "recommended_expansions": recommended,
        "operating_rules": [
            "Use gate.md and context.md as the setup packet.",
            "Do not read raw source for setup when the gate is active.",
            "Use exact expansion commands for file contents, citations, or line-level facts.",
            "Every exact expansion must update receipt.json.",
            "The receipt proves Smavg-supplied context only.",
        ],
    }


def _default_run_id(slug: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{_slug(slug)}-gate"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._")
    return slug[:80] or "gate"


def _safe_expansion_name(path: str) -> str:
    return _slug(path.replace("/", "__")) or "exact-file"


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(text, encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
