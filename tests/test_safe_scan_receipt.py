import json
import tempfile
import unittest
from pathlib import Path

from smavg.context import build_context_report, expand_context_file, write_context_outputs
from smavg.receipt import append_expansion_to_receipt, create_receipt_from_context
from smavg.safe_ops import safe_pack
from smavg.scan import run_scan


class SafeScanReceiptTests(unittest.TestCase):
    def test_safe_pack_verifies_restore_compare_and_can_quarantine_without_delete(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            history = source / "reports"
            history.mkdir(parents=True)
            for index in range(8):
                (history / f"report-{index:02d}.md").write_text(
                    "\n".join(
                        [
                            "# Report",
                            "## Shared",
                            "This line stays stable across reports.",
                            f"Value: {index}",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
            (source / "one.bin").write_bytes(bytes(range(64)))

            report = safe_pack(
                source=source,
                archive=root / "source.smavg",
                work_dir=root / "work",
                quarantine_dir=root / "quarantine",
                move_to_quarantine=True,
            )

            self.assertTrue(report["archive_verify"]["pass"])
            self.assertTrue(report["restore_compare"]["pass"])
            self.assertTrue(report["source_moved_to_quarantine"])
            self.assertFalse(report["delete_performed"])
            cleanup = report["cleanup_projection"]
            self.assertEqual(cleanup["quarantine"]["status"], "moved")
            self.assertEqual(cleanup["quarantine"]["disk_bytes_freed_now"], 0)
            self.assertGreater(
                cleanup["purge_projection"]["additional_disk_bytes_freed_if_quarantine_purged_from_current_state"],
                0,
            )
            self.assertIn("net_disk_bytes_saved_after_purge_and_archive_kept", cleanup["purge_projection"])
            self.assertGreater(cleanup["token_projection"]["raw_source_tokens_estimate"], 0)
            self.assertIn("tokens_saved_when_agent_uses_smavg_brief_instead_of_raw_source", cleanup["token_projection"])
            self.assertIn(report["importance_brief"]["rating"], {"high", "medium", "low", "unknown"})
            self.assertIn("truth", report["importance_brief"])
            quarantined = Path(str(report["quarantined_path"]))
            self.assertTrue(quarantined.exists())
            self.assertFalse(source.exists())
            self.assertEqual((quarantined / "reports" / "report-03.md").read_text(encoding="utf-8").splitlines()[3], "Value: 3")

    def test_receipt_records_brief_and_exact_expansion_without_claiming_full_raw_send(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            for index in range(4):
                (source / f"note-{index}.md").write_text(
                    f"# Note {index}\n\n## Shared\nStable body.\nValue {index}\n",
                    encoding="utf-8",
                )
            context_json = root / "context.json"
            context_md = root / "context.md"
            report = build_context_report(source)
            write_context_outputs(report, context_md, context_json)
            receipt_json = root / "receipt.json"
            receipt = create_receipt_from_context(
                context_json=context_json,
                context_markdown=context_md,
                receipt_json=receipt_json,
            )

            expanded = root / "expanded.md"
            expand_context_file(context_json, "note-2.md", expanded)
            updated = append_expansion_to_receipt(
                receipt_json=receipt_json,
                context_json=context_json,
                relative_path="note-2.md",
                expanded_output=expanded,
            )

            self.assertGreater(receipt["raw_material"]["raw_tokens_estimate"], 0)
            self.assertFalse(updated["supplied_to_agent"]["full_raw_source_supplied_by_smavg"])
            self.assertEqual(len(updated["supplied_to_agent"]["exact_expansions"]), 1)
            self.assertTrue(updated["supplied_to_agent"]["exact_expansions"][0]["verified"])
            self.assertGreater(updated["supplied_to_agent"]["total_tokens_estimate"], receipt["supplied_to_agent"]["brief_tokens_estimate"])
            self.assertTrue(receipt_json.with_suffix(".md").exists())

    def test_scan_is_read_only_and_writes_candidate_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            scan_root = root / "scan-root"
            repeated = scan_root / "repeated"
            repeated.mkdir(parents=True)
            for index in range(5):
                (repeated / f"handoff-{index}.md").write_text(
                    "\n".join(
                        [
                            f"# Handoff {index}",
                            "",
                            "## Shared",
                            "Use this same repeated structure.",
                            f"Variable {index}",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )

            summary = run_scan(
                root=scan_root,
                out_dir=root / "scans",
                run_id="scan-test",
                recursive=True,
                max_depth=1,
                include_workflows=False,
            )

            self.assertEqual(summary["format"], "smavg-scan-report")
            self.assertFalse(summary["cleanup_performed"])
            self.assertGreaterEqual(summary["directories_analyzed"], 1)
            self.assertTrue(Path(summary["scan_json"]).exists())
            self.assertTrue(Path(summary["scan_markdown"]).exists())
            self.assertTrue(repeated.exists())
            candidate_paths = [item["path"] for item in summary["directories"]]
            self.assertIn(str(repeated.resolve()), candidate_paths)


if __name__ == "__main__":
    unittest.main()
