import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from smavg.ledger import (
    add_task_report,
    add_task_text,
    append_event,
    create_event,
    end_task,
    event_from_report,
    import_reports,
    ledger_report,
    load_events,
    start_task,
    summarize_task,
)


class LedgerTaskTests(unittest.TestCase):
    def test_ledger_adds_manual_event_and_reports_x_ratios(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger = root / "events.jsonl"
            event = create_event(
                kind="context",
                label="test context",
                before={"tokens": 1000, "disk_bytes": 5000},
                after={"tokens": 100, "disk_bytes": 1000},
                verification={"status": "verified"},
            )
            append_event(event, ledger)

            report = ledger_report(ledger_path=ledger)

            self.assertEqual(len(load_events(ledger)), 1)
            self.assertEqual(report["ai_tokens"]["before"], 1000)
            self.assertEqual(report["ai_tokens"]["after"], 100)
            self.assertEqual(report["ai_tokens"]["saved"], 900)
            self.assertEqual(report["ai_tokens"]["ratio"], 10.0)
            self.assertEqual(report["storage_disk"]["ratio"], 5.0)
            self.assertEqual(report["headline"]["tokens_saved_all_time"], 900)
            self.assertEqual(report["headline"]["disk_bytes_saved_all_time"], 4000)
            self.assertIn("categories", report)
            self.assertTrue(any(item["id"] == "ai_context" for item in report["categories"]))
            self.assertEqual(report["trust"]["failures_counted_as_wins"], 0)

    def test_ledger_headline_splits_today_from_all_time(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger = root / "events.jsonl"
            append_event(
                create_event(
                    kind="context",
                    label="old",
                    before={"tokens": 1000},
                    after={"tokens": 500},
                    created_at="2026-05-01T12:00:00+00:00",
                ),
                ledger,
            )
            append_event(
                create_event(
                    kind="context",
                    label="today",
                    before={"tokens": 2000, "repeated_tokens": 6000},
                    after={"tokens": 100, "repeated_tokens": 100},
                    created_at="2026-05-17T12:00:00+00:00",
                ),
                ledger,
            )

            report = ledger_report(
                ledger_path=ledger,
                now=datetime(2026, 5, 17, tzinfo=timezone.utc),
            )

            self.assertEqual(report["headline"]["tokens_saved_today"], 1900)
            self.assertEqual(report["headline"]["tokens_saved_all_time"], 2400)
            self.assertEqual(report["headline"]["repeated_tokens_saved_today"], 5900)

    def test_ledger_imports_gate_gauntlet_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report_json = root / "gate-results.json"
            report_json.write_text(
                json.dumps(
                    {
                        "format": "smavg-gate-gauntlet",
                        "summary": {
                            "probes": 2,
                            "fail": 0,
                            "gate_integrity_pass": 2,
                            "receipt_integrity_pass": 2,
                            "exact_expansion_pass": 2,
                            "model_routing_pass": 2,
                            "evidence_tasks": 3,
                            "evidence_task_pass": 3,
                            "same_evidence": 3,
                            "raw_tokens_estimate": 10000,
                            "gate_receipt_tokens_estimate": 500,
                            "receipt_reduction_ratio": 20.0,
                            "repeated_raw_tokens_estimate": 30000,
                            "repeated_gate_tokens_estimate": 500,
                            "repeated_reduction_ratio": 60.0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            event = event_from_report(report_json)

            self.assertEqual(event["kind"], "gate_gauntlet")
            self.assertEqual(event["verification"]["status"], "verified")
            self.assertEqual(event["before"]["tokens"], 10000)
            self.assertEqual(event["after"]["tokens"], 500)
            self.assertEqual(event["ratios"]["tokens"], 20.0)
            self.assertEqual(event["quality"]["evidence_task_pass"], 3)

    def test_ledger_imports_surface_gauntlet_report_as_mcp_skill_plugin_event(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report_json = root / "surface-results.json"
            report_json.write_text(
                json.dumps(
                    {
                        "format": "smavg-surface-gauntlet",
                        "generated_at": "2026-05-18T10:00:00+00:00",
                        "registry_json": str(root / "surfaces.json"),
                        "summary": {
                            "context_groups": 4,
                            "useful_groups": 3,
                            "weak_groups": 1,
                            "failed_groups": 0,
                            "exact_expansion_pass": 8,
                            "exact_expansion_total": 8,
                            "configured_unverified_surfaces": 2,
                            "raw_tokens_estimate": 10000,
                            "smavg_supplied_tokens_estimate": 1000,
                            "first_time_reduction_ratio": 10.0,
                            "repeated_raw_tokens_estimate": 30000,
                            "repeated_smavg_tokens_estimate": 1000,
                            "repeated_reduction_ratio": 30.0,
                        },
                    }
                ),
                encoding="utf-8",
            )

            event = event_from_report(report_json)
            ledger = root / "events.jsonl"
            append_event(event, ledger)
            report = ledger_report(ledger_path=ledger)
            cards = {item["id"]: item for item in report["categories"]}

            self.assertEqual(event["kind"], "surface_gauntlet")
            self.assertEqual(event["verification"]["status"], "verified")
            self.assertEqual(event["quality"]["exact_expansion_pass"], 8)
            self.assertEqual(report["repeated_work_tokens"]["ratio"], 30.0)
            self.assertEqual(cards["mcp_skill_plugin"]["event_count"], 1)
            self.assertEqual(cards["mcp_skill_plugin"]["reductions"]["tokens"]["ratio"], 10.0)

    def test_ledger_keeps_category_cards_separate_from_lifetime_rollup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger = root / "events.jsonl"
            append_event(
                create_event(
                    kind="storage_gauntlet",
                    label="storage proof",
                    before={"disk_bytes": 10000},
                    after={"disk_bytes": 100},
                    verification={"status": "verified"},
                    quality={"verify_pass": 1, "verify_total": 1, "restore_pass": 1, "restore_total": 1},
                ),
                ledger,
            )
            append_event(
                create_event(
                    kind="gate_gauntlet",
                    label="gate proof",
                    before={"tokens": 5000, "repeated_tokens": 15000},
                    after={"tokens": 250, "repeated_tokens": 250},
                    verification={"status": "verified"},
                    quality={"evidence_task_pass": 2, "evidence_task_total": 2},
                ),
                ledger,
            )

            report = ledger_report(ledger_path=ledger)
            cards = {item["id"]: item for item in report["categories"]}

            self.assertEqual(report["ai_tokens"]["ratio"], 20.0)
            self.assertEqual(report["storage_disk"]["ratio"], 100.0)
            self.assertEqual(cards["storage"]["reductions"]["disk_bytes"]["ratio"], 100.0)
            self.assertNotIn("tokens", cards["storage"]["reductions"])
            self.assertEqual(cards["agent_workflow"]["reductions"]["tokens"]["ratio"], 20.0)
            self.assertEqual(cards["agent_workflow"]["reductions"]["repeated_tokens"]["ratio"], 60.0)

    def test_import_reports_prefers_top_level_and_skips_duplicates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ledger = root / "events.jsonl"
            run = root / "run"
            child = run / "child"
            child.mkdir(parents=True)
            (run / "results.json").write_text(
                json.dumps(
                    {
                        "format": "smavg-gate-gauntlet",
                        "generated_at": "2026-05-17T10:00:00+00:00",
                        "summary": {
                            "probes": 1,
                            "fail": 0,
                            "exact_expansion_pass": 1,
                            "evidence_tasks": 1,
                            "evidence_task_pass": 1,
                            "raw_tokens_estimate": 1000,
                            "gate_receipt_tokens_estimate": 100,
                            "repeated_raw_tokens_estimate": 3000,
                            "repeated_gate_tokens_estimate": 100,
                        },
                    }
                ),
                encoding="utf-8",
            )
            (child / "context.json").write_text(
                json.dumps(
                    {
                        "format": "smavg-context",
                        "generated_at": "2026-05-17T10:00:00+00:00",
                        "original_tokens_estimate": 999999,
                        "brief_tokens_estimate": 1,
                    }
                ),
                encoding="utf-8",
            )

            first = import_reports(root, ledger_path=ledger)
            second = import_reports(root, ledger_path=ledger)
            report = ledger_report(ledger_path=ledger)

            self.assertEqual(first["selected_reports"], 1)
            self.assertEqual(first["suppressed_component_reports"], 1)
            self.assertEqual(first["imported"], 1)
            self.assertEqual(second["imported"], 0)
            self.assertEqual(second["skipped_duplicate"], 1)
            self.assertEqual(report["ai_tokens"]["before"], 1000)
            self.assertEqual(len(load_events(ledger)), 1)

    def test_task_session_counts_visible_messages_and_smavg_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            tasks_dir = root / "tasks"
            ledger = root / "events.jsonl"
            report_json = root / "receipt.json"
            report_json.write_text(
                json.dumps(
                    {
                        "format": "smavg-run-receipt",
                        "target_label": "receipt-test",
                        "context_json": str(root / "context.json"),
                        "raw_material": {
                            "raw_tokens_estimate": 5000,
                            "logical_bytes": 12000,
                        },
                        "supplied_to_agent": {
                            "total_tokens_estimate": 250,
                            "reduction_ratio": 20.0,
                            "exact_expansions": [
                                {"path": "README.md", "verified": True},
                            ],
                        },
                        "verification": {
                            "exact_expansions_verified": True,
                        },
                    }
                ),
                encoding="utf-8",
            )

            task = start_task(label="session test", tasks_dir=tasks_dir)
            task = add_task_text(task_id=task["id"], role="user", text="Please run Smavg.", tasks_dir=tasks_dir)
            task = add_task_text(task_id=task["id"], role="assistant", text="Running Smavg now.", tasks_dir=tasks_dir)
            task = add_task_report(task_id=task["id"], report_path=report_json, tasks_dir=tasks_dir)
            summary = summarize_task(task)
            ended = end_task(task_id=task["id"], tasks_dir=tasks_dir, ledger_path=ledger)

            self.assertGreater(summary["visible_user_input_tokens"], 0)
            self.assertGreater(summary["visible_assistant_output_tokens"], 0)
            self.assertEqual(summary["smavg_raw_context_tokens"], 5000)
            self.assertEqual(summary["smavg_supplied_tokens"], 250)
            self.assertEqual(summary["smavg_reduction_ratio"], 20.0)
            self.assertEqual(ended["summary"]["smavg_saved_tokens"], 4750)
            self.assertEqual(len(load_events(ledger)), 1)


if __name__ == "__main__":
    unittest.main()
