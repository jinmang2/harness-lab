"""Reference solution for tasks/fixtures/week2-durations (proves the acceptance suite is satisfiable)."""

import re
from decimal import Decimal

_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}
_ORDER = "dhms"
_COMPACT = re.compile(r"(?:\d+(?:\.\d+)?[dhms]\s*)+", re.IGNORECASE)
_PART = re.compile(r"(\d+(?:\.\d+)?)([dhms])", re.IGNORECASE)
_ISO = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")


def parse(text: str) -> int:
    if not isinstance(text, str):
        raise TypeError("text must be str")
    s = text.strip()
    sign = 1
    if s.startswith("-"):
        sign, s = -1, s[1:]
    if not s or not (s[0].isdigit() or s[0] == "P"):
        raise ValueError(f"invalid duration: {text!r}")
    if s.isdigit():
        return sign * int(s)
    if s.startswith("P"):
        m = _ISO.fullmatch(s)
        if not m or s in ("P", "PT") or s.endswith("T"):
            raise ValueError(f"invalid duration: {text!r}")
        d, h, mi, sec = (int(g or 0) for g in m.groups())
        return sign * (d * 86400 + h * 3600 + mi * 60 + sec)
    if not _COMPACT.fullmatch(s):
        raise ValueError(f"invalid duration: {text!r}")
    total, last = Decimal(0), -1
    for value, unit in _PART.findall(s):
        index = _ORDER.index(unit.lower())
        if index <= last:
            raise ValueError(f"units out of order or repeated: {text!r}")
        last = index
        total += Decimal(value) * _UNITS[unit.lower()]
    if total != total.to_integral_value():
        raise ValueError(f"not a whole number of seconds: {text!r}")
    return sign * int(total)


def format(seconds: int, *, iso: bool = False) -> str:  # noqa: A001
    if iso and seconds < 0:
        raise ValueError("ISO form has no negative spans")
    sign, n = ("-" if seconds < 0 else ""), abs(seconds)
    d, rest = divmod(n, 86400)
    h, rest = divmod(rest, 3600)
    m, s = divmod(rest, 60)
    if iso:
        if n == 0:
            return "PT0S"
        time = "".join(f"{v}{u}" for v, u in ((h, "H"), (m, "M"), (s, "S")) if v)
        return "P" + (f"{d}D" if d else "") + ("T" + time if time else "")
    if n == 0:
        return "0s"
    return sign + "".join(f"{v}{u}" for v, u in ((d, "d"), (h, "h"), (m, "m"), (s, "s")) if v)
