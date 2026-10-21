"""Reference solution for the week2 `versions` task (never copied into a workspace)."""

from __future__ import annotations

import re

_ID = r"[0-9A-Za-z-]+"
_NUM = r"0|[1-9][0-9]*"
_VERSION = re.compile(rf"({_NUM})\.({_NUM})\.({_NUM})(?:-({_ID}(?:\.{_ID})*))?(?:\+({_ID}(?:\.{_ID})*))?", re.ASCII)
_PARTIAL = re.compile(rf"(?:({_NUM})|[xX*])(?:\.(?:({_NUM})|[xX*]))?(?:\.(?:({_NUM})|[xX*]))?", re.ASCII)
_OP = re.compile(r"(>=|<=|>|<|=|~|\^)?\s*(\S*)")


def _check(text: object) -> str:
    if not isinstance(text, str):
        raise TypeError(f"expected str, got {type(text).__name__}")
    return text


def _pre(raw: str | None) -> tuple:
    if raw is None:
        return ()
    out: list[int | str] = []
    for part in raw.split("."):
        if part.isdigit():
            if len(part) > 1 and part[0] == "0":
                raise ValueError(f"numeric prerelease identifier with a leading zero: {part!r}")
            out.append(int(part))
        else:
            out.append(part)
    return tuple(out)


def _full(text: str) -> tuple:
    m = _VERSION.fullmatch(text)
    if not m:
        raise ValueError(f"invalid version: {text!r}")
    build = tuple(m.group(5).split(".")) if m.group(5) else ()
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), _pre(m.group(4)), build)


def parse(text: str) -> tuple:
    s = _check(text).strip()
    if s[:1] in ("v", "="):
        s = s[1:]
    return _full(s)


def _cmp_pre(a: tuple, b: tuple) -> int:
    if a == b:
        return 0
    if not a:
        return 1
    if not b:
        return -1
    for x, y in zip(a, b):
        if x == y:
            continue
        if isinstance(x, int) and isinstance(y, int):
            return -1 if x < y else 1
        if isinstance(x, int):
            return -1
        if isinstance(y, int):
            return 1
        return -1 if x < y else 1
    return -1 if len(a) < len(b) else 1


def _cmp(a: tuple, b: tuple) -> int:
    if a[:3] != b[:3]:
        return -1 if a[:3] < b[:3] else 1
    return _cmp_pre(a[3], b[3])


def compare(a: str, b: str) -> int:
    return _cmp(parse(a), parse(b))


# A comparator is (op, version tuple) with op in > >= < <=; "any" sets are empty lists.
Comparator = tuple[str, tuple]


def _partial(text: str) -> tuple[list[int], tuple]:
    """Given parts (up to the first wildcard) and the prerelease, for range versions."""
    m = _VERSION.fullmatch(text)
    if m:
        v = _full(text)
        return [v[0], v[1], v[2]], v[3]
    m = _PARTIAL.fullmatch(text)
    if not m:
        raise ValueError(f"invalid version in range: {text!r}")
    parts: list[int] = []
    for g in m.groups():
        if g is None:
            break
        parts.append(int(g))
    # a wildcard followed by a number ("1.x.3") is not a partial version
    raw = text.split(".")
    for i, piece in enumerate(raw):
        if piece in ("x", "X", "*") and any(p not in ("x", "X", "*") for p in raw[i + 1:]):
            raise ValueError(f"invalid version in range: {text!r}")
    return parts, ()


def _v(parts: list[int], pre: tuple = ()) -> tuple:
    p = parts + [0] * (3 - len(parts))
    return (p[0], p[1], p[2], pre, ())


def _bump(parts: list[int]) -> tuple:
    """The version just above the span of a partial (non-empty) version."""
    p = list(parts)
    p[-1] += 1
    return _v(p)


def _span(parts: list[int], pre: tuple) -> list[Comparator]:
    if not parts:
        return []
    if len(parts) == 3:
        return [(">=", _v(parts, pre)), ("<=", _v(parts, pre))]
    return [(">=", _v(parts)), ("<", _bump(parts))]


def _comparator(op: str, text: str) -> list[Comparator]:
    parts, pre = _partial(text)
    full = len(parts) == 3
    if op in ("", "="):
        return _span(parts, pre)
    if op == "~":
        if not parts:
            return []
        upper = _bump(parts[:2]) if len(parts) >= 2 else _bump(parts[:1])
        return [(">=", _v(parts, pre)), ("<", upper)]
    if op == "^":
        if not parts:
            return []
        idx = next((i for i, n in enumerate(parts) if n != 0), len(parts) - 1)
        return [(">=", _v(parts, pre)), ("<", _bump(parts[: idx + 1]))]
    if not parts:
        return [] if op in (">=", "<=") else [("<", (0, 0, 0, (0,), ()))]  # >* / <* match nothing
    if full:
        return [(op, _v(parts, pre))]
    if op == ">=":
        return [(">=", _v(parts))]
    if op == ">":
        return [(">=", _bump(parts))]
    if op == "<":
        return [("<", _v(parts))]
    return [("<", _bump(parts))]  # <=


def _hyphen(a: str, b: str) -> list[Comparator]:
    pa, prea = _partial(a)
    pb, preb = _partial(b)
    out: list[Comparator] = [(">=", _v(pa, prea))] if pa else []
    if len(pb) == 3:
        out.append(("<=", _v(pb, preb)))
    elif pb:
        out.append(("<", _bump(pb)))
    return out


def _set(text: str) -> list[Comparator]:
    tokens = text.split()
    if not tokens:
        return []
    if "-" in tokens:
        if len(tokens) != 3 or tokens[1] != "-" or tokens[0][:1] in "<>=~^" or tokens[2][:1] in "<>=~^":
            raise ValueError(f"invalid hyphen range: {text!r}")
        return _hyphen(tokens[0], tokens[2])
    # glue an operator token to the version after it (">= 1.2.3")
    glued: list[str] = []
    for tok in tokens:
        if glued and glued[-1] in (">=", "<=", ">", "<", "=", "~", "^"):
            glued[-1] += tok
        else:
            glued.append(tok)
    out: list[Comparator] = []
    for tok in glued:
        m = re.fullmatch(r"(>=|<=|>|<|=|~|\^)?([0-9A-Za-z.*+-]+)", tok)
        if not m:
            raise ValueError(f"invalid comparator: {tok!r}")
        out += _comparator(m.group(1) or "", m.group(2))
    return out


def _range(text: str) -> list[list[Comparator]]:
    return [_set(part) for part in _check(text).strip().split("||")]


def _holds(v: tuple, c: Comparator) -> bool:
    r = _cmp(v, c[1])
    return {">": r > 0, ">=": r >= 0, "<": r < 0, "<=": r <= 0}[c[0]]


def _in_set(v: tuple, cs: list[Comparator]) -> bool:
    if not all(_holds(v, c) for c in cs):
        return False
    if v[3]:
        return any(c[1][3] and c[1][:3] == v[:3] for c in cs)
    return True


def satisfies(version: str, range_: str) -> bool:
    v = parse(_check(version))
    return any(_in_set(v, cs) for cs in _range(range_))


def max_satisfying(versions: list[str], range_: str) -> str | None:
    sets = _range(range_)
    best: tuple | None = None
    best_text: str | None = None
    for text in versions:
        v = parse(text)
        if any(_in_set(v, cs) for cs in sets) and (best is None or _cmp(v, best) > 0):
            best, best_text = v, text
    return best_text
