import json
import tempfile
import unittest
from pathlib import Path

from smavg.mcp_server import handle_raw_message


class McpServerTests(unittest.TestCase):
    def test_initialize_and_tools_list(self):
        initialize = handle_raw_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18"},
                }
            )
        )
        self.assertEqual(initialize["result"]["serverInfo"]["name"], "smavg")
        self.assertIn("tools", initialize["result"]["capabilities"])

        listed = handle_raw_message(
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        )
        names = {tool["name"] for tool in listed["result"]["tools"]}

        self.assertIn("smavg_preflight", names)
        self.assertIn("smavg_gate", names)
        self.assertIn("smavg_expand", names)
        self.assertIn("smavg_scan", names)
        self.assertIn("smavg_safe_pack", names)
        self.assertIn("smavg_receipt", names)
        self.assertIn("smavg_workflows", names)
        self.assertIn("smavg_surface_scan", names)
        self.assertIn("smavg_surface_gauntlet", names)
        self.assertIn("smavg_status", names)
        self.assertIn("smavg_autopilot", names)
        self.assertIn("smavg_daemon_once", names)
        self.assertIn("smavg_daemon_status", names)
        self.assertIn("smavg_plugin_build", names)
        self.assertIn("smavg_plugin_verify", names)

    def test_preflight_tool_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.mkdir()
            for index in range(4):
                (source / f"handoff-{index}.md").write_text(
                    "\n".join(
                        [
                            f"# Handoff {index}",
                            "",
                            "## Shared",
                            "Use Smavg preflight before repeated work.",
                            f"Variable {index}",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )

            response = handle_raw_message(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "smavg_preflight",
                            "arguments": {
                                "source": str(source),
                                "out_dir": str(root / "preflights"),
                                "run_id": "mcp-test",
                                "budget": 1000,
                            },
                        },
                    }
                )
            )

            result = response["result"]
            structured = result["structuredContent"]

            self.assertFalse(result["isError"])
            self.assertEqual(structured["format"], "smavg-preflight")
            self.assertEqual(structured["target_kind"], "directory")
            self.assertTrue(Path(structured["context_markdown"]).exists())
            self.assertTrue(Path(structured["context_json"]).exists())
            self.assertTrue(Path(structured["preflight_markdown"]).exists())
            self.assertTrue(Path(structured["preflight_json"]).exists())
            self.assertGreater(structured["raw_tokens_estimate"], 0)

    def test_tool_originated_failure_is_visible_to_model(self):
        response = handle_raw_message(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "tools/call",
                    "params": {
                        "name": "smavg_preflight",
                        "arguments": {
                            "source": "/path/that/does/not/exist",
                            "out_dir": "/tmp/smavg-mcp-test",
                            "run_id": "bad",
                        },
                    },
                }
            )
        )

        self.assertTrue(response["result"]["isError"])
        self.assertIn("Not a directory", response["result"]["content"][0]["text"])

    def test_notifications_do_not_emit_responses(self):
        response = handle_raw_message(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
        )

        self.assertIsNone(response)


if __name__ == "__main__":
    unittest.main()
