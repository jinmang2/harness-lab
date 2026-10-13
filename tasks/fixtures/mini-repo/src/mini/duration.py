import re

_UNITS = {"h": 3600, "m": 60, "s": 1}
_PART = re.compile(r"(\d+)([hms])")


def parse(text: str) -> int:
    """Return seconds for strings like '1h30m'."""
    parts = _PART.findall(text)
    if not parts or "".join(n + u for n, u in parts) != text:
        raise ValueError(f"bad duration: {text!r}")
    return sum(int(n) * _UNITS[u] for n, u in parts)


def fmt(seconds: int) -> str:
    """Inverse of parse."""
    out = []
    for unit, size in _UNITS.items():
        value, seconds = divmod(seconds, size)
        if value:
            out.append(f"{value}{unit}")
    return "".join(out) or "0s"
