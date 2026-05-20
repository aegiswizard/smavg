import os
import tempfile
import unittest
from pathlib import Path

from smavg.gauntlet import GauntletError, run_gauntlet, scan_corpus


class GauntletTests(unittest.TestCase):
    def test_gauntlet_counts_clean_regular_file_tree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            nested = source / "nested"
            nested.mkdir(parents=True)
            (source / "a.txt").write_text("alpha\n", encoding="utf-8")
            (nested / "b.txt").write_text("beta\n", encoding="utf-8")

            report = run_gauntlet([source], root / "out", baselines="none")
            result = report["results"][0]

            self.assertTrue(result["result_counted"], result)
            self.assertTrue(result["full_fidelity_counted"], result)
            self.assertEqual(result["verify"], "PASS")
            self.assertEqual(result["regular_file_diff"], "PASS")
            self.assertEqual(result["files_archived"], 2)
            self.assertTrue((root / "out" / "report.md").exists())
            self.assertTrue((root / "out" / "results.json").exists())

    def test_gauntlet_counts_empty_directory_after_tree_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            (source / "empty").mkdir(parents=True)
            (source / "a.txt").write_text("alpha\n", encoding="utf-8")

            report = run_gauntlet([source], root / "out", baselines="none")
            result = report["results"][0]

            self.assertTrue(result["result_counted"], result)
            self.assertTrue(result["full_fidelity_counted"], result)
            self.assertEqual(result["unsupported_count"], 0)
            self.assertEqual(result["pack_status"], "PASS")
            self.assertEqual(result["regular_file_diff"], "PASS")
            self.assertEqual(result["tree_fidelity"], "PASS")

    def test_gauntlet_counts_symlink_without_following_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            target = root / "target.txt"
            target.write_text("secret target should not be followed\n", encoding="utf-8")
            try:
                os.symlink(target, source / "linked.txt")
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            report = run_gauntlet([source], root / "out", baselines="none")
            result = report["results"][0]

            self.assertTrue(result["result_counted"], result)
            self.assertTrue(result["full_fidelity_counted"], result)
            self.assertEqual(result["pack_status"], "PASS")
            self.assertEqual(result["blocking_unsupported_count"], 0)
            self.assertEqual(result["symlinks_discovered"], 1)
            self.assertEqual(result["tree_fidelity"], "PASS")

    def test_scan_refuses_sensitive_named_root_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "wallet-data"
            source.mkdir()
            (source / "note.txt").write_text("not packed\n", encoding="utf-8")

            with self.assertRaises(GauntletError):
                scan_corpus(source)


if __name__ == "__main__":
    unittest.main()
