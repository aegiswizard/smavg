import tempfile
import unittest
from pathlib import Path

from smavg.ledger import load_events
from smavg.work import (
    WorkError,
    end_work,
    expand_work,
    load_work,
    note_work,
    start_work,
    summarize_work,
)


class WorkModeTests(unittest.TestCase):
    def test_work_mode_runs_gate_receipt_task_and_ledger_once(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            for index in range(6):
                (source / f"report-{index}.md").write_text(
                    "\n".join(
                        [
                            "# Weekly Report",
                            "",
                            "Status: green",
                            "Owner: Aegis Wizard",
                            f"Week: {index}",
                            "Next: keep the Smavg work loop exact.",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
            work_dir = root / "work"
            tasks_dir = root / "tasks"
            ledger = root / "events.jsonl"

            session = start_work(
                source=source,
                task="Test Smavg Work Mode",
                work_dir=work_dir,
                tasks_dir=tasks_dir,
                work_id="work-smoke",
                budget_tokens=500,
            )
            self.assertEqual(session["status"], "active")
            self.assertTrue(Path(session["files"]["gate_json"]).exists())
            self.assertTrue(Path(session["files"]["receipt_json"]).exists())

            expansion = expand_work(
                relative_path="report-3.md",
                work_id="work-smoke",
                work_dir=work_dir,
            )
            self.assertTrue(Path(expansion["expansion"]["output"]).exists())
            self.assertTrue(expansion["expansion"]["verified"])

            note_work(
                role="user",
                text="Please run this through Smavg Work Mode.",
                work_id="work-smoke",
                work_dir=work_dir,
            )
            note_work(
                role="assistant",
                text="I used the gate and one exact expansion.",
                work_id="work-smoke",
                work_dir=work_dir,
            )

            result = end_work(
                work_id="work-smoke",
                work_dir=work_dir,
                ledger_path=ledger,
                report_path=root / "work.md",
            )
            summary = result["work"]["task_summary"]
            events = load_events(ledger)

            self.assertEqual(result["work"]["status"], "ended")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["kind"], "task_session")
            self.assertIn(str(Path(session["files"]["receipt_json"])), events[0]["artifacts"])
            self.assertGreater(summary["smavg_raw_context_tokens"], 0)
            self.assertGreater(summary["smavg_supplied_tokens"], 0)
            self.assertEqual(summary["quality"]["exact_expansion_pass"], 1)
            self.assertEqual(summarize_work(load_work("work-smoke", work_dir))["exact_expansions"], 1)
            self.assertTrue((root / "work.md").exists())

            with self.assertRaises(WorkError):
                end_work(work_id="work-smoke", work_dir=work_dir, ledger_path=ledger)


if __name__ == "__main__":
    unittest.main()
