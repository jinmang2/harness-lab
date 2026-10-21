"""week2 differential check: a workspace's module against the reference on seeded random inputs.

    python3 -I week2_fuzz.py TASK WORKSPACE [N]   # TASK: durations | sizes | versions

The acceptance suites have one test per SPEC rule, so every harness scores full marks and the
suite stops telling them apart. This feeds the same few thousand generated inputs to the
reference solution (`tests/data/week2_*_reference`) and to `WORKSPACE/<TASK>.py`, and counts the
inputs whose outcome differs: the returned value, or the exception class (`ValueError`,
`TypeError`). It prints one JSON line (`{"total", "agree", "by_fn", "samples"}`) and exits 0.

Inputs the spec leaves open are not generated, so a disagreement is a spec violation, not a
reading: non-ASCII digits, `"1."` / `".5"` / `"1_0"` and a space between number and unit in
durations, a sign before an ISO duration, a non-`int` `format` argument in durations, a space
after `~` / `^`, and an operator or hyphen bound on a bare wildcard (`>x`, `x - 1.2`) in versions.
Grading material: never copied into a workspace (ADR-0015).
"""

from __future__ import annotations

import importlib.util
import json
import random
import signal
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

REFERENCES = Path(__file__).resolve().parents[2] / "tests" / "data"
REFERENCE = {"durations": REFERENCES / "week2_reference" / "durations.py", "sizes": REFERENCES / "week2_sizes_reference" / "sizes.py",
             "versions": REFERENCES / "week2_versions_reference" / "versions.py"}
SAMPLES = 5
Case = tuple[str, tuple[Any, ...], dict[str, Any]]
R = random.Random(20261019)


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _timeout(*_: object) -> None:
    raise TimeoutError


def _outcome(fn: Callable[..., Any], args: tuple[Any, ...], kw: dict[str, Any]) -> tuple[str, str]:
    signal.alarm(2)
    try:
        return ("ok", repr(fn(*args, **kw)))
    except (ValueError, TypeError) as e:
        return ("err", type(e).__name__)
    except Exception as e:  # noqa: BLE001 - a crash or a hang is an outcome too
        return ("crash", type(e).__name__)
    finally:
        signal.alarm(0)


def _ws() -> str:
    return R.choice(["", "", "", " ", "  ", "\t"])


# durations
def _dur_num() -> str:
    k = R.random()
    if k < 0.6:
        return str(R.randint(0, 120))
    if k < 0.75:
        return R.choice(["1.5", "0.5", "1.01", "2.25", "0.25", "1.50", "0.1"])
    return R.choice(["1e2", "", "1,5"])


def _dur_text() -> str:
    k = R.random()
    if k < 0.55:
        units = R.sample("dhms", R.randint(1, 4))
        if R.random() < 0.7:
            units.sort(key="dhms".index)
        if R.random() < 0.1:
            units.append(units[-1])
        parts = [_dur_num() + (u.upper() if R.random() < 0.2 else u) for u in units]
        if R.random() < 0.1:
            parts.append(str(R.randint(1, 9)))
        s = _ws().join(parts) if R.random() < 0.5 else "".join(p + _ws() for p in parts)
        if R.random() < 0.05:
            s = s.replace(parts[-1], "-" + parts[-1])
        return _ws() + R.choice(["", "", "", "-", "+", "--", " -"]) + s + _ws()
    if k < 0.85:
        s = "P"
        if R.random() < 0.6:
            s += f"{R.randint(0, 5)}D"
        if R.random() < 0.8:
            s += "T"
            for u in "HMS":
                if R.random() < 0.5:
                    s += R.choice([str(R.randint(0, 90)), "1.5", "0"]) + u
        if R.random() < 0.1:
            s = s.lower()
        return _ws() + s + _ws()
    return R.choice(["", " ", "h", "90", "-90", "0", "abc", "1h 30", "P1H", "PT", "1d-1h", "1h30m10", "3600s", "+5"])


def _durations(n: int) -> Iterator[Case]:
    for _ in range(n):
        yield ("parse", (_dur_text(),), {})
    for _ in range(n // 2):
        v = R.choice([R.randint(-10, 10), R.randint(-200000, 200000), R.randint(0, 10**9), R.choice([0, 60, 3600, 86400, 86399, -86400])])
        yield ("format", (v,), {"iso": R.random() < 0.5})
    for bad in (None, 5, b"1h"):
        yield ("parse", (bad,), {})


# sizes
UNITS = ["B", "KB", "MB", "GB", "TB", "KiB", "MiB", "GiB", "TiB", "kb", "KIB", "mb", "kB", "Kib", "PB", "b"]


def _size_num() -> str:
    k = R.random()
    if k < 0.55:
        return str(R.randint(0, 5000))
    if k < 0.75:
        return R.choice(["1.5", "0.5", "0.1", "1.0001", "2.25", "0.001", "007", "1.", "1.25"])
    return R.choice(["1_000", "_1", "1_", "1__0", "1,000", "1e3", "١", "-1", "+1", "1_000.5", " "])


def _sizes(n: int) -> Iterator[Case]:
    for _ in range(n):
        if R.random() < 0.85:
            text = _ws() + _size_num() + R.choice(["", " ", " ", "  "]) + R.choice(UNITS) + _ws()
        else:
            text = R.choice(["", " ", "KiB", "512", "007", "1. KiB", "0", "1 KiB B", "1KiB", "1.5KiB"])
        yield ("parse", (text,), {})
    for _ in range(n // 2):
        base = R.choice([1, 1000, 1024, 1000**2, 1024**2, 1000**3, 1024**3, 1024**4, 1000**4])
        v = max(0, int(base * R.choice([1, 1.5, 0.999, 1023.95, 999.95, 2.25, 2.75, R.uniform(0, 2000)])) + R.randint(-3, 3))
        yield ("format", (v,), {"binary": R.random() < 0.6, "precision": R.choice([0, 1, 1, 2, 3])})
    for bad in ((-1,), (True,), (1.5,), ("1",)):
        yield ("format", bad, {})
    yield ("format", (10,), {"precision": -1})


# versions
def _num() -> str:
    if R.random() < 0.1:
        return R.choice(["0", "1", "2", "3", "10", "9", str(R.randint(0, 20)), "01", "00"])
    return str(R.choice([0, 1, 1, 2, 3, 9, 10, 11]))


def _ident() -> str:
    if R.random() < 0.15:
        return R.choice(["alpha", "beta", "rc", "0", "1", "2", "11", "0a", "x-y", "01", "", "Alpha", "a.b"])
    return R.choice(["alpha", "beta", "rc", "0", "1", "2", "11", "0a"])


def _version(prefix: bool = True, valid_bias: float = 0.85) -> str:
    v = ".".join(_num() for _ in range(3 if R.random() < valid_bias else R.choice([2, 4])))
    if R.random() < 0.4:
        v += "-" + ".".join(_ident() for _ in range(R.randint(1, 3)))
    if R.random() < 0.2:
        v += "+" + ".".join(R.choice(["build", "05", "001", "sha-1", "x"]) for _ in range(R.randint(1, 2)))
    if prefix and R.random() < 0.2:
        v = R.choice(["v", "=", "V", "vv", " v"]) + v
    if prefix and R.random() < 0.2:
        v = _ws() + v + _ws()
    return v


def _partial(bound: bool = False) -> str:
    """A range version; with `bound` (after an operator or in a hyphen range) never a bare wildcard."""
    if R.random() < 0.5:
        return _version(prefix=False, valid_bias=0.95)
    parts = [R.choice(["0", "1", "2", "x", "X", "*", "3"]) for _ in range(R.randint(1, 3))]
    if bound and parts[0] in "xX*":
        parts[0] = R.choice(["0", "1", "2", "3"])
    return ".".join(parts) + ("-beta" if R.random() < 0.05 else "")


def _comparator() -> str:
    ops = ["", "", ">", ">=", "<", "<=", "=", "~", "^", "=>", "~>"] if R.random() < 0.1 else ["", ">", ">=", "<", "<=", "=", "~", "^"]
    op = R.choice(ops)
    space = " " if R.random() < 0.15 and op not in ("~", "^", "~>") else ""
    return op + space + _partial(bound=bool(op))


def _set() -> str:
    if R.random() < 0.15:
        return (">=" if R.random() < 0.1 else "") + _partial(bound=True) + " - " + _partial(bound=True)
    return " ".join(_comparator() for _ in range(R.randint(1, 2)))


def _range() -> str:
    if R.random() < 0.05:
        return R.choice(["", " ", "*", "||", ">=", "1.x.3", "x"])
    return (" || " if R.random() < 0.8 else "||").join(_set() for _ in range(R.randint(1, 2)))


POOL = ["1.2.3", "1.2.4", "1.3.0", "2.0.0", "0.2.3", "0.2.9", "0.3.0", "0.0.3", "0.0.4", "1.0.0", "1.0.0-rc.1", "1.2.3-alpha.7",
        "1.2.3-beta.4", "1.2.4-beta.1", "1.2.3-alpha.3", "3.4.5-alpha.9", "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-beta.11", "0.0.0",
        "2.3.4", "2.4.0", "1.1.9", "0.9.0", "1.2.0", "10.0.0"]


def _versions(n: int) -> Iterator[Case]:
    for _ in range(n):
        yield ("parse", (_version(),), {})
    for _ in range(n):
        yield ("compare", (_version(prefix=False, valid_bias=0.97), _version(prefix=False, valid_bias=0.97)), {})
    for _ in range(n * 2):
        v = R.choice(POOL) if R.random() < 0.6 else _version(prefix=False, valid_bias=1)
        yield ("satisfies", (v, _range()), {})
    for _ in range(n // 2):
        yield ("max_satisfying", (R.sample(POOL, R.randint(0, 6)), _range()), {})
    yield ("parse", (None,), {})
    yield ("parse", (1,), {})
    yield ("satisfies", ("1.2.3", None), {})
    yield ("max_satisfying", (["1.2.3", "bad"], "*"), {})


CASES: dict[str, Callable[[int], Iterator[Case]]] = {"durations": _durations, "sizes": _sizes, "versions": _versions}


def run(task: str, workspace: Path, n: int = 2000) -> dict[str, Any]:
    signal.signal(signal.SIGALRM, _timeout)
    ref = _load("week2_fuzz_reference", REFERENCE[task])
    try:
        cand = _load("week2_fuzz_candidate", workspace / f"{task}.py")
    except Exception as e:  # noqa: BLE001
        return {"total": 0, "agree": 0, "by_fn": {}, "samples": [], "error": repr(e)}
    total = agree = 0
    by_fn: dict[str, list[int]] = {}
    samples = []
    for fn, args, kw in CASES[task](n):
        want = _outcome(getattr(ref, fn), args, kw)
        got = _outcome(getattr(cand, fn), args, kw) if hasattr(cand, fn) else ("crash", "missing")
        same = want == got
        total += 1
        agree += same
        stat = by_fn.setdefault(fn, [0, 0])
        stat[0] += same
        stat[1] += 1
        if not same and len(samples) < SAMPLES:
            samples.append({"call": f"{fn}{args!r}"[:160] + (f" {kw}" if kw else ""), "want": want, "got": got})
    return {"total": total, "agree": agree, "by_fn": by_fn, "samples": samples}


if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1], Path(sys.argv[2]).resolve(), int(sys.argv[3]) if len(sys.argv) > 3 else 2000), ensure_ascii=False))
