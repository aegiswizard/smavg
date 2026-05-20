import tempfile
import unittest
from pathlib import Path

from smavg.codex_gauntlet import CodexEvidenceTask, CodexWorkloadProbe, run_codex_workload_gauntlet


class CodexGauntletTests(unittest.TestCase):
    def test_codex_gauntlet_measures_tokens_and_exact_expansion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "skills"
            source.mkdir()
            for index in range(12):
                (source / f"skill-{index}.md").write_text(
                    "\n".join(
                        [
                            f"# Skill {index}",
                            "",
                            "## Scope",
                            "Use the same browser workflow safely.",
                            "",
                            "## Steps",
                            "Open the target page.",
                            "Inspect the page state.",
                            f"Write the exact result for job {index}.",
                            *[
                                "Stable instruction: preserve exact user intent and verify before acting."
                                for _ in range(20)
                            ],
                            "",
                            "## Verification",
                            "Confirm the exact browser state.",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )

            report = run_codex_workload_gauntlet(
                root / "out",
                probes=[
                    CodexWorkloadProbe(
                        name="skills-test",
                        description="Synthetic repeated skills.",
                        source=source,
                        required_paths=("skill-0.md", "skill-1.md"),
                        tasks=(
                            CodexEvidenceTask(
                                name="browser-workflow-proof",
                                question="Does the workflow preserve exact user intent?",
                                required_paths=("skill-0.md", "skill-1.md"),
                                evidence_terms=(
                                    "Use the same browser workflow safely.",
                                    "Stable instruction",
                                    "Confirm the exact browser state.",
                                ),
                            ),
                        ),
                    )
                ],
                budget_tokens=1000,
                repeat_count=10,
            )
            result = report["results"][0]

            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["exact_expansion"], "PASS")
            self.assertGreater(result["raw_tokens_estimate"], 0)
            self.assertGreater(result["brief_tokens_estimate"], 0)
            self.assertGreater(result["repeated_reduction_ratio"], 1.0)
            self.assertEqual(result["task_summary"]["pass"], 1)
            self.assertEqual(result["tasks"][0]["status"], "PASS")
            self.assertTrue(result["tasks"][0]["raw_correct"])
            self.assertTrue(result["tasks"][0]["smavg_correct"])
            self.assertTrue((root / "out" / "report.md").exists())
            self.assertTrue((root / "out" / "results.json").exists())

    def test_codex_gauntlet_fails_when_required_file_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            (source / "present.md").write_text("# Present\n\nbody\n", encoding="utf-8")

            report = run_codex_workload_gauntlet(
                root / "out",
                probes=[
                    CodexWorkloadProbe(
                        name="missing-required",
                        description="Missing required file.",
                        source=source,
                        required_paths=("missing.md",),
                    )
                ],
            )
            result = report["results"][0]

            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["exact_expansion"], "FAIL")
            self.assertFalse(result["all_required_paths_present"])


if __name__ == "__main__":
    unittest.main()
