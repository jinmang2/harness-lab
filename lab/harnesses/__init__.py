"""Harness registry. One harness = one composition, the lab's version of a DSH preset.

Add a harness by decorating a builder in any module imported at the bottom:

    @harness("my-variant", "what changes and why")
    def build(ctx: BuildContext):
        return create_agent(ctx.model, ...)
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel


@dataclass
class BuildContext:
    model: BaseChatModel
    model_name: str
    workdir: Path
    hooks: list[dict[str, Any]] = field(default_factory=list)
    # Required for interrupts (HITL) and multi-turn chat; builders pass it through.
    checkpointer: Any = None
    # "ask": pause for approval before shell commands and file writes (DSH's approval
    # policy `ask`); "auto": never. Builders apply it with common.approvals/interrupts.
    approval: str = "auto"
    # True only in the chat UI, where a person can answer ask_user_question and
    # review plans; batch runs answer neither, like DSH headless.
    interactive: bool = False


@dataclass(frozen=True)
class Harness:
    name: str
    description: str
    build: Callable[[BuildContext], Any]


REGISTRY: dict[str, Harness] = {}


def harness(name: str, description: str) -> Callable[[Callable[[BuildContext], Any]], Callable[[BuildContext], Any]]:
    def register(build: Callable[[BuildContext], Any]) -> Callable[[BuildContext], Any]:
        if name in REGISTRY:
            raise ValueError(f"duplicate harness {name!r}")
        REGISTRY[name] = Harness(name, description, build)
        return build

    return register


def get(name: str) -> Harness:
    try:
        return REGISTRY[name]
    except KeyError:
        raise SystemExit(f"unknown harness {name!r}; known: {', '.join(sorted(REGISTRY))}") from None


from lab.harnesses import advanced, experiments, minimal, standard  # noqa: E402,F401  (registration side effects)
