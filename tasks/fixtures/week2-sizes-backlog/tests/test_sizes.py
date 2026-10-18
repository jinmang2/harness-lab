import unittest

import sizes


class ParseTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(sizes.parse("1 KiB"), 1024)
        self.assertEqual(sizes.parse("2 KB"), 2000)
        self.assertEqual(sizes.parse("1MiB"), 1048576)

    def test_bare_number(self):
        self.assertEqual(sizes.parse("512"), 512)


class FormatTest(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(sizes.format(1536), "1.5 KiB")
        self.assertEqual(sizes.format(512), "512 B")


if __name__ == "__main__":
    unittest.main()
