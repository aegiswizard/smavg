import tempfile
import unittest
from pathlib import Path

from smavg.codex_gauntlet import CodexEvidenceTask, CodexWorkloadProbe
from smavg.gate_gauntlet import run_gate_gauntlet


class GateGauntletTests(unittest.TestCase):
    def test_gate_gauntlet_requires_receipt_and_matching_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            repeated_lines = [
                "Use the Smavg gate packet as setup context.",
                "Expand exact files through receipt-aware commands.",
                "Do not read the raw source tree for setup.",
                "Record every exact expansion in the receipt.",
                "Compare evidence from exact expanded files only.",
            ]
            for index in range(80):
                (source / f"runbook-{index}.md").write_text(
                    "\n".join(
                        [
                            f"# Runbook {index}",
                            "",
                            "## Shared Gate Rule",
                            *repeated_lines,
                            "",
                            "## Repeated Procedure",
                            *repeated_lines,
                            "",
                            "## Validation",
                            *repeated_lines,
                            f"Variable value {index}",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )

            report = run_gate_gauntlet(
                root / "out",
                probes=[
                    CodexWorkloadProbe(
                        name="gate-test",
                        description="Synthetic gate fixture.",
                        source=source,
                        required_paths=("runbook-0.md", "runbook-1.md"),
                        tasks=(
                            CodexEvidenceTask(
                                name="gate-rule",
                                question="Does the packet preserve the gate rule?",
                                required_paths=("runbook-0.md", "runbook-1.md"),
                                evidence_terms=(
                                    "Use the Smavg gate packet as setup context.",
                                    "receipt-aware commands",
                                ),
                            ),
                        ),
                    )
                ],
                budget_tokens=1000,
                repeat_count=3,
            )
            result = report["results"][0]

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["gate_integrity"], "PASS")
            self.assertEqual(result["receipt_integrity"], "PASS")
            self.assertEqual(result["exact_expansion"], "PASS")
            self.assertTrue(result["tasks"][0]["same_evidence"])
            self.assertFalse(result["full_raw_source_supplied_by_smavg"])
            self.assertGreater(result["receipt_reduction_ratio"], 1.0)
            self.assertTrue((root / "out" / "results.json").exists())
            self.assertTrue((root / "out" / "report.md").exists())


if __name__ == "__main__":
    unittest.main()
