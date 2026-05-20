import tempfile
import unittest
from pathlib import Path

from smavg.daemon import (
    daemon_status,
    run_daemon_once,
    write_daemon_config,
    write_service_file,
)
from smavg.plugin import build_plugin_bundle, verify_plugin_bundle


class DaemonPluginTests(unittest.TestCase):
    def test_daemon_once_runs_read_only_and_records_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            for index in range(5):
                (source / f"note-{index}.md").write_text(
                    "\n".join(
                        [
                            f"# Note {index}",
                            "",
                            "Shared Smavg daemon scan text.",
                            "The daemon must never delete source data.",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
            daemon_dir = root / "daemon"
            config_path = daemon_dir / "config.json"
            write_daemon_config(
                config_path=config_path,
                root=source,
                daemon_dir=daemon_dir,
                interval_seconds=60,
                include_surfaces=False,
                include_workflows=False,
            )

            report = run_daemon_once(
                config_path=config_path,
                run_id="once",
                include_surfaces=False,
                include_workflows=False,
            )
            status = daemon_status(daemon_dir=daemon_dir, config_path=config_path)

            self.assertEqual(report["format"], "smavg-daemon-run")
            self.assertTrue((daemon_dir / "runs" / "once" / "daemon.json").exists())
            self.assertTrue((daemon_dir / "state.json").exists())
            self.assertTrue(source.exists())
            self.assertFalse(report["actions"]["delete_performed"])
            self.assertFalse(report["actions"]["quarantine_performed"])
            self.assertEqual(status["state"]["last_run_id"], "once")

    def test_service_file_is_written_but_not_loaded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = root / "daemon" / "config.json"
            write_daemon_config(config_path=config, root=root, daemon_dir=root / "daemon")

            service = write_service_file(
                platform_name="systemd",
                out=root / "smavg-daemon.service",
                config_path=config,
                interval_seconds=60,
            )

            self.assertTrue((root / "smavg-daemon.service").exists())
            self.assertFalse(service["installed"])
            self.assertFalse(service["loaded"])
            self.assertIn("smavg.cli daemon run", (root / "smavg-daemon.service").read_text(encoding="utf-8"))

    def test_plugin_bundle_build_and_verify(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "plugin"
            summary = build_plugin_bundle(
                out_dir=root,
                smavg_command="smavg",
                python_executable="python3",
            )
            verify = verify_plugin_bundle(root)

            self.assertEqual(summary["format"], "smavg-plugin-bundle")
            self.assertTrue((root / "skills" / "smavg-repetition-firewall" / "SKILL.md").exists())
            self.assertTrue((root / "mcp" / "smavg-mcp.json").exists())
            self.assertEqual(verify["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
