"""Parse and format human-written time spans. See SPEC.md."""


def parse(text: str) -> int:
    raise NotImplementedError


def format(seconds: int, *, iso: bool = False) -> str:  # noqa: A001 - name fixed by SPEC.md
    raise NotImplementedError
