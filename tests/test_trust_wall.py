import json
import os
import stat
import tempfile
import unittest
import zlib
from pathlib import Path

from smavg.container import (
    HEADER,
    MAGIC,
    ContainerError,
    extract_container_file,
    pack_container,
    read_container,
    restore_container,
    verify_container,
)
from smavg.context import ContextError, build_context_report, expand_context_file, write_context_outputs
from smavg.daemon import run_daemon_once, write_daemon_config, write_service_file
from smavg.delta import sha256_bytes
from smavg.ledger import append_event, create_event, ledger_report
from smavg.plugin import SMAVG_LICENSE_NAME, build_plugin_bundle, verify_plugin_bundle
from smavg.receipt import append_expansion_to_receipt, create_receipt_from_context
from smavg.safe_ops import SafePackError, safe_pack


class TrustWallTests(unittest.TestCase):
    def test_container_rejects_absolute_fallback_path(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _simple_archive(Path(temp))
            container = read_container(archive)
            manifest = dict(container.manifest)
            manifest["fallback_files"] = [dict(item) for item in manifest["fallback_files"]]
            manifest["fallback_files"][0]["path"] = "/tmp/smavg-escape.txt"
            _rewrite_container(archive, manifest, container.payload)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("Unsafe archive path", failures[0])

    def test_container_rejects_negative_payload_offset(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _simple_archive(Path(temp))
            container = read_container(archive)
            manifest = dict(container.manifest)
            manifest["fallback_files"] = [dict(item) for item in manifest["fallback_files"]]
            manifest["fallback_files"][0]["offset"] = -1
            _rewrite_container(archive, manifest, container.payload)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("must be non-negative", failures[0])

    def test_container_rejects_header_payload_hash_mismatch_without_payload_change(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _simple_archive(Path(temp))
            data = bytearray(archive.read_bytes())
            magic, manifest_len, payload_len, manifest_sha, _payload_sha = HEADER.unpack(data[: HEADER.size])
            self.assertEqual(magic, MAGIC)
            data[: HEADER.size] = HEADER.pack(
                MAGIC,
                manifest_len,
                payload_len,
                manifest_sha,
                b"\x00" * 32,
            )
            archive.write_bytes(data)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("payload_sha256 does not match header", failures[0])

    def test_extract_refuses_to_overwrite_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = _simple_archive(root)
            output = root / "existing.txt"
            output.write_text("do not overwrite\n", encoding="utf-8")

            with self.assertRaises(ContainerError):
                extract_container_file(archive, "note.txt", output)

            self.assertEqual(output.read_text(encoding="utf-8"), "do not overwrite\n")

    def test_restore_refuses_to_overwrite_existing_symlink_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "target.txt").write_text("target\n", encoding="utf-8")
            try:
                os.symlink("target.txt", source / "target-link")
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")
            archive = root / "tree.smavg"
            pack_container(source, archive)
            restore = root / "restore"
            restore.mkdir()
            (restore / "target-link").write_text("preexisting\n", encoding="utf-8")

            with self.assertRaises(ContainerError):
                restore_container(archive, restore)

            self.assertEqual((restore / "target-link").read_text(encoding="utf-8"), "preexisting\n")

    def test_mixed_binary_empty_and_mode_restore_is_byte_perfect(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            history = source / "reports"
            history.mkdir(parents=True)
            stable = [f"same line {index}\n" for index in range(120)]
            for index in range(9):
                (history / f"report-{index:03d}.md").write_text(
                    "".join(stable[:60] + [f"value {index}\n"] + stable[60:]),
                    encoding="utf-8",
                )
            (source / "empty.bin").write_bytes(b"")
            (source / "binary.dat").write_bytes(bytes(range(256)) * 3)
            tool = source / "run.sh"
            tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            tool.chmod(0o755)
            archive = root / "mixed.smavg"
            restore = root / "restore"

            pack_container(source, archive)
            ok, failures = verify_container(archive)
            restore_container(archive, restore)

            self.assertTrue(ok, failures)
            for path in sorted(item for item in source.rglob("*") if item.is_file()):
                relative = path.relative_to(source)
                self.assertEqual((restore / relative).read_bytes(), path.read_bytes())
            self.assertEqual(stat.S_IMODE((restore / "run.sh").stat().st_mode), 0o755)

    def test_context_expand_refuses_same_size_sha_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            file_path = source / "note.md"
            file_path.write_text("same-length-data-001\n", encoding="utf-8")
            context_json = root / "context.json"
            write_context_outputs(build_context_report(source), None, context_json)
            file_path.write_text("same-length-data-002\n", encoding="utf-8")

            with self.assertRaises(ContextError) as caught:
                expand_context_file(context_json, "note.md", root / "expanded.md")

            self.assertIn("SHA-256 changed", str(caught.exception))

    def test_context_expand_rejects_path_traversal_request(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "note.md").write_text("trusted note\n", encoding="utf-8")
            context_json = root / "context.json"
            write_context_outputs(build_context_report(source), None, context_json)

            with self.assertRaises(ContextError):
                expand_context_file(context_json, "../note.md", root / "expanded.md")

    def test_receipt_records_multiple_exact_expansions_without_raw_dump(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            for name in ("alpha.md", "beta.md", "gamma.md"):
                (source / name).write_text(f"# {name}\nShared instructions.\nUnique {name}.\n", encoding="utf-8")
            context_json = root / "context.json"
            write_context_outputs(build_context_report(source), None, context_json)
            receipt_json = root / "receipt.json"
            receipt = create_receipt_from_context(context_json=context_json, receipt_json=receipt_json)
            brief_tokens = int(receipt["supplied_to_agent"]["brief_tokens_estimate"])

            for name in ("alpha.md", "beta.md"):
                expanded = root / f"expanded-{name}"
                expand_context_file(context_json, name, expanded)
                receipt = append_expansion_to_receipt(
                    receipt_json=receipt_json,
                    context_json=context_json,
                    relative_path=name,
                    expanded_output=expanded,
                )

            supplied = receipt["supplied_to_agent"]
            self.assertFalse(supplied["full_raw_source_supplied_by_smavg"])
            self.assertEqual(len(supplied["exact_expansions"]), 2)
            self.assertGreaterEqual(supplied["total_tokens_estimate"], brief_tokens)
            self.assertTrue(all(item["verified"] for item in supplied["exact_expansions"]))

    def test_ledger_failed_event_is_visible_but_not_counted_as_benefit(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = Path(temp) / "ledger.jsonl"
            append_event(
                create_event(
                    kind="context",
                    label="verified",
                    before={"tokens": 100},
                    after={"tokens": 50},
                    verification={"status": "verified"},
                ),
                ledger,
            )
            append_event(
                create_event(
                    kind="context",
                    label="failed should not win",
                    before={"tokens": 1_000_000},
                    after={"tokens": 1},
                    verification={"status": "failed"},
                ),
                ledger,
            )

            report = ledger_report(ledger_path=ledger)

            self.assertEqual(report["event_count"], 2)
            self.assertEqual(report["trust"]["failed_events"], 1)
            self.assertEqual(report["trust"]["failures_counted_as_wins"], 0)
            self.assertEqual(report["ai_tokens"]["before"], 100)
            self.assertEqual(report["ai_tokens"]["after"], 50)
            self.assertEqual(report["headline"]["tokens_saved_all_time"], 50)

    def test_safe_pack_refuses_archive_inside_source_and_leaves_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "note.md").write_text("safe pack must not risk source\n", encoding="utf-8")

            with self.assertRaises(SafePackError):
                safe_pack(
                    source=source,
                    archive=source / "inside.smavg",
                    work_dir=root / "work",
                    quarantine_dir=root / "quarantine",
                    move_to_quarantine=True,
                )

            self.assertTrue(source.exists())
            self.assertTrue((source / "note.md").exists())
            self.assertFalse((root / "quarantine").exists())

    def test_daemon_once_preserves_source_tree_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            nested = source / "nested"
            nested.mkdir(parents=True)
            (source / "a.md").write_text("daemon read only\n", encoding="utf-8")
            (nested / "b.bin").write_bytes(bytes(range(32)))
            before = _tree_fingerprint(source)
            daemon_dir = root / "daemon"
            config = daemon_dir / "config.json"
            write_daemon_config(
                config_path=config,
                root=source,
                daemon_dir=daemon_dir,
                include_surfaces=False,
                include_workflows=False,
            )

            report = run_daemon_once(
                config_path=config,
                run_id="trust-wall",
                include_surfaces=False,
                include_workflows=False,
            )

            self.assertEqual(before, _tree_fingerprint(source))
            self.assertFalse(report["actions"]["cleanup_performed"])
            self.assertFalse(report["actions"]["delete_performed"])

    def test_service_generation_writes_launchd_file_without_loading(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "daemon" / "config.json"
            write_daemon_config(config_path=config, root=root / "source", daemon_dir=root / "daemon")
            service_path = root / "com.aegiswizard.smavg.daemon.plist"

            service = write_service_file(
                platform_name="launchd",
                out=service_path,
                config_path=config,
                interval_seconds=120,
            )
            text = service_path.read_text(encoding="utf-8")

            self.assertFalse(service["installed"])
            self.assertFalse(service["loaded"])
            self.assertIn("<string>daemon</string>", text)
            self.assertIn("<string>run</string>", text)
            self.assertIn("<string>--cycles</string>", text)
            self.assertIn("<string>1</string>", text)

    def test_plugin_bundle_manifest_declares_genesis_license_and_core_wrapper(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "plugin"
            build_plugin_bundle(out_dir=root, smavg_command="smavg", python_executable="python3")
            verify = verify_plugin_bundle(root)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            skill = (root / "skills" / "smavg-repetition-firewall" / "SKILL.md").read_text(encoding="utf-8")

            self.assertEqual(verify["status"], "PASS")
            self.assertEqual(manifest["license"], SMAVG_LICENSE_NAME)
            self.assertEqual(manifest["logic_policy"], "wrap-smavg-core-only")
            self.assertIn("does not replace Smavg core verification", skill)

    def test_license_metadata_is_consistent_across_public_files(self):
        root = Path(__file__).resolve().parents[1]
        license_text = (root / "LICENSE").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        notice = (root / "NOTICE").read_text(encoding="utf-8")
        pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn(SMAVG_LICENSE_NAME, license_text)
        self.assertIn(SMAVG_LICENSE_NAME, readme)
        self.assertIn(SMAVG_LICENSE_NAME, notice)
        self.assertIn('license = { file = "LICENSE" }', pyproject)
        self.assertNotIn('license = { text = "MIT" }', pyproject)

    def test_weak_context_case_reports_weak_without_fake_win(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "source"
            source.mkdir()
            (source / "one.txt").write_text("alpha beta gamma delta epsilon\n", encoding="utf-8")
            (source / "two.txt").write_text("red green blue yellow purple\n", encoding="utf-8")
            (source / "three.txt").write_text("north south east west center\n", encoding="utf-8")

            report = build_context_report(source)

            self.assertEqual(report["assessment"]["status"], "weak")
            self.assertEqual(report["families_detected"], 0)
            self.assertGreater(report["original_tokens_estimate"], 0)
            self.assertLess(float(report["token_reduction_ratio"] or 0), 2.0)

def _simple_archive(root: Path) -> Path:
    source = root / "source"
    source.mkdir()
    (source / "note.txt").write_text("hello world\n", encoding="utf-8")
    archive = root / "simple.smavg"
    pack_container(source, archive)
    return archive


def _rewrite_container(path: Path, manifest: dict, payload: bytes) -> None:
    manifest["payload_bytes"] = len(payload)
    manifest["payload_sha256"] = sha256_bytes(payload)
    manifest_payload = zlib.compress(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        level=9,
    )
    header = HEADER.pack(
        MAGIC,
        len(manifest_payload),
        len(payload),
        bytes.fromhex(sha256_bytes(manifest_payload)),
        bytes.fromhex(sha256_bytes(payload)),
    )
    path.write_bytes(header + manifest_payload + payload)


def _tree_fingerprint(root: Path) -> list:
    rows = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            rows.append(("symlink", relative, os.readlink(path)))
        elif path.is_file():
            rows.append(("file", relative, sha256_bytes(path.read_bytes()), stat.S_IMODE(path.stat().st_mode)))
        elif path.is_dir():
            rows.append(("dir", relative, stat.S_IMODE(path.stat().st_mode)))
    return rows


if __name__ == "__main__":
    unittest.main()
