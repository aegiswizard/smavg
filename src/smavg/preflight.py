"""Smavg preflight routines for token-efficient agent work."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

from .context import ContextError, build_context_report, write_context_outputs
from .receipt import initialize_receipt_from_preflight
from .workflow_context import build_workflow_context_report


def run_preflight(
    *,
    out_dir: Path,
    source: Optional[Path] = None,
    workflow: Optional[str] = None,
    budget_tokens: Optional[int] = None,
    run_id: Optional[str] = None,
) -> Dict[str, object]:
    """Create a Smavg context brief and a small operational summary."""
    if (source is None) == (workflow is None):
        raise ContextError("Preflight requires exactly one of source or workflow")

    if workflow is not None:
        target_kind = "workflow"
        target_label = f"workflow:{workflow}"
        slug = workflow
        report = build_workflow_context_report(workflow, budget_tokens=budget_tokens)
    else:
        assert source is not None
        source = Path(source).expanduser().resolve()
        target_kind = "directory"
        target_label = str(source)
        slug = source.name or "root"
        report = build_context_report(source, budget_tokens=budget_tokens)

    run_dir = Path(out_dir).expanduser()
    run_dir = run_dir / (run_id or _default_run_id(slug))
    run_dir.mkdir(parents=True, exist_ok=False)

    context_md = run_dir / "context.md"
    context_json = run_dir / "context.json"
    preflight_json = run_dir / "preflight.json"
    preflight_md = run_dir / "preflight.md"
    receipt_json = run_dir / "receipt.json"
    receipt_md = run_dir / "receipt.md"

    write_context_outputs(report, context_md, context_json)
    summary = _summary(
        report=report,
        target_kind=target_kind,
        target_label=target_label,
        run_dir=run_dir,
        context_md=context_md,
        context_json=context_json,
        preflight_md=preflight_md,
        preflight_json=preflight_json,
        receipt_md=receipt_md,
        receipt_json=receipt_json,
    )
    preflight_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    preflight_md.write_text(_render_preflight_markdown(summary), encoding="utf-8")
    initialize_receipt_from_preflight(summary)
    return summary


def _summary(
    *,
    report: Dict[str, object],
    target_kind: str,
    target_label: str,
    run_dir: Path,
    context_md: Path,
    context_json: Path,
    preflight_md: Path,
    preflight_json: Path,
    receipt_md: Path,
    receipt_json: Path,
) -> Dict[str, object]:
    recommended = []
    exact_dir = run_dir / "exact"
    for item in report.get("recommended_expansions", [])[:8]:
        path = str(item.get("path", ""))
        if not path:
            continue
        output = exact_dir / _safe_expansion_name(path)
        recommended.append(
            {
                "path": path,
                "estimated_tokens": item.get("estimated_tokens", 0),
                "reasons": item.get("reasons", []),
                "expand_command": (
                    "smavg expand-context "
                    f"{context_json} {path} --out {output}"
                ),
            }
        )

    return {
        "format": "smavg-preflight",
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_kind": target_kind,
        "target_label": target_label,
        "run_dir": str(run_dir),
        "context_markdown": str(context_md),
        "context_json": str(context_json),
        "preflight_markdown": str(preflight_md),
        "preflight_json": str(preflight_json),
        "receipt_markdown": str(receipt_md),
        "receipt_json": str(receipt_json),
        "files": report.get("file_count", 0),
        "text_files": report.get("text_file_count", 0),
        "binary_files": report.get("binary_file_count", 0),
        "logical_bytes": report.get("logical_bytes", 0),
        "raw_tokens_estimate": report.get("original_tokens_estimate", 0),
        "brief_tokens_estimate": report.get("brief_tokens_estimate", 0),
        "token_reduction_ratio": report.get("token_reduction_ratio"),
        "families_detected": report.get("families_detected", 0),
        "family_coverage_percent": report.get("family_coverage_percent", 0.0),
        "assessment": report.get("assessment", {}),
        "recommended_expansions": recommended,
        "strict_routine": [
            "Read context_markdown first.",
            "Expand exact files only when the brief says they are needed.",
            "Verify expanded files against source hashes before relying on exact content.",
            "Record raw-vs-brief token numbers in the task result.",
        ],
    }


def _render_preflight_markdown(summary: Dict[str, object]) -> str:
    assessment = summary.get("assessment", {})
    ratio = summary.get("token_reduction_ratio")
    ratio_text = "n/a" if ratio is None else f"{ratio}x"
    lines = [
        f"# Smavg Preflight: {summary['target_label']}",
        "",
        "This preflight is the operating entry point for token-efficient agent work.",
        "Read the context brief first, then expand exact files only when needed.",
        "",
        "## Measurement",
        "",
        f"- Target kind: `{summary['target_kind']}`",
        f"- Files: {summary['files']}",
        f"- Text files: {summary['text_files']}",
        f"- Binary files: {summary['binary_files']}",
        f"- Logical bytes: {summary['logical_bytes']}",
        f"- Raw setup tokens estimate: {summary['raw_tokens_estimate']}",
        f"- Brief tokens estimate: {summary['brief_tokens_estimate']}",
        f"- Token reduction: {ratio_text}",
        f"- Families detected: {summary['families_detected']}",
        f"- Family coverage: {summary['family_coverage_percent']}%",
        f"- Assessment: `{assessment.get('status', 'unknown')}`",
        f"- Recommendation: {assessment.get('recommendation', 'not evaluated')}",
        "",
        "## Files",
        "",
        f"- Context brief: `{summary['context_markdown']}`",
        f"- Context JSON: `{summary['context_json']}`",
        f"- Preflight JSON: `{summary['preflight_json']}`",
        f"- Run receipt: `{summary['receipt_markdown']}`",
        f"- Receipt JSON: `{summary['receipt_json']}`",
        "",
        "## Strict Routine",
        "",
    ]
    for item in summary.get("strict_routine", []):
        lines.append(f"- {item}")
    lines.extend(["", "## Recommended Exact Expansions", ""])
    recommended = summary.get("recommended_expansions", [])
    if recommended:
        for item in recommended:
            reasons = ", ".join(item.get("reasons", [])) or "high-signal file"
            lines.extend(
                [
                    f"### `{item['path']}`",
                    "",
                    f"- Estimated tokens: {item.get('estimated_tokens', 0)}",
                    f"- Reasons: {reasons}",
                    "",
                    "```bash",
                    str(item["expand_command"]),
                    "```",
                    "",
                ]
            )
    else:
        lines.append("No high-signal exact expansions were recommended.")
        lines.append("")
    return "\n".join(lines)


def _default_run_id(slug: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{_slug(slug)}"


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._")
    return slug[:80] or "preflight"


def _safe_expansion_name(path: str) -> str:
    return _slug(path.replace("/", "__")) or "exact-file"
