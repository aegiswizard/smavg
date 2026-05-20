"""Run receipts for Smavg-supplied AI context."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .context import ContextError, estimate_tokens
from .delta import sha256_bytes


class ReceiptError(RuntimeError):
    """Raised when a Smavg run receipt cannot be created or updated."""


def initialize_receipt_from_preflight(summary: Dict[str, object]) -> Dict[str, object]:
    """Write the initial receipt for a preflight run."""
    receipt_json = Path(str(summary["receipt_json"]))
    receipt_markdown = Path(str(summary["receipt_markdown"]))
    receipt = _base_receipt(
        target_kind=str(summary.get("target_kind", "unknown")),
        target_label=str(summary.get("target_label", "")),
        context_json=Path(str(summary["context_json"])),
        context_markdown=Path(str(summary["context_markdown"])),
        raw_tokens=int(summary.get("raw_tokens_estimate", 0)),
        brief_tokens=int(summary.get("brief_tokens_estimate", 0)),
        logical_bytes=int(summary.get("logical_bytes", 0)),
        files=int(summary.get("files", 0)),
        text_files=int(summary.get("text_files", 0)),
        binary_files=int(summary.get("binary_files", 0)),
    )
    _write_receipt(receipt, receipt_json, receipt_markdown)
    return receipt


def create_receipt_from_context(
    *,
    context_json: Path,
    receipt_json: Path,
    receipt_markdown: Optional[Path] = None,
    context_markdown: Optional[Path] = None,
    target_label: Optional[str] = None,
) -> Dict[str, object]:
    """Create a receipt directly from an existing Smavg context JSON."""
    report = _read_context_json(context_json)
    receipt = _base_receipt(
        target_kind=str(report.get("source_kind", "directory")),
        target_label=target_label or str(report.get("source_path", context_json)),
        context_json=Path(context_json),
        context_markdown=context_markdown,
        raw_tokens=int(report.get("original_tokens_estimate", 0)),
        brief_tokens=int(report.get("brief_tokens_estimate", 0)),
        logical_bytes=int(report.get("logical_bytes", 0)),
        files=int(report.get("file_count", 0)),
        text_files=int(report.get("text_file_count", 0)),
        binary_files=int(report.get("binary_file_count", 0)),
    )
    _write_receipt(receipt, receipt_json, receipt_markdown or receipt_json.with_suffix(".md"))
    return receipt


def append_expansion_to_receipt(
    *,
    receipt_json: Path,
    context_json: Path,
    relative_path: str,
    expanded_output: Path,
) -> Dict[str, object]:
    """Record a hash-verified exact expansion as Smavg-supplied context."""
    receipt_path = Path(receipt_json)
    markdown_path = receipt_path.with_suffix(".md")
    if receipt_path.exists():
        receipt = _read_receipt(receipt_path)
    else:
        receipt = create_receipt_from_context(
            context_json=context_json,
            receipt_json=receipt_path,
            receipt_markdown=markdown_path,
        )

    report = _read_context_json(context_json)
    record = _file_record(report, relative_path)
    data = Path(expanded_output).read_bytes()
    if len(data) != int(record.get("size", -1)):
        raise ReceiptError(f"Expanded output size does not match context record: {relative_path}")
    if sha256_bytes(data) != str(record.get("sha256", "")):
        raise ReceiptError(f"Expanded output SHA-256 does not match context record: {relative_path}")

    text = _decode_text_for_tokens(data)
    supplied_tokens = estimate_tokens(text) if text is not None else 0
    expansion = {
        "path": relative_path,
        "output": str(Path(expanded_output)),
        "bytes": len(data),
        "tokens_estimate": supplied_tokens,
        "sha256": record["sha256"],
        "verified": True,
        "recorded_at": _now(),
    }
    expansions: List[Dict[str, object]] = [
        item
        for item in receipt["supplied_to_agent"].get("exact_expansions", [])
        if isinstance(item, dict)
    ]
    expansions.append(expansion)
    receipt["supplied_to_agent"]["exact_expansions"] = expansions
    receipt["supplied_to_agent"]["exact_expansion_tokens_estimate"] = sum(
        int(item.get("tokens_estimate", 0)) for item in expansions
    )
    receipt["supplied_to_agent"]["exact_expansion_bytes"] = sum(
        int(item.get("bytes", 0)) for item in expansions
    )
    _refresh_totals(receipt)
    receipt["updated_at"] = _now()
    _write_receipt(receipt, receipt_path, markdown_path)
    return receipt


def render_receipt_markdown(receipt: Dict[str, object]) -> str:
    supplied = receipt.get("supplied_to_agent", {})
    source = receipt.get("raw_material", {})
    verification = receipt.get("verification", {})
    ratio = supplied.get("reduction_ratio")
    ratio_text = "n/a" if ratio is None else f"{ratio}x"
    lines = [
        f"# Smavg Run Receipt: {receipt.get('target_label', '')}",
        "",
        "This receipt records what Smavg supplied. It does not claim to audit",
        "unrelated application context outside Smavg.",
        "",
        "## Raw Material Scanned Locally",
        "",
        f"- Files: {source.get('files', 0)}",
        f"- Text files: {source.get('text_files', 0)}",
        f"- Binary files: {source.get('binary_files', 0)}",
        f"- Logical bytes: {source.get('logical_bytes', 0)}",
        f"- Raw token estimate: {source.get('raw_tokens_estimate', 0)}",
        f"- Scanned locally by Smavg: `{source.get('scanned_locally_by_smavg', False)}`",
        "",
        "## Supplied To Agent Through Smavg",
        "",
        f"- Brief tokens estimate: {supplied.get('brief_tokens_estimate', 0)}",
        f"- Exact expansion tokens estimate: {supplied.get('exact_expansion_tokens_estimate', 0)}",
        f"- Total Smavg-supplied tokens estimate: {supplied.get('total_tokens_estimate', 0)}",
        f"- Reduction ratio: {ratio_text}",
        f"- Full raw source supplied by Smavg: `{supplied.get('full_raw_source_supplied_by_smavg', False)}`",
        "",
        "## Files",
        "",
        f"- Context JSON: `{receipt.get('context_json')}`",
        f"- Context Markdown: `{receipt.get('context_markdown')}`",
        "",
        "## Exact Expansions",
        "",
    ]
    expansions = supplied.get("exact_expansions", [])
    if expansions:
        for item in expansions:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- `{item.get('path')}`: {item.get('tokens_estimate', 0)} tokens, "
                f"{item.get('bytes', 0)} bytes, verified `{item.get('verified', False)}`, "
                f"sha256 `{item.get('sha256')}`"
            )
    else:
        lines.append("No exact expansions have been supplied yet.")
    lines.extend(
        [
            "",
            "## Verification",
            "",
            f"- Exact expansions verified: `{verification.get('exact_expansions_verified', False)}`",
            "- Trust boundary: Smavg can prove Smavg-supplied context only.",
        ]
    )
    return "\n".join(lines) + "\n"


def _base_receipt(
    *,
    target_kind: str,
    target_label: str,
    context_json: Path,
    context_markdown: Optional[Path],
    raw_tokens: int,
    brief_tokens: int,
    logical_bytes: int,
    files: int,
    text_files: int,
    binary_files: int,
) -> Dict[str, object]:
    receipt: Dict[str, object] = {
        "format": "smavg-run-receipt",
        "version": 1,
        "generated_at": _now(),
        "updated_at": _now(),
        "target_kind": target_kind,
        "target_label": target_label,
        "context_json": str(Path(context_json)),
        "context_markdown": str(context_markdown) if context_markdown is not None else None,
        "raw_material": {
            "files": files,
            "text_files": text_files,
            "binary_files": binary_files,
            "logical_bytes": logical_bytes,
            "raw_tokens_estimate": raw_tokens,
            "scanned_locally_by_smavg": True,
        },
        "supplied_to_agent": {
            "brief_tokens_estimate": brief_tokens,
            "exact_expansion_tokens_estimate": 0,
            "exact_expansion_bytes": 0,
            "total_tokens_estimate": brief_tokens,
            "reduction_ratio": None,
            "full_raw_source_supplied_by_smavg": False,
            "exact_expansions": [],
        },
        "verification": {
            "hash_algorithm": "sha256",
            "exact_expansions_verified": True,
            "ai_regenerated_exact_bytes": False,
        },
        "trust_boundary": (
            "This receipt records only context supplied by Smavg. It cannot prove "
            "what unrelated app history or non-Smavg tools supplied."
        ),
    }
    _refresh_totals(receipt)
    return receipt


def _refresh_totals(receipt: Dict[str, object]) -> None:
    raw_tokens = int(receipt.get("raw_material", {}).get("raw_tokens_estimate", 0))
    supplied = receipt["supplied_to_agent"]
    total = int(supplied.get("brief_tokens_estimate", 0)) + int(
        supplied.get("exact_expansion_tokens_estimate", 0)
    )
    supplied["total_tokens_estimate"] = total
    supplied["reduction_ratio"] = round(raw_tokens / total, 3) if raw_tokens and total else None


def _read_context_json(context_json: Path) -> Dict[str, object]:
    try:
        report = json.loads(Path(context_json).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReceiptError(f"Could not read context JSON: {context_json}") from exc
    if report.get("format") != "smavg-context" or report.get("version") != 1:
        raise ReceiptError("Unsupported context JSON for receipt")
    return report


def _read_receipt(receipt_json: Path) -> Dict[str, object]:
    try:
        receipt = json.loads(Path(receipt_json).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReceiptError(f"Could not read receipt JSON: {receipt_json}") from exc
    if receipt.get("format") != "smavg-run-receipt" or receipt.get("version") != 1:
        raise ReceiptError("Unsupported Smavg receipt")
    return receipt


def _write_receipt(receipt: Dict[str, object], receipt_json: Path, receipt_markdown: Path) -> None:
    _write_text_atomic(receipt_json, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    _write_text_atomic(receipt_markdown, render_receipt_markdown(receipt))


def _file_record(report: Dict[str, object], relative_path: str) -> Dict[str, object]:
    for item in report.get("files", []):
        if isinstance(item, dict) and item.get("path") == relative_path:
            return item
    raise ReceiptError(f"Path not found in context JSON: {relative_path}")


def _decode_text_for_tokens(data: bytes) -> Optional[str]:
    if not data:
        return ""
    sample = data[:8192]
    if b"\x00" in sample:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("latin1")
        except UnicodeDecodeError:
            return None


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
