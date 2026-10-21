"""Parse, compare and match version strings. See SPEC.md."""


def parse(text: str) -> tuple:
    raise NotImplementedError


def compare(a: str, b: str) -> int:
    raise NotImplementedError


def satisfies(version: str, range_: str) -> bool:
    raise NotImplementedError


def max_satisfying(versions: list[str], range_: str) -> str | None:
    raise NotImplementedError
