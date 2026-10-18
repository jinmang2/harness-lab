"""Parse and format byte sizes. See SPEC.md."""


def parse(text: str) -> int:
    raise NotImplementedError


def format(size: int, *, binary: bool = True, precision: int = 1) -> str:  # noqa: A001 - the spec's name
    raise NotImplementedError
