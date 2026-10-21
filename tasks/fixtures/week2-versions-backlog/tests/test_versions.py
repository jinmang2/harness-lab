import unittest

import versions


class ParseTest(unittest.TestCase):
    def test_core(self):
        self.assertEqual(versions.parse("1.2.3"), (1, 2, 3, (), ()))

    def test_prerelease_and_build(self):
        self.assertEqual(versions.parse("1.2.3-alpha.1+build.5"), (1, 2, 3, ("alpha", 1), ("build", "5")))


class CompareTest(unittest.TestCase):
    def test_core(self):
        self.assertEqual(versions.compare("1.2.3", "1.2.4"), -1)
        self.assertEqual(versions.compare("2.0.0", "1.9.9"), 1)


class SatisfiesTest(unittest.TestCase):
    def test_comparators(self):
        self.assertTrue(versions.satisfies("1.5.0", ">=1.2.3 <2.0.0"))
        self.assertFalse(versions.satisfies("2.0.0", ">=1.2.3 <2.0.0"))

    def test_caret(self):
        self.assertTrue(versions.satisfies("1.9.0", "^1.2.3"))


if __name__ == "__main__":
    unittest.main()
