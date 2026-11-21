import unittest

from durutil import parse_duration


class Basics(unittest.TestCase):
    def test_seconds(self):
        self.assertEqual(parse_duration("45s"), 45)

    def test_hours(self):
        self.assertEqual(parse_duration("2h"), 7200)


class Repro(unittest.TestCase):
    def test_repro_minutes(self):
        self.assertEqual(parse_duration("90m"), 5400)

    def test_repro_hours_then_bare_minutes(self):
        self.assertEqual(parse_duration("1h30"), 5400)

    def test_repro_trailing_junk_rejected(self):
        self.assertIsNone(parse_duration("10sx"))


if __name__ == "__main__":
    unittest.main()
