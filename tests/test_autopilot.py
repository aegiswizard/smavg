import tempfile
import unittest
from pathlib import Path

from smavg.autopilot import (
    apply_safe_action,
    autopilot_status,
    load_latest_autopilot,
    render_autopilot_markdown,
    render_status_markdown,
    run_autopilot_scan,
    verify_autopilot,
)
from smavg.ledger import append_event, create_event


class AutopilotTests(unittest.TestCase):
    def test_autopilot_scan_writes_latest_short_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            for index in range(6):
                (source / f"note-{index}.md").write_text(
                    "\n".join(
                        [
                            f"# Note {index}",
                            "",
                            "## Shared",
                            "Use Smavg as the repetition firewall.",
                            "Exact expansion is required.",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )

            report = run_autopilot_scan(
                root=source,
                out_dir=root / "autopilot",
                run_id="scan",
                budget_tokens=500,
                recursive=False,
                include_surfaces=False,
                include_workflows=False,
            )
            loaded = load_latest_autopilot(root / "autopilot")
            markdown = render_autopilot_markdown(report)
            verify = verify_autopilot(out_dir=root / "autopilot", ledger_path=root / "ledger.jsonl")

            self.assertEqual(report["format"], "smavg-autopilot-report")
            self.assertEqual(loaded["report_json"], report["report_json"])
            self.assertIn("Smavg Report", markdown)
            self.assertEqual(verify["status"], "PASS")

    def test_status_combines_latest_scan_and_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "a.md").write_text("# A\n\n## Shared\nsame\n", encoding="utf-8")
            (source / "b.md").write_text("# B\n\n## Shared\nsame\n", encoding="utf-8")
            ledger = root / "ledger.jsonl"
            append_event(
                create_event(
                    kind="context",
                    label="saved",
                    before={"tokens": 1000, "repeated_tokens": 3000, "disk_bytes": 10000},
                    after={"tokens": 100, "repeated_tokens": 100, "disk_bytes": 1000},
                    quality={"exact_expansion_pass": 1, "exact_expansion_total": 1},
                ),
                ledger,
            )
            run_autopilot_scan(
                root=source,
                out_dir=root / "autopilot",
                run_id="scan",
                budget_tokens=500,
                recursive=False,
                include_surfaces=False,
                include_workflows=False,
            )

            status = autopilot_status(out_dir=root / "autopilot", ledger_path=ledger)
            markdown = render_status_markdown(status)

            self.assertEqual(status["ledger"]["all"]["tokens_saved"], 900)
            self.assertIsInstance(status["latest_scan"], dict)
            self.assertIn("Smavg Status", markdown)

    def test_apply_safe_action_packs_verifies_and_does_not_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "a.md").write_text("# A\n\nsafe pack\n", encoding="utf-8")
            (source / "b.md").write_text("# B\n\nsafe pack\n", encoding="utf-8")

            report = apply_safe_action(
                source=source,
                archive=root / "archive.smavg",
                work_dir=root / "work",
                report_path=root / "report.json",
            )

            self.assertTrue((root / "archive.smavg").exists())
            self.assertTrue((root / "report.json").exists())
            self.assertTrue(source.exists())
            self.assertFalse(report["delete_performed"])
            self.assertFalse(report["source_moved_to_quarantine"])
            self.assertTrue(report["restore_compare"]["pass"])


if __name__ == "__main__":
    unittest.main()
