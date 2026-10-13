"""Steering: messages sent while a turn runs (DeepSeek Harness `agent.steer`, inbox `next-step`).

The chat session puts steered text in an `Inbox`; this middleware appends it as an
ordinary user message before the next model call, and keeps the turn open while
any remain, as DSH's agent loop does. No wrapper text is added.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import hook_config
from langchain_core.messages import HumanMessage


class Inbox:
    """Thread-safe `next-step` list; `on_claim` reports each message as it enters the turn."""

    def __init__(self, on_claim: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._items: list[dict[str, Any]] = []
        self.on_claim = on_claim

    def put(self, item: dict[str, Any]) -> None:
        with self._lock:
            self._items.append(item)

    def remove(self, item_id: str) -> bool:
        with self._lock:
            before = len(self._items)
            self._items = [i for i in self._items if i.get("id") != item_id]
            return len(self._items) != before

    def pending(self) -> bool:
        with self._lock:
            return bool(self._items)

    def claim(self) -> list[dict[str, Any]]:
        with self._lock:
            items, self._items = self._items, []
        for item in items:
            if self.on_claim:
                self.on_claim(item)
        return items

    def drain(self) -> list[dict[str, Any]]:
        """Unclaimed items when the turn ends anyway (error, stop): the caller requeues them."""
        with self._lock:
            items, self._items = self._items, []
        return items


class InboxMiddleware(AgentMiddleware):
    def __init__(self, inbox: Inbox, to_message: Callable[[dict[str, Any]], Any],
                 extra: Callable[[], dict[str, Any]] | None = None) -> None:
        super().__init__()
        self.inbox = inbox
        self.to_message = to_message
        self.extra = extra  # state updates that come with a human message (e.g. goal authority)

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        items = self.inbox.claim()
        if not items:
            return None
        return {"messages": [self.to_message(i) for i in items], **(self.extra() if self.extra else {})}

    @hook_config(can_jump_to=["model"])
    def after_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        last = (state.get("messages") or [None])[-1]
        if last is not None and not getattr(last, "tool_calls", None) and self.inbox.pending():
            return {"jump_to": "model"}  # the turn does not end while steered messages wait
        return None


def text_message(item: dict[str, Any]) -> HumanMessage:
    return HumanMessage(item.get("content") or item.get("text") or "")
