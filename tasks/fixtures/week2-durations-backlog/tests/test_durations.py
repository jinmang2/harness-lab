"""Starter tests: `python3 -m unittest discover -s tests`. They cover only part of SPEC.md."""

import unittest

import durations


class ParseTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(durations.parse("1h30m"), 5400)
        self.assertEqual(durations.parse("2d"), 172800)
        self.assertEqual(durations.parse("45s"), 45)

    def test_spaces(self):
        self.assertEqual(durations.parse(" 1h  30m "), 5400)

    def test_bare_number(self):
        self.assertEqual(durations.parse("90"), 90)

    def test_invalid(self):
        for text in ("", "1x", "abc"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                durations.parse(text)


class FormatTest(unittest.TestCase):
    def test_compact(self):
        self.assertEqual(durations.format(5400), "1h30m")
        self.assertEqual(durations.format(0), "0s")


if __name__ == "__main__":
    unittest.main()
