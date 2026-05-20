import unittest

from smavg.line_template import render_line_template, try_line_template


class LineTemplateTests(unittest.TestCase):
    def test_log_like_lines_round_trip(self):
        lines = []
        for index in range(40):
            lines.append(
                f"[2026-05-09 10:{index:02d}:00] INFO worker-{index % 4} completed job {1000 + index}\n"
            )
        data = "".join(lines).encode("utf-8")

        payload = try_line_template(data)

        self.assertIsNotNone(payload)
        self.assertEqual(render_line_template(payload), data)


if __name__ == "__main__":
    unittest.main()
