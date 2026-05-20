"""Real-corpus gauntlet runner for Smavg archives."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .container import ContainerError, pack_container, restore_container, verify_container
from .realdata import (
    write_cisa_kev_corpus,
    write_loghub_corpus,
    write_nvd_cve_corpus,
    write_weather_csv_corpus,
)


class GauntletError(RuntimeError):
    """Raised when a gauntlet cannot be prepared or executed."""


SENSITIVE_RELATIVE_ROOTS = {
    ".ssh",
    ".gnupg",
    ".aws",
    ".config/gcloud",
    ".docker",
    "Library/Keychains",
    "Library/Mail",
    "Library/Messages",
    "Library/Application Support/Google/Chrome",
    "Library/Application Support/Firefox",
    "Library/Application Support/BraveSoftware",
    "Library/Application Support/Signal",
    "Library/Application Support/Telegram Desktop",
}

SENSITIVE_NAME_PARTS = {
    "keychain",
    "wallet",
    "password",
    "1password",
    "bitwarden",
}


@dataclass
class FileRecord:
    path: Path
    relative: str
    size: int
    disk_bytes: int
    mode: int
    nlink: int


@dataclass
class DirectoryRecord:
    path: Path
    relative: str
    mode: int


@dataclass
class SymlinkRecord:
    path: Path
    relative: str
    target: str


@dataclass
class UnsupportedEntry:
    path: str
    reason: str
    blocking: bool = True


@dataclass
class CorpusScan:
    source: Path
    files: List[FileRecord] = field(default_factory=list)
    directories: List[DirectoryRecord] = field(default_factory=list)
    symlinks: List[SymlinkRecord] = field(default_factory=list)
    unsupported: List[UnsupportedEntry] = field(default_factory=list)
    metadata_warnings: List[UnsupportedEntry] = field(default_factory=list)

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def apparent_bytes(self) -> int:
        return sum(item.size for item in self.files)

    @property
    def disk_bytes(self) -> int:
        return sum(item.disk_bytes for item in self.files)

    @property
    def blocking_unsupported_count(self) -> int:
        return sum(1 for item in self.unsupported if item.blocking)

    @property
    def unsupported_count(self) -> int:
        return len(self.unsupported)


@dataclass
class CorpusSpec:
    name: str
    path: Path
    stage: str
    notes: str = ""


def run_gauntlet(
    sources: Iterable[Path],
    output_dir: Path,
    *,
    preset: Optional[str] = None,
    baselines: str = "thorough",
    allow_sensitive: bool = False,
    keep_baselines: bool = False,
) -> Dict[str, object]:
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    specs = []
    if preset:
        specs.extend(_preset_sources(preset, output_dir))
    for source in sources:
        path = Path(source).expanduser().resolve()
        specs.append(CorpusSpec(name=_safe_name(path.name or "source"), path=path, stage="custom"))
    if not specs:
        raise GauntletError("No gauntlet sources were provided")

    archives_dir = output_dir / "archives"
    restores_dir = output_dir / "restored"
    baselines_dir = output_dir / "baselines"
    archives_dir.mkdir(parents=True, exist_ok=True)
    restores_dir.mkdir(parents=True, exist_ok=True)
    baselines_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for spec in specs:
        results.append(
            run_gauntlet_corpus(
                spec,
                archives_dir=archives_dir,
                restores_dir=restores_dir,
                baselines_dir=baselines_dir,
                baselines=baselines,
                allow_sensitive=allow_sensitive,
                keep_baselines=keep_baselines,
            )
        )

    report = {
        "generated_at": _utc_now(),
        "format": "smavg-gauntlet-v1",
        "preset": preset,
        "baseline_mode": baselines,
        "scope": (
            "regular-file bytes, relative paths, directories including empty "
            "directories, symlinks without following targets, and file/directory "
            "permission modes; timestamps, ownership, and hard-link identity are "
            "not claimed"
        ),
        "output_dir": str(output_dir),
        "summary": _summary(results),
        "results": results,
    }
    (output_dir / "results.json").write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "report.md").write_text(_markdown_report(report), encoding="utf-8")
    return report


def run_gauntlet_corpus(
    spec: CorpusSpec,
    *,
    archives_dir: Path,
    restores_dir: Path,
    baselines_dir: Path,
    baselines: str,
    allow_sensitive: bool,
    keep_baselines: bool,
) -> Dict[str, object]:
    started = time.monotonic()
    archive_name = _unique_name(spec.name, spec.path)
    archive_path = archives_dir / f"{archive_name}.smavg"
    restore_path = restores_dir / archive_name
    baseline_root = baselines_dir / archive_name

    result: Dict[str, object] = {
        "name": spec.name,
        "stage": spec.stage,
        "source": str(spec.path),
        "notes": spec.notes,
        "archive": str(archive_path),
        "restore_dir": str(restore_path),
        "started_at": _utc_now(),
        "pack_status": "not_run",
        "verify": "NOT_RUN",
        "restore": "NOT_RUN",
        "regular_file_diff": "NOT_RUN",
        "tree_fidelity": "NOT_RUN",
        "result_counted": False,
        "full_fidelity_counted": False,
        "failures": [],
        "warnings": [],
        "baselines": {},
    }

    try:
        scan = scan_corpus(spec.path, allow_sensitive=allow_sensitive)
    except GauntletError as exc:
        result["scan_error"] = str(exc)
        result["failures"] = [str(exc)]
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        return result

    result["files_discovered"] = scan.file_count
    result["directories_discovered"] = len(scan.directories)
    result["symlinks_discovered"] = len(scan.symlinks)
    result["original_apparent_bytes"] = scan.apparent_bytes
    result["original_disk_bytes"] = scan.disk_bytes
    result["unsupported_entries"] = [
        {"path": item.path, "reason": item.reason, "blocking": item.blocking}
        for item in scan.unsupported[:50]
    ]
    result["unsupported_count"] = scan.unsupported_count
    result["blocking_unsupported_count"] = scan.blocking_unsupported_count
    result["metadata_warnings"] = [
        {"path": item.path, "reason": item.reason}
        for item in scan.metadata_warnings[:50]
    ]
    result["metadata_warning_count"] = len(scan.metadata_warnings)

    if scan.blocking_unsupported_count:
        result["pack_status"] = "SKIPPED_UNSUPPORTED"
        result["failures"] = [
            "blocking unsupported filesystem entries present; archive skipped to avoid unsafe or incomplete representation"
        ]
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        return result

    if archive_path.exists():
        archive_path.unlink()
    if restore_path.exists():
        shutil.rmtree(restore_path)

    try:
        pack_report = pack_container(spec.path, archive_path)
        result["pack_status"] = "PASS"
        result["smavg_report"] = pack_report
        result["files_archived"] = int(pack_report["file_count"])
        result["smavg_archive_bytes"] = int(pack_report["archive_bytes"])
        result["smavg_payload_bytes"] = int(pack_report["payload_bytes"])
        result["smavg_ratio"] = pack_report["ratio"]
        result["smavg_payload_ratio"] = pack_report["payload_ratio"]
    except (ContainerError, OSError) as exc:
        result["pack_status"] = "FAIL"
        result["failures"] = [f"pack failed: {exc}"]
        result["duration_seconds"] = round(time.monotonic() - started, 3)
        return result

    ok, failures = verify_container(archive_path)
    result["verify"] = "PASS" if ok else "FAIL"
    if failures:
        result.setdefault("failures", []).extend(failures)

    try:
        restored_count = restore_container(archive_path, restore_path)
        result["restore"] = "PASS"
        result["files_restored"] = restored_count
    except (ContainerError, OSError) as exc:
        result["restore"] = "FAIL"
        result.setdefault("failures", []).append(f"restore failed: {exc}")
        restored_count = None

    if result["restore"] == "PASS":
        diff_ok, diff_failures = compare_regular_files(scan, restore_path)
        result["regular_file_diff"] = "PASS" if diff_ok else "FAIL"
        if diff_failures:
            result.setdefault("failures", []).extend(diff_failures[:50])
        tree_ok, tree_failures = compare_full_tree(scan, restore_path)
        result["tree_fidelity"] = "PASS" if tree_ok else "FAIL"
        if tree_failures:
            result.setdefault("failures", []).extend(tree_failures[:50])

    result["baselines"] = run_baselines(spec.path, baseline_root, baselines, keep=keep_baselines)
    _add_baseline_comparison(result)

    content_counted = (
        result.get("pack_status") == "PASS"
        and result.get("verify") == "PASS"
        and result.get("restore") == "PASS"
        and result.get("regular_file_diff") == "PASS"
        and int(result.get("files_archived", -1)) == scan.file_count
        and int(result.get("files_restored", -1)) == scan.file_count
        and scan.unsupported_count == 0
    )
    result["result_counted"] = bool(content_counted)
    result["full_fidelity_counted"] = bool(content_counted and not scan.metadata_warnings)
    if result.get("tree_fidelity") != "PASS":
        result["full_fidelity_counted"] = False
    if content_counted and scan.metadata_warnings:
        result["warnings"].append(
            "regular-file bytes restored, but metadata warnings prevent full-fidelity filesystem claim"
        )
    if not content_counted and not result.get("failures"):
        result["failures"] = ["strict gauntlet counting rule was not satisfied"]

    result["duration_seconds"] = round(time.monotonic() - started, 3)
    return result


def scan_corpus(source: Path, *, allow_sensitive: bool = False) -> CorpusScan:
    source = Path(source).expanduser().resolve()
    if not source.exists():
        raise GauntletError(f"Source does not exist: {source}")
    if not source.is_dir():
        raise GauntletError(f"Gauntlet source must be a directory: {source}")
    if not allow_sensitive and _is_sensitive_root(source):
        raise GauntletError(
            f"Refusing sensitive source without --allow-sensitive: {source}"
        )

    scan = CorpusScan(source=source)
    _scan_dir(source, "", scan)
    return scan


def compare_regular_files(scan: CorpusScan, restored_dir: Path) -> Tuple[bool, List[str]]:
    failures = []
    expected_paths = {item.relative for item in scan.files}
    restored_paths = set()
    for path in restored_dir.rglob("*"):
        if path.is_file() and not path.is_symlink():
            restored_paths.add(path.relative_to(restored_dir).as_posix())

    for missing in sorted(expected_paths - restored_paths)[:50]:
        failures.append(f"missing restored file: {missing}")
    for extra in sorted(restored_paths - expected_paths)[:50]:
        failures.append(f"extra restored file: {extra}")

    by_relative = {item.relative: item for item in scan.files}
    for relative in sorted(expected_paths & restored_paths):
        source_bytes = by_relative[relative].path.read_bytes()
        restored_bytes = (restored_dir / relative).read_bytes()
        if source_bytes != restored_bytes:
            failures.append(f"restored bytes differ: {relative}")
            if len(failures) >= 50:
                break
    return not failures, failures


def compare_full_tree(scan: CorpusScan, restored_dir: Path) -> Tuple[bool, List[str]]:
    failures = []
    regular_ok, regular_failures = compare_regular_files(scan, restored_dir)
    if not regular_ok:
        failures.extend(regular_failures)

    expected_dirs = {item.relative: item for item in scan.directories}
    expected_symlinks = {item.relative: item for item in scan.symlinks}
    expected_regular = {item.relative: item for item in scan.files}
    expected_all = set(expected_dirs) | set(expected_symlinks) | set(expected_regular)

    restored_all = set()
    for path in restored_dir.rglob("*"):
        restored_all.add(path.relative_to(restored_dir).as_posix())

    for missing in sorted(expected_all - restored_all)[:50]:
        failures.append(f"missing restored tree entry: {missing}")
    for extra in sorted(restored_all - expected_all)[:50]:
        failures.append(f"extra restored tree entry: {extra}")

    for relative, record in expected_dirs.items():
        target = restored_dir / relative
        if not target.is_dir() or target.is_symlink():
            failures.append(f"directory not restored as directory: {relative}")
            continue
        if stat.S_IMODE(target.stat().st_mode) != record.mode:
            failures.append(f"directory mode differs: {relative}")

    for relative, record in expected_regular.items():
        target = restored_dir / relative
        if not target.is_file() or target.is_symlink():
            failures.append(f"file not restored as regular file: {relative}")
            continue
        if stat.S_IMODE(target.stat().st_mode) != record.mode:
            failures.append(f"file mode differs: {relative}")

    for relative, record in expected_symlinks.items():
        target = restored_dir / relative
        if not target.is_symlink():
            failures.append(f"symlink not restored as symlink: {relative}")
            continue
        restored_target = os.readlink(target)
        if restored_target != record.target:
            failures.append(f"symlink target differs: {relative}")

    return not failures, failures


def run_baselines(
    source: Path,
    baseline_root: Path,
    mode: str,
    *,
    keep: bool = False,
) -> Dict[str, object]:
    if mode == "none":
        return {}
    if mode not in {"quick", "thorough"}:
        raise GauntletError(f"Unknown baseline mode: {mode}")

    baseline_root.mkdir(parents=True, exist_ok=True)
    specs = _baseline_specs(mode)
    results: Dict[str, object] = {}
    for name, binary, args, suffix in specs:
        if shutil.which(binary) is None:
            results[name] = {"status": "SKIPPED", "reason": f"{binary} not installed"}
            continue
        output = baseline_root / f"archive.tar.{suffix}"
        started = time.monotonic()
        status, reason = _run_tar_compressor(source, binary, args, output)
        item: Dict[str, object] = {
            "status": status,
            "duration_seconds": round(time.monotonic() - started, 3),
        }
        if status == "PASS":
            item["bytes"] = output.stat().st_size
            item["path"] = str(output) if keep else None
            if not keep:
                output.unlink(missing_ok=True)
        else:
            item["reason"] = reason
            output.unlink(missing_ok=True)
        results[name] = item
    if not keep:
        try:
            baseline_root.rmdir()
        except OSError:
            pass
    return results


def _scan_dir(path: Path, relative: str, scan: CorpusScan) -> None:
    try:
        with os.scandir(path) as iterator:
            entries = sorted(list(iterator), key=lambda item: item.name)
    except OSError as exc:
        scan.unsupported.append(
            UnsupportedEntry(relative or ".", f"unreadable directory: {exc}")
        )
        return

    for entry in entries:
        child_relative = f"{relative}/{entry.name}" if relative else entry.name
        try:
            if entry.is_symlink():
                scan.symlinks.append(
                    SymlinkRecord(
                        path=path / entry.name,
                        relative=child_relative,
                        target=os.readlink(path / entry.name),
                    )
                )
                continue
            entry_stat = entry.stat(follow_symlinks=False)
        except OSError as exc:
            scan.unsupported.append(
                UnsupportedEntry(child_relative, f"unreadable entry: {exc}")
            )
            continue

        mode = entry_stat.st_mode
        child_path = path / entry.name
        if stat.S_ISDIR(mode):
            scan.directories.append(
                DirectoryRecord(
                    path=child_path,
                    relative=child_relative,
                    mode=stat.S_IMODE(mode),
                )
            )
            _scan_dir(child_path, child_relative, scan)
        elif stat.S_ISREG(mode):
            disk = int(getattr(entry_stat, "st_blocks", 0)) * 512
            if disk == 0:
                disk = int(entry_stat.st_size)
            file_mode = stat.S_IMODE(mode)
            scan.files.append(
                FileRecord(
                    path=child_path,
                    relative=child_relative,
                    size=int(entry_stat.st_size),
                    disk_bytes=disk,
                    mode=file_mode,
                    nlink=int(getattr(entry_stat, "st_nlink", 1)),
                )
            )
            if int(getattr(entry_stat, "st_nlink", 1)) > 1:
                scan.metadata_warnings.append(
                    UnsupportedEntry(
                        child_relative,
                        "hard-link identity is not preserved by Container v1",
                        blocking=False,
                    )
                )
        else:
            scan.unsupported.append(
                UnsupportedEntry(child_relative, "special filesystem entry is not represented")
            )


def _run_tar_compressor(
    source: Path,
    binary: str,
    args: List[str],
    output: Path,
) -> Tuple[str, str]:
    source = Path(source).resolve()
    env = dict(os.environ)
    env["COPYFILE_DISABLE"] = "1"
    tar_cmd = ["tar", "-cf", "-", "-C", str(source.parent), source.name]
    compressor_cmd = [binary] + args
    with output.open("wb") as handle:
        tar = subprocess.Popen(
            tar_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert tar.stdout is not None
        compressor = subprocess.Popen(
            compressor_cmd,
            stdin=tar.stdout,
            stdout=handle,
            stderr=subprocess.PIPE,
            env=env,
        )
        tar.stdout.close()
        compressor_stderr = compressor.communicate()[1]
        tar_stderr = tar.stderr.read() if tar.stderr is not None else b""
        tar_return = tar.wait()
    if tar_return != 0:
        return "FAIL", tar_stderr.decode("utf-8", errors="replace").strip()
    if compressor.returncode != 0:
        return "FAIL", compressor_stderr.decode("utf-8", errors="replace").strip()
    return "PASS", ""


def _baseline_specs(mode: str) -> List[Tuple[str, str, List[str], str]]:
    if mode == "quick":
        return [
            ("xz", "xz", ["-6", "-c"], "xz"),
            ("zstd", "zstd", ["-6", "-q", "-c"], "zst"),
            ("brotli", "brotli", ["-q", "6", "-c"], "br"),
        ]
    return [
        ("xz", "xz", ["-9e", "-c"], "xz"),
        ("zstd", "zstd", ["-19", "--long=31", "-q", "-c"], "zst"),
        ("brotli", "brotli", ["-q", "11", "-c"], "br"),
    ]


def _add_baseline_comparison(result: Dict[str, object]) -> None:
    baseline_bytes = []
    for name, item in dict(result.get("baselines", {})).items():
        if isinstance(item, dict) and item.get("status") == "PASS" and "bytes" in item:
            baseline_bytes.append((name, int(item["bytes"])))
    if not baseline_bytes or "smavg_archive_bytes" not in result:
        result["best_baseline"] = None
        result["smavg_vs_best_baseline"] = None
        return
    best_name, best_size = min(baseline_bytes, key=lambda item: item[1])
    smavg_size = int(result["smavg_archive_bytes"])
    result["best_baseline"] = {"name": best_name, "bytes": best_size}
    result["smavg_vs_best_baseline"] = round(best_size / smavg_size, 3) if smavg_size else None
    result["beats_best_baseline"] = smavg_size < best_size


def _summary(results: List[Dict[str, object]]) -> Dict[str, object]:
    counted = [item for item in results if item.get("result_counted")]
    full_fidelity = [item for item in results if item.get("full_fidelity_counted")]
    baseline_wins = [item for item in counted if item.get("beats_best_baseline")]
    return {
        "corpora": len(results),
        "counted": len(counted),
        "full_fidelity_counted": len(full_fidelity),
        "not_counted": len(results) - len(counted),
        "verify_pass": sum(1 for item in results if item.get("verify") == "PASS"),
        "restore_pass": sum(1 for item in results if item.get("restore") == "PASS"),
        "diff_pass": sum(1 for item in results if item.get("regular_file_diff") == "PASS"),
        "tree_fidelity_pass": sum(1 for item in results if item.get("tree_fidelity") == "PASS"),
        "beats_best_baseline": len(baseline_wins),
    }


def _markdown_report(report: Dict[str, object]) -> str:
    lines = [
        f"# Smavg Gauntlet Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Preset: {report.get('preset') or 'custom'}",
        f"- Baseline mode: {report['baseline_mode']}",
        f"- Scope: {report['scope']}",
        "",
        "## Summary",
        "",
    ]
    summary = report["summary"]
    lines.extend(
        [
            f"- Corpora: {summary['corpora']}",
            f"- Counted: {summary['counted']}",
            f"- Full-fidelity counted: {summary.get('full_fidelity_counted', 0)}",
            f"- Not counted: {summary['not_counted']}",
            f"- Verify PASS: {summary['verify_pass']}",
            f"- Restore PASS: {summary['restore_pass']}",
            f"- Regular-file diff PASS: {summary['diff_pass']}",
            f"- Tree fidelity PASS: {summary.get('tree_fidelity_pass', 0)}",
            f"- Counted corpora beating best available baseline: {summary['beats_best_baseline']}",
            "",
            "## Results",
            "",
            "| Corpus | Stage | Files | Unsupported | Original | Smavg | Ratio | Best baseline | Smavg vs best | Verify | Diff | Counted | Full fidelity |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | --- | --- | --- |",
        ]
    )
    for item in report["results"]:
        best = item.get("best_baseline")
        best_label = "n/a"
        if isinstance(best, dict):
            best_label = f"{best.get('name')} {_human_bytes(int(best.get('bytes', 0)))}"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("name", "")),
                    str(item.get("stage", "")),
                    str(item.get("files_discovered", "n/a")),
                    str(item.get("unsupported_count", "n/a")),
                    _human_bytes(int(item.get("original_apparent_bytes", 0)))
                    if "original_apparent_bytes" in item
                    else "n/a",
                    _human_bytes(int(item.get("smavg_archive_bytes", 0)))
                    if "smavg_archive_bytes" in item
                    else "n/a",
                    str(item.get("smavg_ratio", "n/a")),
                    best_label,
                    str(item.get("smavg_vs_best_baseline", "n/a")),
                    str(item.get("verify", "n/a")),
                    str(item.get("regular_file_diff", "n/a")),
                    "YES" if item.get("result_counted") else "NO",
                    "YES" if item.get("full_fidelity_counted") else "NO",
                ]
            )
            + " |"
        )
    lines.extend(["", "## Not Counted / Warnings", ""])
    for item in report["results"]:
        if item.get("result_counted") and not item.get("metadata_warning_count"):
            continue
        lines.append(f"### {item.get('name')}")
        if item.get("failures"):
            for failure in item["failures"][:10]:
                lines.append(f"- Failure: {failure}")
        if item.get("unsupported_count"):
            lines.append(f"- Unsupported entries: {item.get('unsupported_count')}")
            for unsupported in item.get("unsupported_entries", [])[:10]:
                lines.append(f"  - {unsupported['path']}: {unsupported['reason']}")
        if item.get("metadata_warning_count"):
            lines.append(f"- Metadata warnings: {item.get('metadata_warning_count')}")
            for warning in item.get("metadata_warnings", [])[:10]:
                lines.append(f"  - {warning['path']}: {warning['reason']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _preset_sources(preset: str, output_dir: Path) -> List[CorpusSpec]:
    if preset == "all":
        specs = []
        for name in ("stage1-local-safe", "stage2-local-reality", "stage3-public"):
            specs.extend(_preset_sources(name, output_dir))
        return specs
    if preset == "stage1-local-safe":
        return _existing_specs(
            [
                ("smavg-repo", Path("/Users/mac/smavg"), "stage1-local-safe", "Smavg project repository"),
                (
                    "codex-memories",
                    Path("/Users/mac/.codex/memories"),
                    "stage1-local-safe",
                    "Codex durable memory markdown/data",
                ),
                (
                    "codex-skills",
                    Path("/Users/mac/.codex/skills"),
                    "stage1-local-safe",
                    "Local Codex skills",
                ),
                (
                    "kimi-skills",
                    Path("/Users/mac/.kimi/skills"),
                    "stage1-local-safe",
                    "Local Kimi skills",
                ),
                (
                    "smavg-patent-research",
                    Path("/Users/mac/smavg/research/patents/2026-05-09-smavg-patent-landscape"),
                    "stage1-local-safe",
                    "Saved Smavg patent/prior-art research",
                ),
                (
                    "luau-history-extracted",
                    Path("/private/tmp/smavg-archive-v1-luau/corpus/records"),
                    "stage1-local-safe",
                    "Existing real extracted Luau file-history proof corpus",
                ),
                (
                    "luau-mixed-history",
                    Path("/private/tmp/smavg-planner-mixed/source"),
                    "stage1-local-safe",
                    "Existing real mixed corpus with Luau histories and unrelated files",
                ),
            ]
        )
    if preset == "stage2-local-reality":
        return _existing_specs(
            [
                (
                    "personal-ops-mcp",
                    Path("/Users/mac/personal-ops-mcp"),
                    "stage2-local-reality",
                    "Local MCP/tooling project",
                ),
                (
                    "plugins",
                    Path("/Users/mac/plugins"),
                    "stage2-local-reality",
                    "Local plugin source tree",
                ),
                (
                    "ontario-dashboard",
                    Path("/Users/mac/ontario-claims-edge/data/dashboard"),
                    "stage2-local-reality",
                    "Local generated dashboard artifacts",
                ),
                (
                    "library-diagnostic-reports",
                    Path("/Users/mac/Library/Logs/DiagnosticReports"),
                    "stage2-local-reality",
                    "Local macOS diagnostic reports, if present",
                ),
            ]
        )
    if preset == "stage3-public":
        public_root = output_dir / "public-corpora"
        public_root.mkdir(parents=True, exist_ok=True)
        specs: List[CorpusSpec] = []
        loghub_root = public_root / "loghub"
        write_loghub_corpus(loghub_root)
        specs.append(
            CorpusSpec(
                "public-loghub-2k",
                loghub_root / "records",
                "stage3-public",
                "Real Loghub 2k raw logs",
            )
        )
        weather_root = public_root / "weather-csv"
        write_weather_csv_corpus(weather_root, limit=10)
        specs.append(
            CorpusSpec(
                "public-weather-csv",
                weather_root / "records",
                "stage3-public",
                "Real public historical weather CSV files",
            )
        )
        cisa_root = public_root / "cisa-kev"
        write_cisa_kev_corpus(cisa_root)
        specs.append(
            CorpusSpec(
                "public-cisa-kev",
                cisa_root / "records",
                "stage3-public",
                "Real CISA KEV JSON records",
            )
        )
        nvd_root = public_root / "nvd-recent"
        write_nvd_cve_corpus(nvd_root, feed="recent", limit=1000)
        specs.append(
            CorpusSpec(
                "public-nvd-recent-1000",
                nvd_root / "records",
                "stage3-public",
                "First 1000 real records from official NVD recent CVE feed",
            )
        )
        return specs
    raise GauntletError(f"Unknown gauntlet preset: {preset}")


def _existing_specs(items: Iterable[Tuple[str, Path, str, str]]) -> List[CorpusSpec]:
    specs = []
    for name, path, stage, notes in items:
        expanded = path.expanduser()
        if expanded.exists() and expanded.is_dir():
            specs.append(CorpusSpec(name, expanded.resolve(), stage, notes))
    return specs


def _is_sensitive_root(path: Path) -> bool:
    home = Path.home().resolve()
    resolved = path.resolve()
    lowered_parts = [part.lower() for part in resolved.parts]
    if any(fragment in part for fragment in SENSITIVE_NAME_PARTS for part in lowered_parts):
        return True
    for relative in SENSITIVE_RELATIVE_ROOTS:
        sensitive = (home / relative).resolve()
        if _is_relative_to(resolved, sensitive):
            return True
    return False


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _unique_name(name: str, path: Path) -> str:
    digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:8]
    return f"{_safe_name(name)}-{digest}"


def _safe_name(value: str) -> str:
    kept = []
    for char in value:
        if char.isalnum() or char in {"-", "_", "."}:
            kept.append(char)
        else:
            kept.append("-")
    name = "".join(kept).strip(".-")
    return name or "corpus"


def _utc_now() -> str:
    return datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _human_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}" if unit != "B" else f"{int(amount)} B"
        amount /= 1024
    return f"{value} B"
