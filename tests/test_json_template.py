import unittest
import json

from smavg.json_template import (
    MAX_TEMPLATE_DEPTH,
    apply_template,
    canonical_json_bytes,
    render_json_template,
    try_json_template,
)


class JsonTemplateTests(unittest.TestCase):
    def test_canonical_json_round_trips_as_template(self):
        data = canonical_json_bytes(
            {
                "cveID": "CVE-2026-0001",
                "dateAdded": "2026-05-09",
                "knownRansomwareCampaignUse": "Unknown",
                "shortDescription": "Real records use repeated keys with changing values.",
            }
        )

        result = try_json_template(data)

        self.assertIsNotNone(result)
        template, variables = result
        self.assertEqual(render_json_template(template, variables), data)

    def test_noncanonical_json_is_not_claimed(self):
        data = json.dumps({"b": 1, "a": 2}).encode("utf-8")

        self.assertIsNone(try_json_template(data))

    def test_apply_template_rejects_excessive_depth_cleanly(self):
        node = ["v", 0]
        for _ in range(MAX_TEMPLATE_DEPTH + 2):
            node = ["l", [node]]

        with self.assertRaisesRegex(ValueError, "maximum depth"):
            apply_template(node, ["value"])


if __name__ == "__main__":
    unittest.main()
