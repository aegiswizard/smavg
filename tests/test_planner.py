import tempfile
import unittest
from pathlib import Path

from smavg.planner import build_archive_plan


class PlannerTests(unittest.TestCase):
    def test_planner_splits_messy_history_from_unrelated_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()

            stable = [f"stable report line {index:03d}\n" for index in range(320)]
            for version in range(1, 13):
                body = (
                    ["# Quarterly report\n", f"version: {version}\n"]
                    + stable[:160]
                    + [f"metric: {version * 11}\n"]
                    + stable[160:]
                )
                (source / f"report_v{version}.md").write_text("".join(body), encoding="utf-8")

            (source / "logo.bin").write_bytes(bytes(range(256)))
            (source / "readme.txt").write_text("unrelated text\n", encoding="utf-8")

            plan = build_archive_plan(source, root / "store")

            self.assertEqual(len(plan.files), 14)
            self.assertEqual(len(plan.history_packs), 1)
            self.assertEqual(len(plan.history_packs[0].manifest_files), 12)
            self.assertEqual({item.relative for item in plan.fallback_files}, {"logo.bin", "readme.txt"})
            self.assertEqual(plan.report["fallback"]["files"], 2)


if __name__ == "__main__":
    unittest.main()
