import tempfile
import unittest
import json
import os
import stat
import zlib
from pathlib import Path
from unittest.mock import patch

from smavg.container import (
    HEADER,
    MAGIC,
    pack_container,
    read_container,
    report_container,
    restore_container,
    extract_container_file,
    verify_container,
)
from smavg.delta import sha256_bytes
from smavg.history_pack import HISTORY_PACK_V2_CODEC, HISTORY_PACK_V3_CODEC, HISTORY_PACK_V4_CODEC


class ContainerTests(unittest.TestCase):
    def test_single_file_container_round_trips_mixed_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            history = source / "reports"
            history.mkdir(parents=True)
            stable = [f"stable line {index:03d}\n" for index in range(160)]
            for version in range(10):
                body = (
                    ["# Report\n", f"revision: {version}\n"]
                    + stable[:80]
                    + [f"value: {version * 5}\n"]
                    + stable[80:]
                )
                (history / f"report_v{version}.md").write_text("".join(body), encoding="utf-8")
            (source / "random.bin").write_bytes(bytes(range(256)))
            (source / "note.txt").write_text("single unrelated note\n", encoding="utf-8")

            archive = root / "project.smavg"
            restore = root / "restore"
            report = pack_container(source, archive)
            ok, failures = verify_container(archive)
            count = restore_container(archive, restore)
            reread = report_container(archive)

            self.assertTrue(ok, failures)
            self.assertEqual(count, 12)
            self.assertEqual(report["file_count"], 12)
            self.assertEqual(reread["file_count"], 12)
            self.assertEqual(len(reread["families"]), 1)
            self.assertIn(
                reread["families"][0]["codec"],
                {HISTORY_PACK_V2_CODEC, HISTORY_PACK_V3_CODEC, HISTORY_PACK_V4_CODEC},
            )
            self.assertEqual(len(reread["fallback_files"]), 2)
            self.assertEqual((restore / "random.bin").read_bytes(), (source / "random.bin").read_bytes())
            self.assertEqual((restore / "reports" / "report_v7.md").read_bytes(), (history / "report_v7.md").read_bytes())

            extracted = root / "one-file.md"
            size = extract_container_file(archive, "reports/report_v7.md", extracted)
            self.assertEqual(size, len((history / "report_v7.md").read_bytes()))
            self.assertEqual(extracted.read_bytes(), (history / "report_v7.md").read_bytes())

    def test_container_handles_empty_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "empty"
            source.mkdir()
            archive = root / "empty.smavg"

            report = pack_container(source, archive)
            ok, failures = verify_container(archive)
            restore = root / "restore"
            count = restore_container(archive, restore)

            self.assertTrue(ok, failures)
            self.assertEqual(report["file_count"], 0)
            self.assertEqual(report["logical_bytes"], 0)
            self.assertEqual(count, 0)

    def test_container_handles_one_binary_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            data = bytes(range(256)) * 4
            (source / "one.bin").write_bytes(data)
            archive = root / "one.smavg"
            restore = root / "restore"

            pack_container(source, archive)
            ok, failures = verify_container(archive)
            count = restore_container(archive, restore)
            report = report_container(archive)

            self.assertTrue(ok, failures)
            self.assertEqual(count, 1)
            self.assertEqual(len(report["families"]), 0)
            self.assertEqual(len(report["fallback_files"]), 1)
            self.assertEqual((restore / "one.bin").read_bytes(), data)

    def test_container_verify_report_restore_do_not_use_path_read_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "one.bin").write_bytes(bytes(range(256)) * 32)
            archive = root / "one.smavg"
            pack_container(source, archive)
            restore = root / "restore"

            with patch.object(Path, "read_bytes", side_effect=AssertionError("full read disallowed")):
                ok, failures = verify_container(archive)
                report = report_container(archive)
                count = restore_container(archive, restore)

            self.assertTrue(ok, failures)
            self.assertEqual(report["file_count"], 1)
            self.assertEqual(count, 1)
            self.assertEqual((restore / "one.bin").read_bytes(), (source / "one.bin").read_bytes())

    def test_container_history_verify_restore_do_not_use_path_read_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            history = source / "history"
            history.mkdir(parents=True)
            stable = [f"stable line {index:03d}\n" for index in range(140)]
            for version in range(12):
                body = (
                    ["# Report\n", f"revision: {version}\n"]
                    + stable[:70]
                    + [f"value: {version * 9}\n"]
                    + stable[70:]
                )
                (history / f"{version:03d}.txt").write_text("".join(body), encoding="utf-8")
            archive = root / "history.smavg"
            pack_container(source, archive)
            restore = root / "restore"

            with patch.object(Path, "read_bytes", side_effect=AssertionError("full read disallowed")):
                ok, failures = verify_container(archive)
                count = restore_container(archive, restore)

            self.assertTrue(ok, failures)
            self.assertEqual(count, 12)
            self.assertEqual((restore / "history" / "009.txt").read_bytes(), (history / "009.txt").read_bytes())

    def test_container_restores_tree_metadata_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            nested = source / "nested"
            empty = source / "empty"
            nested.mkdir(parents=True)
            empty.mkdir()
            executable = nested / "tool.sh"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            target = nested / "target.txt"
            target.write_text("target\n", encoding="utf-8")
            try:
                os.symlink("nested/target.txt", source / "target-link")
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            archive = root / "tree.smavg"
            restore = root / "restore"
            report = pack_container(source, archive)
            ok, failures = verify_container(archive)
            count = restore_container(archive, restore)

            self.assertTrue(ok, failures)
            self.assertEqual(count, 2)
            self.assertEqual(report["tree_entry_count"], 3)
            self.assertEqual(report["file_mode_override_count"], 1)
            self.assertTrue((restore / "empty").is_dir())
            self.assertEqual(stat.S_IMODE((restore / "nested" / "tool.sh").stat().st_mode), 0o755)
            self.assertTrue((restore / "target-link").is_symlink())
            self.assertEqual(os.readlink(restore / "target-link"), "nested/target.txt")
            self.assertEqual((restore / "nested" / "target.txt").read_text(encoding="utf-8"), "target\n")

    def test_container_rejects_bad_magic(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _simple_archive(Path(temp))
            data = bytearray(archive.read_bytes())
            data[:8] = b"NOTSMAVG"
            archive.write_bytes(data)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("magic", failures[0])

    def test_container_rejects_truncated_archive(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _simple_archive(Path(temp))
            archive.write_bytes(archive.read_bytes()[:-1])

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("size", failures[0])

    def test_container_rejects_header_claim_larger_than_file_without_payload_allocation(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "huge-claim.smavg"
            payload_len = 10 * 1024 * 1024 * 1024
            header = HEADER.pack(MAGIC, 0, payload_len, b"\x00" * 32, b"\x00" * 32)
            archive.write_bytes(header)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("size", failures[0])

    def test_container_rejects_corrupted_manifest_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _simple_archive(Path(temp))
            data = bytearray(archive.read_bytes())
            data[HEADER.size] ^= 0x01
            archive.write_bytes(data)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("Manifest SHA-256", failures[0])

    def test_container_rejects_corrupted_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _simple_archive(Path(temp))
            data = bytearray(archive.read_bytes())
            magic, manifest_len, payload_len, _manifest_sha, _payload_sha = HEADER.unpack(data[: HEADER.size])
            self.assertEqual(magic, MAGIC)
            self.assertGreater(payload_len, 0)
            data[HEADER.size + manifest_len] ^= 0x01
            archive.write_bytes(data)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("Payload SHA-256", failures[0])

    def test_container_rejects_missing_manifest_field_cleanly(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _simple_archive(Path(temp))
            container = read_container(archive)
            manifest = dict(container.manifest)
            del manifest["file_count"]
            _rewrite_container(archive, manifest, container.payload)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("missing required manifest field", failures[0])

    def test_container_rejects_unsafe_fallback_path(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _simple_archive(Path(temp))
            container = read_container(archive)
            manifest = dict(container.manifest)
            manifest["fallback_files"] = [dict(item) for item in manifest["fallback_files"]]
            manifest["fallback_files"][0]["path"] = "../evil.txt"
            _rewrite_container(archive, manifest, container.payload)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("Unsafe archive path", failures[0])

    def test_container_rejects_unsafe_tree_path(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _simple_archive(Path(temp))
            container = read_container(archive)
            manifest = dict(container.manifest)
            manifest["tree_entries"] = [dict(item) for item in manifest.get("tree_entries", [])]
            manifest["tree_entries"].append({"path": "../evil.txt", "kind": "dir", "mode": 0o755})
            manifest["tree_entry_count"] = len(manifest["tree_entries"])
            _rewrite_container(archive, manifest, container.payload)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("Unsafe archive path", failures[0])

    def test_container_rejects_unknown_tree_kind(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _simple_archive(Path(temp))
            container = read_container(archive)
            manifest = dict(container.manifest)
            manifest["tree_entries"] = [dict(item) for item in manifest.get("tree_entries", [])]
            manifest["tree_entries"].append({"path": "extra-file.txt", "kind": "file", "mode": 0o644})
            manifest["tree_entry_count"] = len(manifest["tree_entries"])
            _rewrite_container(archive, manifest, container.payload)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("Unknown tree entry kind", failures[0])

    def test_container_rejects_duplicate_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "a.txt").write_text("alpha\n", encoding="utf-8")
            (source / "b.txt").write_text("beta\n", encoding="utf-8")
            archive = root / "dupe.smavg"
            pack_container(source, archive)
            container = read_container(archive)
            manifest = dict(container.manifest)
            manifest["fallback_files"] = [dict(item) for item in manifest["fallback_files"]]
            manifest["fallback_files"][1]["path"] = manifest["fallback_files"][0]["path"]
            _rewrite_container(archive, manifest, container.payload)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("Duplicate restored path", failures[0])

    def test_container_rejects_wrong_restored_sha(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _simple_archive(Path(temp))
            container = read_container(archive)
            manifest = dict(container.manifest)
            manifest["fallback_files"] = [dict(item) for item in manifest["fallback_files"]]
            manifest["fallback_files"][0]["sha256"] = "0" * 64
            _rewrite_container(archive, manifest, container.payload)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("Fallback SHA-256", failures[0])

    def test_container_rejects_payload_record_outside_region(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = _simple_archive(Path(temp))
            container = read_container(archive)
            manifest = dict(container.manifest)
            manifest["fallback_files"] = [dict(item) for item in manifest["fallback_files"]]
            manifest["fallback_files"][0]["offset"] = container.payload_length + 1
            _rewrite_container(archive, manifest, container.payload)

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("outside payload region", failures[0])

    def test_container_rejects_malformed_history_pack(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            history = source / "history"
            history.mkdir(parents=True)
            stable = [f"stable line {index:03d}\n" for index in range(120)]
            for version in range(10):
                (history / f"{version:03d}.md").write_text(
                    "".join(stable[:60] + [f"value {version}\n"] + stable[60:]),
                    encoding="utf-8",
                )
            archive = root / "history.smavg"
            pack_container(source, archive)
            container = read_container(archive)
            manifest = dict(container.manifest)
            manifest["families"] = [dict(item) for item in manifest["families"]]
            payload = bytearray(container.payload)
            family = manifest["families"][0]
            offset = int(family["offset"])
            payload[offset] ^= 0x01
            family["sha256"] = sha256_bytes(bytes(payload[offset : offset + int(family["length"])]))
            _rewrite_container(archive, manifest, bytes(payload))

            ok, failures = verify_container(archive)

            self.assertFalse(ok)
            self.assertIn("History family decode failed", failures[0])


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


if __name__ == "__main__":
    unittest.main()
