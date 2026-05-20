import tempfile
import unittest
import io
from hashlib import sha256
import json
import lzma
import zlib
from pathlib import Path

from smavg.history_pack import (
    HISTORY_PACK_V2_CODEC,
    HISTORY_PACK_V3_CODEC,
    HISTORY_PACK_V4_CODEC,
    _V3_HEADER,
    decode_history_pack,
    encode_history_pack,
    encode_history_paths,
    history_pack_codec,
    restore_history_pack_member,
    restore_history_pack_member_stream,
)


class HistoryPackTests(unittest.TestCase):
    def test_history_pack_round_trips_real_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            group = source / "notes"
            group.mkdir(parents=True)

            stable = [f"stable line {index:03d}: repeated report text\n" for index in range(120)]
            expected = {}
            for version in range(12):
                body = (
                    ["# Weekly report\n", f"version: {version}\n"]
                    + stable[:60]
                    + [f"measurement: {version * 17}\n"]
                    + stable[60:]
                )
                path = group / f"{version:03d}.md"
                data = "".join(body).encode("utf-8")
                path.write_bytes(data)
                expected[path.relative_to(source).as_posix()] = data

            encoded = encode_history_pack(source)
            self.assertIsNotNone(encoded)
            payload, manifest_files = encoded
            restored = decode_history_pack(payload)

            self.assertIn(
                history_pack_codec(payload),
                {HISTORY_PACK_V2_CODEC, HISTORY_PACK_V3_CODEC, HISTORY_PACK_V4_CODEC},
            )
            self.assertEqual(len(manifest_files), len(expected))
            self.assertEqual(restored, expected)

    def test_history_pack_v3_random_restores_one_member(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            group = source / "history"
            group.mkdir(parents=True)

            expected = {}
            stable = [f"stable line {index:03d}\n" for index in range(400)]
            paths = []
            for version in range(15):
                data = "".join(
                    ["# File\n", f"version: {version}\n"]
                    + stable[:200]
                    + [f"value: {version * 13}\n"]
                    + stable[200:]
                ).encode("utf-8")
                path = group / f"{version:03d}.txt"
                path.write_bytes(data)
                paths.append(path)
                expected[path.relative_to(source).as_posix()] = data

            encoded = encode_history_paths(
                source,
                paths,
                "history-test",
                min_group_size=4,
                checkpoint_interval=3,
            )
            self.assertIsNotNone(encoded)
            payload, manifest_files = encoded

            self.assertGreater(max(int(item["chunk_index"]) for item in manifest_files), 0)
            self.assertEqual(
                restore_history_pack_member(payload, "history/007.txt"),
                expected["history/007.txt"],
            )
            with io.BytesIO(payload) as handle:
                self.assertEqual(
                    restore_history_pack_member_stream(
                        handle,
                        0,
                        len(payload),
                        "history/004.txt",
                    ),
                    expected["history/004.txt"],
                )

    def test_history_pack_v4_rejects_bad_chunk_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            group = source / "history"
            group.mkdir(parents=True)
            stable = [f"stable line {index:03d}\n" for index in range(180)]
            paths = []
            for version in range(12):
                data = "".join(
                    ["# File\n", f"version: {version}\n"]
                    + stable[:90]
                    + [f"value: {version * 17}\n"]
                    + stable[90:]
                ).encode("utf-8")
                path = group / f"{version:03d}.txt"
                path.write_bytes(data)
                paths.append(path)

            encoded = encode_history_paths(
                source,
                paths,
                "history-test",
                min_group_size=4,
                checkpoint_interval=3,
            )
            self.assertIsNotNone(encoded)
            payload, _manifest_files = encoded
            self.assertEqual(history_pack_codec(payload), HISTORY_PACK_V4_CODEC)

            magic, index_len, chunks_len, _index_sha = _V3_HEADER.unpack(
                payload[: _V3_HEADER.size]
            )
            index_start = _V3_HEADER.size
            index_end = index_start + index_len
            index_document = json.loads(zlib.decompress(payload[index_start:index_end]))
            index_document["chunks"][0]["root"] = "0" * 64
            replacement_index = zlib.compress(
                json.dumps(index_document, sort_keys=True, separators=(",", ":")).encode("utf-8"),
                level=9,
            )
            corrupted = (
                _V3_HEADER.pack(
                    magic,
                    len(replacement_index),
                    chunks_len,
                    sha256(replacement_index).digest(),
                )
                + replacement_index
                + payload[index_end:]
            )

            with self.assertRaisesRegex(ValueError, "root"):
                decode_history_pack(corrupted)

    def test_history_pack_rejects_unsafe_path(self):
        payload = lzma.compress(
            json.dumps(
                {
                    "v": 2,
                    "groups": [
                        {
                            "parent": "bad",
                            "files": [["base", "../evil.txt", "0" * 64, 0, ""]],
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode("latin1")
        )

        with self.assertRaisesRegex(ValueError, "Unsafe"):
            decode_history_pack(payload)

    def test_history_pack_rejects_bad_member_hash(self):
        payload = lzma.compress(
            json.dumps(
                {
                    "v": 2,
                    "groups": [
                        {
                            "parent": "bad",
                            "files": [["base", "safe.txt", "0" * 64, 4, "data"]],
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode("latin1")
        )

        with self.assertRaisesRegex(ValueError, "SHA-256"):
            decode_history_pack(payload)

    def test_history_pack_rejects_delta_without_base(self):
        payload = lzma.compress(
            json.dumps(
                {
                    "v": 2,
                    "groups": [
                        {
                            "parent": "bad",
                            "files": [["delta", "safe.txt", "0" * 64, 0, []]],
                        }
                    ],
                },
                separators=(",", ":"),
            ).encode("latin1")
        )

        with self.assertRaisesRegex(ValueError, "no base"):
            decode_history_pack(payload)


if __name__ == "__main__":
    unittest.main()
