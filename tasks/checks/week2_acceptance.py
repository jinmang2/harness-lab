"""week2 acceptance suite for the `durations` task: one test per SPEC.md rule.

    python3 week2_acceptance.py [WORKSPACE]   # default: current directory

Imports `durations` from WORKSPACE, runs every test, prints one JSON line
(`{"passed": n, "total": n, "failed": [{"test": ..., "rule": ..., "error": ...}]}`)
and exits 0 only when every test passes. It lives outside the task workspace: the
starter tests there cover only part of the spec. Both a verifier that runs between
rounds and the final grading use this same file.
"""

from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path

durations = None  # imported in main() from the workspace


class Rules(unittest.TestCase):
    def assertInvalid(self, *texts: str) -> None:
        for text in texts:
            with self.subTest(text=text), self.assertRaises(ValueError):
                durations.parse(text)

    def test_r01_units(self):
        """rule 1: d/h/m/s, case-insensitive"""
        self.assertEqual(durations.parse("1h30m"), 5400)
        self.assertEqual(durations.parse("1d2h3m4s"), 93784)
        self.assertEqual(durations.parse("1H30M"), 5400)
        self.assertEqual(durations.parse("2D"), 172800)

    def test_r02_spaces(self):
        """rule 2: whitespace between parts and around the text"""
        self.assertEqual(durations.parse(" 1h  30m "), 5400)
        self.assertEqual(durations.parse("\t1d 1s\n"), 86401)

    def test_r03_bare_number(self):
        """rule 3: a bare non-negative integer is seconds"""
        self.assertEqual(durations.parse("90"), 90)
        self.assertEqual(durations.parse("0"), 0)
        self.assertEqual(durations.parse(" 7 "), 7)

    def test_r04_decimals(self):
        """rule 4: decimal parts, total must be whole seconds"""
        self.assertEqual(durations.parse("1.5h"), 5400)
        self.assertEqual(durations.parse("0.5m"), 30)
        self.assertEqual(durations.parse("1.25m30s"), 105)
        self.assertInvalid("0.5s", "1.01m", "1.h", ".5h")

    def test_r05_order(self):
        """rule 5: largest unit first, each unit once"""
        self.assertInvalid("30m1h", "1h1h", "1s1m", "1d1d")

    def test_r06_dangling_number(self):
        """rule 6: no number without a unit once units are used"""
        self.assertInvalid("1h30", "90 1h", "1h 30")

    def test_r07_sign(self):
        """rule 7: one leading minus for the whole span"""
        self.assertEqual(durations.parse("-1h30m"), -5400)
        self.assertEqual(durations.parse("-90"), -90)
        self.assertEqual(durations.parse(" -1d "), -86400)
        self.assertInvalid("1h-30m", "--1h", "+1h", "- 1h")

    def test_r08_iso(self):
        """rule 8: ISO 8601 durations, uppercase, integers"""
        self.assertEqual(durations.parse("PT1H30M"), 5400)
        self.assertEqual(durations.parse("P1DT2H"), 93600)
        self.assertEqual(durations.parse("P2D"), 172800)
        self.assertEqual(durations.parse("PT0S"), 0)
        self.assertEqual(durations.parse("PT45S"), 45)
        self.assertInvalid("P", "PT", "pt1h", "PT1.5H", "P1H", "PT1D", "P1DT")

    def test_r09_empty(self):
        """rule 9: empty text or a unit without a number"""
        self.assertInvalid("", "   ", "h", "1h m")

    def test_r10_type(self):
        """rule 10: non-str argument is a TypeError"""
        for value in (5400, None, b"1h"):
            with self.subTest(value=value), self.assertRaises(TypeError):
                durations.parse(value)

    def test_r11_format_compact(self):
        """rule 11: compact format"""
        self.assertEqual(durations.format(5400), "1h30m")
        self.assertEqual(durations.format(90061), "1d1h1m1s")
        self.assertEqual(durations.format(0), "0s")
        self.assertEqual(durations.format(59), "59s")
        self.assertEqual(durations.format(86400), "1d")
        self.assertEqual(durations.format(-93600), "-1d2h")

    def test_r12_format_iso(self):
        """rule 12: ISO format, negative is a ValueError"""
        self.assertEqual(durations.format(5400, iso=True), "PT1H30M")
        self.assertEqual(durations.format(86400, iso=True), "P1D")
        self.assertEqual(durations.format(93600, iso=True), "P1DT2H")
        self.assertEqual(durations.format(0, iso=True), "PT0S")
        self.assertEqual(durations.format(61, iso=True), "PT1M1S")
        with self.assertRaises(ValueError):
            durations.format(-1, iso=True)

    def test_r13_round_trip(self):
        """round trip: parse(format(n)) == n"""
        for n in (0, 1, 59, 60, 3599, 3600, 86399, 86400, 90061, 1_000_000, -1, -5400):
            with self.subTest(n=n):
                self.assertEqual(durations.parse(durations.format(n)), n)
            if n >= 0:
                with self.subTest(n=n, iso=True):
                    self.assertEqual(durations.parse(durations.format(n, iso=True)), n)


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
    global durations
    workspace = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    sys.path.insert(0, str(workspace))
    total = len(unittest.defaultTestLoader.getTestCaseNames(Rules))
    try:
        durations = importlib.import_module("durations")
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
