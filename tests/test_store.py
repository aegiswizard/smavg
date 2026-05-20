import tempfile
import unittest
import json
from pathlib import Path

from smavg.json_template import canonical_json_bytes
from smavg.store import SmavgStore


class StoreTests(unittest.TestCase):
    def test_import_verify_and_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            stable_lines = [
                (
                    f"Control {number:03d}: evidence text for the weekly report "
                    f"keeps this unique sentence stable across versions."
                )
                for number in range(220)
            ]
            for index in range(6):
                lines = ["# Daily Log", "The system remained stable."]
                lines.extend(stable_lines[:110])
                lines.append(f"Changed value: {index}")
                lines.extend(stable_lines[110:])
                lines.append("The closing line is unchanged.")
                body = "\n".join(lines)
                (source / f"log-{index}.md").write_text(body, encoding="utf-8")

            store = SmavgStore(root / "store")
            results = store.import_dir(source)
            ok, failures = store.verify_dir(source)
            restored = store.get_file("log-3.md")

            self.assertEqual(len(results), 6)
            self.assertTrue(ok, failures)
            self.assertEqual(restored, (source / "log-3.md").read_bytes())
            self.assertGreaterEqual(store.stats()["object_modes"].get("delta", 0), 1)

    def test_duplicate_content_reuses_existing_object(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = SmavgStore(root / "store")
            first = store.put_bytes("a.txt", b"same bytes\n")
            second = store.put_bytes("b.txt", b"same bytes\n")

            stats = store.stats()

            self.assertEqual(first.object_id, second.object_id)
            self.assertEqual(stats["file_count"], 2)
            self.assertEqual(stats["object_count"], 1)

    def test_canonical_json_uses_shared_template(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            for index in range(5):
                record = {
                    "cveID": f"CVE-2026-{index:04d}",
                    "dateAdded": "2026-05-09",
                    "knownRansomwareCampaignUse": "Unknown",
                    "requiredAction": "Apply mitigations per vendor instructions.",
                    "shortDescription": f"Record {index} has real changing fields.",
                    "vendorProject": "Example",
                }
                (source / f"record-{index}.json").write_bytes(canonical_json_bytes(record))

            store = SmavgStore(root / "store")
            store.import_dir(source)
            ok, failures = store.verify_dir(source)
            stats = store.stats()

            self.assertTrue(ok, failures)
            self.assertEqual(stats["template_count"], 1)
            self.assertEqual(stats["object_modes"].get("json_template"), 5)

    def test_archive_snapshot_restore_and_verify(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "alpha.txt").write_text("alpha\n", encoding="utf-8")
            (source / "nested").mkdir()
            (source / "nested" / "beta.txt").write_text("beta\n", encoding="utf-8")

            store = SmavgStore(root / "store")
            result = store.archive_dir(source, snapshot_id="snap-one")
            ok, failures = store.verify_snapshot_against_dir("snap-one", source)
            integrity_ok, integrity_failures = store.verify_snapshot_integrity("snap-one")
            restore_dir = root / "restore"
            restored_count = store.restore_snapshot("latest", restore_dir)
            manifest = json.loads((root / "store" / "snapshots" / "snap-one.json").read_text())
            config = json.loads((root / "store" / "config.json").read_text())

            self.assertEqual(result.snapshot_id, "snap-one")
            self.assertEqual(result.file_count, 2)
            self.assertTrue(ok, failures)
            self.assertTrue(integrity_ok, integrity_failures)
            self.assertEqual(restored_count, 2)
            self.assertEqual((restore_dir / "alpha.txt").read_bytes(), b"alpha\n")
            self.assertEqual((restore_dir / "nested" / "beta.txt").read_bytes(), b"beta\n")
            self.assertEqual(store.stats()["snapshot_count"], 1)
            self.assertEqual(config["format"], "smavg-archive")
            self.assertEqual(manifest["format"], "smavg-snapshot")
            self.assertEqual(manifest["file_count"], 2)
            self.assertEqual(manifest["files"][0]["path"], "alpha.txt")

    def test_archive_snapshot_freezes_previous_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            target = source / "note.txt"
            target.write_text("first\n", encoding="utf-8")

            store = SmavgStore(root / "store")
            store.archive_dir(source, snapshot_id="snap-first")
            target.write_text("second\n", encoding="utf-8")
            store.archive_dir(source, snapshot_id="snap-second")

            first_restore = root / "first"
            second_restore = root / "second"
            store.restore_snapshot("snap-first", first_restore)
            store.restore_snapshot("snap-second", second_restore)

            self.assertEqual((first_restore / "note.txt").read_text(encoding="utf-8"), "first\n")
            self.assertEqual((second_restore / "note.txt").read_text(encoding="utf-8"), "second\n")
            self.assertEqual(len(store.list_snapshots()), 2)

    def test_archive_uses_compact_history_pack_for_versioned_group(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            group = source / "reports"
            group.mkdir(parents=True)
            stable = [f"stable evidence line {index:03d}\n" for index in range(180)]
            for version in range(14):
                data = (
                    ["# Incident report\n", f"revision: {version}\n"]
                    + stable[:90]
                    + [f"changed value: {version * 3}\n"]
                    + stable[90:]
                )
                (group / f"{version:03d}.txt").write_text("".join(data), encoding="utf-8")

            store = SmavgStore(root / "store")
            result = store.archive_dir(source, snapshot_id="history-one")
            ok, failures = store.verify_snapshot_against_dir("history-one", source)
            integrity_ok, integrity_failures = store.verify_snapshot_integrity("history-one")
            restore_dir = root / "restore"
            restored_count = store.restore_snapshot("history-one", restore_dir)
            manifest = json.loads((root / "store" / "snapshots" / "history-one.json").read_text())
            stats = store.stats()

            self.assertEqual(result.file_count, 14)
            self.assertEqual(result.modes, {"history_pack": 14})
            self.assertTrue(ok, failures)
            self.assertTrue(integrity_ok, integrity_failures)
            self.assertEqual(restored_count, 14)
            self.assertEqual((restore_dir / "reports" / "007.txt").read_bytes(), (group / "007.txt").read_bytes())
            self.assertEqual(manifest["packs"][0]["kind"], "history_pack")
            self.assertEqual(manifest["files"], [])
            self.assertEqual(stats["snapshot_pack_file_modes"].get("history_pack"), 14)

    def test_archive_mixed_plan_restores_history_pack_and_fallback_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            history = source / "weekly"
            history.mkdir(parents=True)
            stable = [f"unchanged operational line {index:03d}\n" for index in range(140)]
            for version in range(10):
                data = (
                    ["# Weekly status\n", f"revision: {version}\n"]
                    + stable[:70]
                    + [f"counter: {version * 19}\n"]
                    + stable[70:]
                )
                (history / f"{version:03d}.md").write_text("".join(data), encoding="utf-8")
            (source / "logo.bin").write_bytes(bytes(range(256)))
            (source / "single-note.txt").write_text("one unrelated note\n", encoding="utf-8")

            store = SmavgStore(root / "store")
            result = store.archive_dir(source, snapshot_id="mixed-one")
            ok, failures = store.verify_snapshot_against_dir("mixed-one", source)
            restore_dir = root / "restore"
            restored_count = store.restore_snapshot("mixed-one", restore_dir)
            manifest = json.loads((root / "store" / "snapshots" / "mixed-one.json").read_text())
            report = store.snapshot_report("mixed-one")
            stats = store.stats()

            self.assertEqual(result.file_count, 12)
            self.assertEqual(result.modes.get("history_pack"), 10)
            self.assertEqual(len(manifest["packs"]), 1)
            self.assertEqual(len(manifest["files"]), 2)
            self.assertEqual(manifest["planner"]["fallback"]["files"], 2)
            self.assertTrue(ok, failures)
            self.assertEqual(restored_count, 12)
            self.assertEqual((restore_dir / "logo.bin").read_bytes(), (source / "logo.bin").read_bytes())
            self.assertEqual((restore_dir / "weekly" / "007.md").read_bytes(), (history / "007.md").read_bytes())
            self.assertEqual(report["snapshot"]["file_count"], 12)
            self.assertEqual(stats["file_count"], 12)


if __name__ == "__main__":
    unittest.main()
