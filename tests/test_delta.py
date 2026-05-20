import unittest
import json

from smavg.delta import DeltaError, apply_delta, create_delta, sha256_bytes


class DeltaTests(unittest.TestCase):
    def test_delta_round_trips_changed_text(self):
        base = b"alpha\nbravo\ncharlie\n"
        target = b"alpha\nbravo updated\ncharlie\nnew line\n"

        delta = create_delta(base, target)

        self.assertEqual(apply_delta(base, delta), target)

    def test_delta_round_trips_empty_target(self):
        base = b"alpha\nbravo\n"
        target = b""

        delta = create_delta(base, target)

        self.assertEqual(apply_delta(base, delta), target)

    def test_delta_rejects_wrong_base(self):
        delta = create_delta(b"alpha\n", b"beta\n")

        with self.assertRaisesRegex(DeltaError, "Base content"):
            apply_delta(b"other\n", delta)

    def test_delta_rejects_copy_outside_base(self):
        document = {
            "v": 1,
            "base_sha256": sha256_bytes(b"abc"),
            "target_sha256": sha256_bytes(b"abc"),
            "target_size": 3,
            "ops": [["copy", 0, 99]],
        }

        with self.assertRaisesRegex(DeltaError, "outside"):
            apply_delta(b"abc", json.dumps(document).encode("utf-8"))

    def test_delta_rejects_invalid_base64(self):
        document = {
            "v": 1,
            "base_sha256": sha256_bytes(b""),
            "target_sha256": sha256_bytes(b""),
            "target_size": 0,
            "ops": [["data", "not base64!!!"]],
        }

        with self.assertRaisesRegex(DeltaError, "base64"):
            apply_delta(b"", json.dumps(document).encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
