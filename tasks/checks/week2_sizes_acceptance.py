"""week2 acceptance suite for the `sizes` task: one test per SPEC.md rule.

    python3 week2_sizes_acceptance.py [WORKSPACE]   # default: current directory

Same contract as week2_acceptance.py: imports `sizes` from WORKSPACE, prints one JSON line
(`{"passed", "total", "failed": [{"test", "rule", "error"}]}`) and exits 0 only when every
test passes. The starter tests in the workspace cover only part of the spec.
"""

from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path

sizes = None  # imported in main() from the workspace


class Rules(unittest.TestCase):
    def assertInvalid(self, *texts: str) -> None:
        for text in texts:
            with self.subTest(text=text), self.assertRaises(ValueError):
                sizes.parse(text)

    def test_r01_units(self):
        """rule 1: decimal and binary units, case-sensitive"""
        cases = {"1 B": 1, "1 KB": 1000, "1 MB": 10**6, "1 GB": 10**9, "1 TB": 10**12,
                 "1 KiB": 1024, "1 MiB": 1024**2, "1 GiB": 1024**3, "1 TiB": 1024**4}
        for text, want in cases.items():
            with self.subTest(text=text):
                self.assertEqual(sizes.parse(text), want)
        self.assertInvalid("1 kb", "1 KIB", "1 mb", "1 kib", "1 Kb", "1 b")

    def test_r02_form(self):
        """rule 2: at most one space before the unit, outer whitespace ignored"""
        self.assertEqual(sizes.parse("1.5KiB"), 1536)
        self.assertEqual(sizes.parse("1.5 KiB"), 1536)
        self.assertEqual(sizes.parse("  2 KB \n"), 2000)
        self.assertInvalid("1.5  KiB", "1.5\tKiB", "1 K iB")

    def test_r03_bare_number(self):
        """rule 3: a bare integer is bytes"""
        self.assertEqual(sizes.parse("512"), 512)
        self.assertEqual(sizes.parse("0"), 0)

    def test_r04_decimals(self):
        """rule 4: decimals allowed, total must be whole bytes"""
        self.assertEqual(sizes.parse("0.5 KiB"), 512)
        self.assertEqual(sizes.parse("1.25 KB"), 1250)
        self.assertEqual(sizes.parse("0.001 KB"), 1)
        self.assertInvalid("0.1 B", "1.0001 KB", "0.3 KiB")

    def test_r05_digits(self):
        """rule 5: ASCII digits, underscores only between integer digits"""
        self.assertEqual(sizes.parse("1_000 B"), 1000)
        self.assertEqual(sizes.parse("1_024_000"), 1024000)
        self.assertInvalid("_1 B", "1_ B", "1__0 B", "1,000 B", "1e3 B", "١ B", "1.5_0 KiB")

    def test_r06_sign(self):
        """rule 6: no sign, leading zeros fine"""
        self.assertEqual(sizes.parse("007 B"), 7)
        self.assertInvalid("-1 B", "+1 B", "-0")

    def test_r07_empty(self):
        """rule 7: empty, unit without number, trailing dot"""
        self.assertInvalid("", "   ", "KiB", " B", "1. KiB")

    def test_r08_type(self):
        """rule 8: non-str is a TypeError"""
        for value in (1024, None, b"1 KiB", 1.5):
            with self.subTest(value=value), self.assertRaises(TypeError):
                sizes.parse(value)

    def test_r09_unit_choice(self):
        """rule 9: largest unit with value >= 1, binary by default"""
        self.assertEqual(sizes.format(1536), "1.5 KiB")
        self.assertEqual(sizes.format(1500, binary=False), "1.5 KB")
        self.assertEqual(sizes.format(512), "512 B")
        self.assertEqual(sizes.format(0), "0 B")
        self.assertEqual(sizes.format(1023), "1023 B")
        self.assertEqual(sizes.format(999, binary=False), "999 B")
        self.assertEqual(sizes.format(5 * 1024**4), "5 TiB")
        self.assertEqual(sizes.format(3 * 1024**5), "3072 TiB")
        self.assertEqual(sizes.format(2_500_000_000, binary=False), "2.5 GB")

    def test_r10_rounding(self):
        """rule 10: round half to even on the exact value, drop trailing zeros"""
        self.assertEqual(sizes.format(2304), "2.2 KiB")
        self.assertEqual(sizes.format(2816), "2.8 KiB")
        self.assertEqual(sizes.format(1024), "1 KiB")
        self.assertEqual(sizes.format(1126), "1.1 KiB")
        self.assertEqual(sizes.format(1536, precision=0), "2 KiB")
        self.assertEqual(sizes.format(2560, precision=0), "2 KiB")
        self.assertEqual(sizes.format(1234567, binary=False, precision=3), "1.235 MB")
        self.assertEqual(sizes.format(1250, binary=False, precision=3), "1.25 KB")
        self.assertEqual(sizes.format(1023, precision=3), "1023 B")

    def test_r11_carry(self):
        """rule 11: rounding up to the next base shows the next unit"""
        self.assertEqual(sizes.format(1048525), "1 MiB")
        self.assertEqual(sizes.format(1048524), "1023.9 KiB")
        self.assertEqual(sizes.format(999_950, binary=False), "1 MB")
        self.assertEqual(sizes.format(1023 * 1024 + 1000, precision=0), "1 MiB")

    def test_r12_errors(self):
        """rule 12: negative size or precision is a ValueError, non-int size a TypeError"""
        with self.assertRaises(ValueError):
            sizes.format(-1)
        with self.assertRaises(ValueError):
            sizes.format(1024, precision=-1)
        for value in (1.0, True, "1024", None):
            with self.subTest(value=value), self.assertRaises(TypeError):
                sizes.format(value)

    def test_r13_round_trip(self):
        """round trip: parse(format(n)) == n when format is exact"""
        for n in (0, 1, 512, 1023, 1024, 1536, 2048, 1024**2, 3 * 1024**3, 1024**4):
            with self.subTest(n=n):
                self.assertEqual(sizes.parse(sizes.format(n)), n)
        for n in (1000, 1500, 10**6, 2_500_000_000):
            with self.subTest(n=n, binary=False):
                self.assertEqual(sizes.parse(sizes.format(n, binary=False)), n)


class _Collect(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.failed_tests: dict[str, dict[str, str]] = {}

    def _note(self, test, err) -> None:
        method = getattr(test, "test_case", test)
        name = method.id().rsplit(".", 1)[-1]
        if name not in self.failed_tests:
            doc = (getattr(method, "_testMethodDoc", None) or "").strip()
            self.failed_tests[name] = {"test": name, "rule": doc, "error": self._exc_info_to_string(err, test).strip().splitlines()[-1][:300]}

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._note(test, err)

    def addError(self, test, err):
        super().addError(test, err)
        self._note(test, err)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        if err is not None:
            self._note(subtest, err)


def main() -> int:
    global sizes
    workspace = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    sys.path.insert(0, str(workspace))
    total = len(unittest.defaultTestLoader.getTestCaseNames(Rules))
    try:
        sizes = importlib.import_module("sizes")
    except Exception as exc:  # noqa: BLE001 - any import failure fails every rule
        print(json.dumps({"passed": 0, "total": total, "failed": [{"test": "import", "rule": "", "error": repr(exc)[:300]}]}))
        return 1
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Rules)
    with open("/dev/null", "w") as sink:
        result = unittest.TextTestRunner(stream=sink, resultclass=_Collect, verbosity=0).run(suite)
    failed = list(result.failed_tests.values())
    print(json.dumps({"passed": total - len(failed), "total": total, "failed": failed}, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
