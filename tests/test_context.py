import json
import tempfile
import unittest
from pathlib import Path

from smavg.context import (
    ContextError,
    build_context_report,
    build_context_report_from_file_map,
    expand_context_file,
    render_context_markdown,
    write_context_outputs,
)
from smavg.preflight import run_preflight


class ContextTests(unittest.TestCase):
    def test_context_report_detects_repeated_markdown_and_expands_exact_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            for index in range(6):
                (source / f"handoff-{index:02d}.md").write_text(
                    "\n".join(
                        [
                            f"# Session Handoff {index}",
                            "",
                            "## What Was Completed",
                            f"- Completed item {index}",
                            "",
                            "## Next Steps",
                            f"- Continue with item {index + 1}",
                            "",
                            "## Verification",
                            f"- sha256 proof {index:064x}",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
            (source / "random.bin").write_bytes(bytes(range(256)))

            report = build_context_report(source)
            markdown = render_context_markdown(report)
            context_md = root / "context.md"
            context_json = root / "context.json"
            restored = root / "restored.md"
            write_context_outputs(report, context_md, context_json)
            size = expand_context_file(context_json, "handoff-03.md", restored)

            self.assertEqual(report["format"], "smavg-context")
            self.assertEqual(report["file_count"], 7)
            self.assertEqual(report["text_file_count"], 6)
            self.assertGreaterEqual(report["families_detected"], 1)
            self.assertIn("Exact Retrieval", markdown)
            self.assertTrue(context_md.exists())
            self.assertTrue(context_json.exists())
            self.assertEqual(size, len((source / "handoff-03.md").read_bytes()))
            self.assertEqual(restored.read_bytes(), (source / "handoff-03.md").read_bytes())

    def test_expand_context_rejects_changed_source_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            file_path = source / "note.md"
            file_path.write_text("# Note\n\noriginal\n", encoding="utf-8")
            report = build_context_report(source)
            context_json = root / "context.json"
            write_context_outputs(report, None, context_json)

            file_path.write_text("# Note\n\nchanged\n", encoding="utf-8")

            with self.assertRaisesRegex(ContextError, "changed"):
                expand_context_file(context_json, "note.md", root / "restored.md")

    def test_context_json_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "a.md").write_text("# A\n\n## Same\nalpha\n", encoding="utf-8")
            (source / "b.md").write_text("# B\n\n## Same\nbeta\n", encoding="utf-8")
            context_json = root / "context.json"
            report = build_context_report(source)
            write_context_outputs(report, None, context_json)

            loaded = json.loads(context_json.read_text(encoding="utf-8"))

            self.assertEqual(loaded["integrity"]["hash_algorithm"], "sha256")
            self.assertTrue(loaded["integrity"]["exact_retrieval_available"])
            self.assertFalse(loaded["integrity"]["ai_generated_interpretations"])
            self.assertEqual(len(loaded["files"]), 2)

    def test_context_reports_weak_when_no_strong_repetition_is_found(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            for index in range(4):
                (source / f"unique-{index}.txt").write_text(
                    "\n".join(
                        [
                            f"Completely distinct topic {index}",
                            f"Only present in file {index}",
                            f"Identifier {index:04d}-{index * 17:04d}",
                        ]
                    ),
                    encoding="utf-8",
                )

            report = build_context_report(source)
            markdown = render_context_markdown(report)

            self.assertEqual(report["families_detected"], 0)
            self.assertEqual(report["assessment"]["status"], "weak")
            self.assertIn("No strong repetition found", report["assessment"]["finding"])
            self.assertIn("No repeated families were detected.", markdown)

    def test_context_recommends_high_signal_files_and_records_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            (source / "short-term").mkdir(parents=True)
            (source / "medium-term").mkdir()
            (source / "short-term" / "current_focus.md").write_text(
                "# Current Focus\n\n## Now\nSmavg reliability pass.\n",
                encoding="utf-8",
            )
            (source / "medium-term" / "smavg_runbook.md").write_text(
                "# Smavg Runbook\n\n## Storage\nVerified.\n\n## Context\nVerified.\n",
                encoding="utf-8",
            )
            (source / "misc.txt").write_text("small note\n", encoding="utf-8")

            report = build_context_report(source, budget_tokens=1000)
            recommended_paths = [item["path"] for item in report["recommended_expansions"]]
            role_hints = {
                item["path"]: item["role_hints"]
                for item in report["recommended_expansions"]
            }

            self.assertEqual(report["brief_budget_tokens"], 1000)
            self.assertIn("short-term/current_focus.md", recommended_paths[:2])
            self.assertIn("medium-term/smavg_runbook.md", recommended_paths[:2])
            self.assertIn("current focus", role_hints["short-term/current_focus.md"])
            self.assertIn("Smavg runbook", role_hints["medium-term/smavg_runbook.md"])

    def test_context_renders_compact_index_for_skills_and_source_modules(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            (source / "src" / "smavg").mkdir(parents=True)
            (source / "plugin" / "skills" / "browser").mkdir(parents=True)
            for index in range(12):
                (source / f"note-{index}.md").write_text(
                    f"# Note {index}\n\n## Shared\nStable repeated note.\n",
                    encoding="utf-8",
                )
            (source / "src" / "smavg" / "mcp_server.py").write_text(
                "def serve():\n    return 'mcp'\n",
                encoding="utf-8",
            )
            (source / "src" / "smavg" / "preflight.py").write_text(
                "def run_preflight():\n    return 'preflight'\n",
                encoding="utf-8",
            )
            (source / "plugin" / "skills" / "browser" / "SKILL.md").write_text(
                "# Browser Skill\n\nUse browser automation safely.\n",
                encoding="utf-8",
            )

            report = build_context_report(source, budget_tokens=3000)
            markdown = render_context_markdown(report)
            indexed_paths = [item["path"] for item in report["compact_file_index"]]

            self.assertIn("Compact Exact File Index", markdown)
            self.assertIn("src/smavg/mcp_server.py", indexed_paths)
            self.assertIn("src/smavg/preflight.py", indexed_paths)
            self.assertIn("plugin/skills/browser/SKILL.md", indexed_paths)
            self.assertIn("src/smavg/mcp_server.py", markdown)
            self.assertIn("plugin/skills/browser/SKILL.md", markdown)

    def test_context_file_map_expands_from_original_source_path(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source_a = root / "source-a"
            source_b = root / "source-b"
            source_a.mkdir()
            source_b.mkdir()
            skill = source_a / "SKILL.md"
            runbook = source_b / "workflow.md"
            skill.write_text("# Skill\n\n## Scope\nUse browser tools.\n", encoding="utf-8")
            runbook.write_text("# Workflow\n\n## Scope\nUse browser tools safely.\n", encoding="utf-8")
            context_json = root / "context.json"
            restored = root / "restored.md"

            report = build_context_report_from_file_map(
                {
                    "skills/example/SKILL.md": skill,
                    "memories/workflow.md": runbook,
                },
                source_label="workflow:test",
                source_kind="workflow",
            )
            write_context_outputs(report, None, context_json)
            size = expand_context_file(context_json, "skills/example/SKILL.md", restored)

            self.assertEqual(report["source_kind"], "workflow")
            self.assertEqual(size, len(skill.read_bytes()))
            self.assertEqual(restored.read_bytes(), skill.read_bytes())
            loaded = json.loads(context_json.read_text(encoding="utf-8"))
            record = next(item for item in loaded["files"] if item["path"] == "skills/example/SKILL.md")
            self.assertEqual(record["source_path"], str(skill.resolve()))

    def test_context_file_map_rejects_changed_original_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            note = source / "note.md"
            note.write_text("# Note\n\noriginal\n", encoding="utf-8")
            context_json = root / "context.json"
            report = build_context_report_from_file_map(
                {"notes/note.md": note},
                source_label="workflow:test",
                source_kind="workflow",
            )
            write_context_outputs(report, None, context_json)

            note.write_text("# Note\n\nchanged\n", encoding="utf-8")

            with self.assertRaisesRegex(ContextError, "changed"):
                expand_context_file(context_json, "notes/note.md", root / "restored.md")

    def test_preflight_writes_summary_and_context_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            for index in range(4):
                (source / f"note-{index}.md").write_text(
                    "\n".join(
                        [
                            f"# Note {index}",
                            "",
                            "## Shared Workflow",
                            "Run the same safe preflight before work.",
                            f"Variable: {index}",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )

            summary = run_preflight(
                source=source,
                out_dir=root / "preflights",
                budget_tokens=800,
                run_id="test-run",
            )

            self.assertEqual(summary["format"], "smavg-preflight")
            self.assertEqual(summary["target_kind"], "directory")
            self.assertTrue(Path(summary["context_markdown"]).exists())
            self.assertTrue(Path(summary["context_json"]).exists())
            self.assertTrue(Path(summary["preflight_markdown"]).exists())
            self.assertTrue(Path(summary["preflight_json"]).exists())
            self.assertGreater(summary["raw_tokens_estimate"], 0)
            self.assertEqual(Path(summary["run_dir"]).name, "test-run")


if __name__ == "__main__":
    unittest.main()
