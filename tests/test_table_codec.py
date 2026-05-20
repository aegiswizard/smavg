import unittest

from smavg.table_codec import render_columnar_table, try_columnar_table


class TableCodecTests(unittest.TestCase):
    def test_simple_csv_round_trips(self):
        lines = ["date,tmax,tmin,prcp\n"]
        for index in range(40):
            lines.append(f"2026-05-{(index % 28) + 1:02d},{70 + index % 5},{50 + index % 3},0\n")
        data = "".join(lines).encode("utf-8")

        payload = try_columnar_table(data)

        self.assertIsNotNone(payload)
        self.assertEqual(render_columnar_table(payload), data)


if __name__ == "__main__":
    unittest.main()
