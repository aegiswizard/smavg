import json
import tempfile
import unittest
from pathlib import Path

from smavg.surfaces import run_surface_gauntlet, scan_surfaces


class SurfaceRegistryTests(unittest.TestCase):
    def test_surface_scan_discovers_skills_plugins_and_sanitizes_configs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            smavg_repo = root / "smavg"
            _write_skill(home / ".codex" / "skills" / "x-browsermcp" / "SKILL.md", "x-browsermcp")
            _write_skill(home / ".agents" / "skills" / "find-skills" / "SKILL.md", "find-skills")
            _write_skill(
                home
                / ".codex"
                / "plugins"
                / "cache"
                / "openai-bundled"
                / "browser"
                / "0.1.0"
                / "skills"
                / "browser"
                / "SKILL.md",
                "browser",
            )
            config = home / ".codex" / "config.toml"
            config.parent.mkdir(parents=True, exist_ok=True)
            config.write_text(
                "\n".join(
                    [
                        "[mcp_servers.browsermcp]",
                        'command = "node"',
                        'api_key = "SECRET-DO-NOT-STORE"',
                    ]
                ),
                encoding="utf-8",
            )
            smavg_repo.mkdir()
            (smavg_repo / "README.md").write_text("# Smavg\n\n## Rule\nExact restore.\n", encoding="utf-8")

            registry = scan_surfaces(
                out_dir=root / "out",
                run_id="scan",
                home=home,
                smavg_repo=smavg_repo,
                budget_tokens=500,
            )

            surfaces = registry["surfaces"]
            self.assertTrue(any(item["type"] == "skill" for item in surfaces))
            self.assertTrue(any(item["type"] == "plugin_skill" for item in surfaces))
            self.assertTrue(any(item["type"] == "plugin_bundle" for item in surfaces))
            self.assertTrue(any(item["type"] == "mcp_config" for item in surfaces))
            self.assertGreaterEqual(registry["summary"]["context_groups"], 4)
            registry_text = Path(registry["surfaces_json"]).read_text(encoding="utf-8")
            self.assertNotIn("SECRET-DO-NOT-STORE", registry_text)
            config_summary = Path(registry["config_summaries"][0]["summary_path"]).read_text(encoding="utf-8")
            self.assertNotIn("SECRET-DO-NOT-STORE", config_summary)
            self.assertIn("api_key:redacted", config_summary)

    def test_surface_gauntlet_verifies_exact_expansion_without_full_raw_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            smavg_repo = root / "smavg"
            for index in range(8):
                _write_skill(
                    home / ".codex" / "skills" / f"workflow-{index}" / "SKILL.md",
                    f"workflow-{index}",
                    body=f"Repeated setup rule {index}\nUse exact expansion.\n",
                )
            smavg_repo.mkdir()
            for index in range(6):
                (smavg_repo / f"note-{index}.md").write_text(
                    "\n".join(
                        [
                            f"# Smavg Note {index}",
                            "",
                            "## Shared",
                            "Use Smavg context first.",
                            "Use exact expansion for file contents.",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )

            report = run_surface_gauntlet(
                root / "gauntlet",
                home=home,
                smavg_repo=smavg_repo,
                budget_tokens=800,
                repeat_count=3,
            )

            self.assertEqual(report["format"], "smavg-surface-gauntlet")
            self.assertFalse(report["summary"]["full_raw_source_supplied_by_smavg"])
            self.assertGreater(report["summary"]["context_groups"], 0)
            self.assertGreater(report["summary"]["exact_expansion_total"], 0)
            self.assertEqual(
                report["summary"]["exact_expansion_pass"],
                report["summary"]["exact_expansion_total"],
            )
            self.assertTrue((root / "gauntlet" / "results.json").exists())
            self.assertTrue((root / "gauntlet" / "report.md").exists())
            loaded = json.loads((root / "gauntlet" / "results.json").read_text(encoding="utf-8"))
            self.assertEqual(loaded["summary"]["failed_groups"], 0)


def _write_skill(path: Path, name: str, body: str = "Use this skill for repeated agent work.\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: Skill {name} for repeated work.",
                "---",
                "",
                f"# {name}",
                "",
                "## Shared Rule",
                body,
                "Do not fake exact file contents.",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
