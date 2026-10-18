"""Reference sizes.py for the week2 acceptance suite (kept outside every workspace)."""

import re
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction

_UNITS = {"B": 1, "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4,
          "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4}
_TEXT = re.compile(r"(?P<int>[0-9]+(?:_[0-9]+)*)(?:\.(?P<frac>[0-9]+))?(?: ?(?P<unit>[A-Za-z]+))?")


def parse(text: str) -> int:
    if not isinstance(text, str):
        raise TypeError("text must be a str")
    m = _TEXT.fullmatch(text.strip())
    if not m:
        raise ValueError(f"invalid size: {text!r}")
    unit = m.group("unit")
    if unit is None and m.group("frac") is not None:
        raise ValueError(f"a decimal needs a unit: {text!r}")
    if unit is not None and unit not in _UNITS:
        raise ValueError(f"unknown unit: {unit!r}")
    value = Fraction(m.group("int").replace("_", "")) + (Fraction(int(m.group("frac")), 10 ** len(m.group("frac"))) if m.group("frac") else 0)
    total = value * _UNITS[unit or "B"]
    if total.denominator != 1:
        raise ValueError(f"not a whole number of bytes: {text!r}")
    return int(total)


def format(size: int, *, binary: bool = True, precision: int = 1) -> str:  # noqa: A001
    if not isinstance(size, int) or isinstance(size, bool):
        raise TypeError("size must be an int")
    if size < 0 or precision < 0:
        raise ValueError("size and precision must be non-negative")
    base = 1024 if binary else 1000
    names = ["B", "KiB", "MiB", "GiB", "TiB"] if binary else ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while i < len(names) - 1 and size >= base ** (i + 1):
        i += 1
    if i == 0:
        return f"{size} B"
    quantum = Decimal(1).scaleb(-precision)
    value = (Decimal(size) / Decimal(base**i)).quantize(quantum, rounding=ROUND_HALF_EVEN)
    if value >= base and i < len(names) - 1:
        i += 1
        value = (Decimal(size) / Decimal(base**i)).quantize(quantum, rounding=ROUND_HALF_EVEN)
    text = f"{value:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text} {names[i]}"
