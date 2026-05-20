import json
import tempfile
import unittest
from pathlib import Path

from smavg.context import expand_context_file
from smavg.gate import run_gate
from smavg.receipt import append_expansion_to_receipt


class GateTests(unittest.TestCase):
    def test_gate_writes_packet_and_receipt_aware_expansion_commands(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            for index in range(5):
                (source / f"handoff-{index}.md").write_text(
                    "\n".join(
                        [
                            f"# Handoff {index}",
                            "",
                            "## Shared",
                            "Use the same repeated agent setup.",
                            f"Variable {index}",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )

            gate = run_gate(
                source=source,
                out_dir=root / "gates",
                run_id="gate-test",
                task="Answer using the Smavg packet only.",
                budget_tokens=1000,
            )

            files = gate["files"]
            self.assertEqual(gate["format"], "smavg-gate")
            self.assertEqual(gate["task"], "Answer using the Smavg packet only.")
            self.assertTrue(Path(files["gate_markdown"]).exists())
            self.assertTrue(Path(files["gate_json"]).exists())
            self.assertTrue(Path(files["context_markdown"]).exists())
            self.assertTrue(Path(files["context_json"]).exists())
            self.assertTrue(Path(files["receipt_json"]).exists())
            self.assertGreater(gate["measurement"]["raw_tokens_estimate"], 0)
            self.assertFalse(gate["measurement"]["full_raw_source_supplied_by_smavg"])
            self.assertIn("--receipt", gate["recommended_expansions"][0]["expand_command"])

            expanded = root / "expanded.md"
            relative = gate["recommended_expansions"][0]["path"]
            expand_context_file(Path(files["context_json"]), relative, expanded)
            receipt = append_expansion_to_receipt(
                receipt_json=Path(files["receipt_json"]),
                context_json=Path(files["context_json"]),
                relative_path=relative,
                expanded_output=expanded,
            )

            self.assertEqual(len(receipt["supplied_to_agent"]["exact_expansions"]), 1)
            self.assertFalse(receipt["supplied_to_agent"]["full_raw_source_supplied_by_smavg"])

    def test_gate_json_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "a.md").write_text("# A\n\n## Shared\nOne\n", encoding="utf-8")
            (source / "b.md").write_text("# B\n\n## Shared\nTwo\n", encoding="utf-8")

            gate = run_gate(
                source=source,
                out_dir=root / "gates",
                run_id="json-test",
                task="Inspect this folder.",
            )
            loaded = json.loads(Path(gate["files"]["gate_json"]).read_text(encoding="utf-8"))

            self.assertEqual(loaded["format"], "smavg-gate")
            self.assertEqual(loaded["files"]["receipt_json"], gate["files"]["receipt_json"])
            self.assertIn("Use gate.md and context.md as the setup packet.", loaded["operating_rules"])


if __name__ == "__main__":
    unittest.main()
