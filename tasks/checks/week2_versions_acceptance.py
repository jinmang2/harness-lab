"""week2 acceptance suite for the `versions` task: one test per SPEC.md rule, plus the ordering line.

    python3 week2_versions_acceptance.py [WORKSPACE]   # default: current directory

Same contract as week2_acceptance.py: imports `versions` from WORKSPACE, prints one JSON line
(`{"passed", "total", "failed": [{"test", "rule", "error"}]}`) and exits 0 only when every
test passes. The starter tests in the workspace cover only part of the spec.
"""

from __future__ import annotations

import functools
import importlib
import json
import random
import sys
import unittest
from pathlib import Path

versions = None  # imported in main() from the workspace


class Rules(unittest.TestCase):
    def assertBadVersion(self, *texts: str) -> None:
        for text in texts:
            with self.subTest(text=text), self.assertRaises(ValueError):
                versions.parse(text)

    def assertMatches(self, range_: str, yes: list[str], no: list[str]) -> None:
        for v in yes:
            with self.subTest(range=range_, version=v):
                self.assertTrue(versions.satisfies(v, range_))
        for v in no:
            with self.subTest(range=range_, version=v):
                self.assertFalse(versions.satisfies(v, range_))

    def test_r01_core(self):
        """rule 1: three non-negative integers, no leading zeros"""
        self.assertEqual(versions.parse("1.2.3"), (1, 2, 3, (), ()))
        self.assertEqual(versions.parse("0.0.0"), (0, 0, 0, (), ()))
        self.assertEqual(versions.parse("10.20.30"), (10, 20, 30, (), ()))
        self.assertBadVersion("01.2.3", "1.02.3", "1.2.03", "1.2", "1.2.3.4", "1..3", "-1.2.3", "1.2.x", "a.b.c", "١.2.3")

    def test_r02_prerelease(self):
        """rule 2: dot-separated prerelease identifiers, numeric ones without leading zeros"""
        self.assertEqual(versions.parse("1.0.0-alpha"), (1, 0, 0, ("alpha",), ()))
        self.assertEqual(versions.parse("1.0.0-alpha.1"), (1, 0, 0, ("alpha", 1), ()))
        self.assertEqual(versions.parse("1.0.0-0a.x-y.7"), (1, 0, 0, ("0a", "x-y", 7), ()))
        self.assertEqual(versions.parse("1.0.0-0"), (1, 0, 0, (0,), ()))
        self.assertBadVersion("1.0.0-01", "1.0.0-", "1.0.0-alpha..1", "1.0.0-al_pha", "1.0.0-alpha.")

    def test_r03_build(self):
        """rule 3: build identifiers after +, leading zeros allowed"""
        self.assertEqual(versions.parse("1.0.0+build.05"), (1, 0, 0, (), ("build", "05")))
        self.assertEqual(versions.parse("1.0.0-rc.1+001"), (1, 0, 0, ("rc", 1), ("001",)))
        self.assertBadVersion("1.0.0+", "1.0.0+a..b", "1.0.0+a+b", "1.0.0+ä")

    def test_r04_prefix_whitespace_and_type(self):
        """rule 4: outer whitespace and one leading v or = are ignored; non-str is TypeError"""
        self.assertEqual(versions.parse(" v1.2.3 "), (1, 2, 3, (), ()))
        self.assertEqual(versions.parse("=1.2.3"), (1, 2, 3, (), ()))
        self.assertBadVersion("vv1.2.3", "V1.2.3", "v 1.2.3", "1.2.3 x", "==1.2.3", "")
        for bad in (None, 1, (1, 2, 3), b"1.2.3"):
            with self.subTest(arg=bad), self.assertRaises(TypeError):
                versions.parse(bad)

    def test_r05_core_order(self):
        """rule 5: major, minor, patch compared numerically"""
        self.assertEqual(versions.compare("1.10.0", "1.9.0"), 1)
        self.assertEqual(versions.compare("1.2.10", "1.2.9"), 1)
        self.assertEqual(versions.compare("2.0.0", "10.0.0"), -1)
        self.assertEqual(versions.compare("1.2.3", "v1.2.3"), 0)

    def test_r06_prerelease_is_lower(self):
        """rule 6: a prerelease is lower than its release"""
        self.assertEqual(versions.compare("1.0.0-rc.1", "1.0.0"), -1)
        self.assertEqual(versions.compare("1.0.0", "1.0.0-0"), 1)
        self.assertEqual(versions.compare("1.0.1-alpha", "1.0.0"), 1)

    def test_r07_prerelease_order(self):
        """rule 7: identifiers left to right, numeric < alphanumeric, shorter is lower"""
        chain = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
                 "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]
        for lo, hi in zip(chain, chain[1:]):
            with self.subTest(lo=lo, hi=hi):
                self.assertEqual(versions.compare(lo, hi), -1)
                self.assertEqual(versions.compare(hi, lo), 1)
        self.assertEqual(versions.compare("1.0.0-2", "1.0.0-10"), -1)
        self.assertEqual(versions.compare("1.0.0-9", "1.0.0-a"), -1)
        self.assertEqual(versions.compare("1.0.0-B", "1.0.0-a"), -1)  # ASCII: uppercase sorts first

    def test_r08_build_ignored(self):
        """rule 8: build metadata does not affect precedence"""
        self.assertEqual(versions.compare("1.0.0+a", "1.0.0+b"), 0)
        self.assertEqual(versions.compare("1.0.0-rc.1+x", "1.0.0-rc.1"), 0)
        self.assertEqual(versions.compare("1.0.0+zzz", "1.0.1"), -1)

    def test_r09_comparators(self):
        """rule 9: >, >=, <, <=, =, bare version, sets and ||, spaces after operators"""
        self.assertMatches(">=1.2.3 <2.0.0", ["1.2.3", "1.9.9"], ["1.2.2", "2.0.0"])
        self.assertMatches(">1.2.3", ["1.2.4"], ["1.2.3"])
        self.assertMatches("<=1.2.3", ["1.2.3", "0.1.0"], ["1.2.4"])
        self.assertMatches("=1.2.3", ["1.2.3", "1.2.3+build"], ["1.2.4"])
        self.assertMatches("1.2.3", ["1.2.3"], ["1.2.4"])
        self.assertMatches(">= 1.2.3 < 1.3.0", ["1.2.5"], ["1.3.0"])
        self.assertMatches("<1.0.0 || >=2.0.0", ["0.5.0", "2.1.0"], ["1.5.0"])
        self.assertMatches("  1.2.3||1.2.5  ", ["1.2.3", "1.2.5"], ["1.2.4"])

    def test_r10_partial_and_x_ranges(self):
        """rule 10: partial versions, x/X/*, empty range, operators on partial versions"""
        self.assertMatches("1.2.x", ["1.2.0", "1.2.99"], ["1.3.0", "1.1.9"])
        self.assertMatches("1.2", ["1.2.7"], ["1.3.0"])
        self.assertMatches("1", ["1.0.0", "1.99.99"], ["2.0.0", "0.9.9"])
        self.assertMatches("1.X", ["1.4.0"], ["2.0.0"])
        self.assertMatches("1.*.*", ["1.4.0"], ["2.0.0"])
        self.assertMatches("*", ["0.0.0", "99.0.0"], [])
        self.assertMatches("", ["1.2.3"], [])
        self.assertMatches(">=1.2", ["1.2.0"], ["1.1.9"])
        self.assertMatches(">1.2", ["1.3.0"], ["1.2.9"])
        self.assertMatches("<1.2", ["1.1.9"], ["1.2.0"])
        self.assertMatches("<=1.2", ["1.2.9"], ["1.3.0"])
        self.assertMatches(">1", ["2.0.0"], ["1.9.9"])

    def test_r11_tilde(self):
        """rule 11: ~ allows patch-level changes"""
        self.assertMatches("~1.2.3", ["1.2.3", "1.2.9"], ["1.3.0", "1.2.2"])
        self.assertMatches("~1.2", ["1.2.0", "1.2.9"], ["1.3.0"])
        self.assertMatches("~1", ["1.0.0", "1.9.0"], ["2.0.0"])
        self.assertMatches("~0.2.3", ["0.2.5"], ["0.3.0"])
        self.assertMatches("~1.2.3-beta.2", ["1.2.3-beta.2", "1.2.3-beta.4", "1.2.3", "1.2.7"], ["1.2.3-beta.1", "1.3.0"])

    def test_r12_caret(self):
        """rule 12: ^ keeps the left-most non-zero part"""
        self.assertMatches("^1.2.3", ["1.2.3", "1.9.9"], ["2.0.0", "1.2.2"])
        self.assertMatches("^0.2.3", ["0.2.3", "0.2.9"], ["0.3.0"])
        self.assertMatches("^0.0.3", ["0.0.3"], ["0.0.4", "0.0.2"])
        self.assertMatches("^1.2", ["1.2.0", "1.9.0"], ["2.0.0"])
        self.assertMatches("^0.2", ["0.2.0", "0.2.9"], ["0.3.0"])
        self.assertMatches("^0.0", ["0.0.0", "0.0.9"], ["0.1.0"])
        self.assertMatches("^0", ["0.0.0", "0.9.9"], ["1.0.0"])
        self.assertMatches("^1.x", ["1.0.0", "1.5.0"], ["2.0.0"])
        self.assertMatches("^0.0.0", ["0.0.0"], ["0.0.1"])

    def test_r13_hyphen(self):
        """rule 13: A - B, partial A filled with zeros, partial B includes its span"""
        self.assertMatches("1.2.3 - 2.3.4", ["1.2.3", "2.3.4"], ["1.2.2", "2.3.5"])
        self.assertMatches("1.2 - 2.3.4", ["1.2.0"], ["1.1.9"])
        self.assertMatches("1.2.3 - 2.3", ["2.3.9"], ["2.4.0"])
        self.assertMatches("1.2.3 - 2", ["2.9.9"], ["3.0.0"])
        self.assertMatches("1.0.0 - 1.2.0 || 2.x", ["1.1.0", "2.5.0"], ["1.5.0"])

    def test_r14_prereleases_need_an_invitation(self):
        """rule 14: a prerelease matches only via a same-tuple prerelease comparator in its set"""
        self.assertMatches(">1.2.3-alpha.3", ["1.2.3-alpha.7", "1.2.3", "3.4.5"], ["3.4.5-alpha.9", "1.2.3-alpha.2"])
        self.assertMatches("^0.9.0", ["0.9.5"], ["1.0.0-rc.1", "0.9.5-beta"])
        self.assertMatches("<1.0.0", ["0.9.0"], ["1.0.0-rc.1"])
        self.assertMatches("^1.2.3-beta.2", ["1.2.3-beta.4", "1.5.0"], ["1.2.4-beta.1", "1.2.3-beta.1"])
        self.assertMatches(">=1.0.0-0 <1.0.0", ["1.0.0-alpha"], ["0.9.0-alpha"])
        self.assertMatches("*", ["1.0.0"], ["1.0.0-rc.1"])
        self.assertMatches("1.2.3-beta.1 - 1.2.3", ["1.2.3-beta.5"], ["1.2.4-beta.1"])
        self.assertMatches(">=1.2.3-beta.1 || >=2.0.0", ["1.2.3-beta.2"], ["2.0.1-beta.1"])

    def test_r15_max_satisfying(self):
        """rule 15: highest match as written, None when none, invalid item raises"""
        self.assertEqual(versions.max_satisfying(["1.2.3", "v1.2.4", "1.3.0"], "~1.2"), "v1.2.4")
        self.assertEqual(versions.max_satisfying(["1.10.0", "1.9.0", "1.2.0"], "^1.0.0"), "1.10.0")
        self.assertEqual(versions.max_satisfying(["1.2.3-beta.1", "1.2.2"], "^1.2.0"), "1.2.2")
        self.assertIsNone(versions.max_satisfying(["2.0.0", "3.0.0"], "^1.0.0"))
        self.assertIsNone(versions.max_satisfying([], "*"))
        with self.assertRaises(ValueError):
            versions.max_satisfying(["1.2.3", "1.2"], "*")

    def test_r16_invalid_ranges(self):
        """rule 16: unknown or dangling operators, partial prereleases, bad hyphen ranges, non-str"""
        for bad in ("=>1.2.3", "~>1.2", ">=", "1.2-beta", ">=1.2.3 - 2.0.0", "1.0.0 - 2.0.0 <1.5.0",
                    ">=a.b.c", "1.2.3 -", "!1.2.3", "1.x.3"):
            with self.subTest(range=bad), self.assertRaises(ValueError):
                versions.satisfies("1.2.3", bad)
        with self.assertRaises(ValueError):
            versions.satisfies("1.2", "*")
        for args in ((None, "*"), ("1.2.3", None)):
            with self.subTest(args=args), self.assertRaises(TypeError):
                versions.satisfies(*args)

    def test_r17_total_order(self):
        """last line of SPEC.md: sorting with compare is a total order"""
        pool = ["0.0.0", "0.0.1", "0.1.0", "1.0.0-0", "1.0.0-2", "1.0.0-10", "1.0.0-a", "1.0.0-a.1",
                "1.0.0-alpha", "1.0.0-alpha.beta", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0", "1.2.10", "1.10.2", "2.0.0"]
        key = functools.cmp_to_key(versions.compare)
        rng = random.Random(7)
        for _ in range(20):
            shuffled = pool[:]
            rng.shuffle(shuffled)
            with self.subTest(order=shuffled[:4]):
                self.assertEqual(sorted(shuffled, key=key), pool)
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
    global versions
    workspace = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    sys.path.insert(0, str(workspace))
    total = len(unittest.defaultTestLoader.getTestCaseNames(Rules))
    try:
        versions = importlib.import_module("versions")
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
