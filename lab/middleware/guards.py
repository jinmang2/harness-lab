"""Guard middleware modeled on DeepSeek Harness plugins."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage


def _with_text(message: Any, text: str) -> Any:
    if isinstance(message, ToolMessage):
        return message.model_copy(update={"content": text})
    return message


class RepeatToolCallGuard(AgentMiddleware):
    """Append a reminder when the model repeats the identical tool call.

    Mirrors dsh `repeat-tool-reminder`: the call still runs, but the result tells
    the model it is looping so it can change approach.
    """

    def __init__(self, threshold: int = 3) -> None:
        super().__init__()
        self.threshold = threshold
        self._last: str | None = None
        self._count = 0

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        call = request.tool_call
        key = call["name"] + json.dumps(call.get("args"), sort_keys=True, ensure_ascii=False)
        self._count = self._count + 1 if key == self._last else 1
        self._last = key
        result = handler(request)
        if self._count >= self.threshold and isinstance(result, ToolMessage) and isinstance(result.content, str):
            reminder = (
                f"\n\n[reminder] You have made this exact `{call['name']}` call {self._count} times in a row. "
                "Repeating it will not change the result; try a different approach."
            )
            return _with_text(result, result.content + reminder)
        return result


class ToolResultPruner(AgentMiddleware):
    """Keep the head and tail of oversized tool results.

    Mirrors dsh `tool-result-pruner` defaults (threshold 8192, head 4096, tail 1024).
    """

    def __init__(self, threshold_chars: int = 8192, head_chars: int = 4096, tail_chars: int = 1024) -> None:
        super().__init__()
        self.threshold_chars = threshold_chars
        self.head_chars = head_chars
        self.tail_chars = tail_chars

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        result = handler(request)
        if not (isinstance(result, ToolMessage) and isinstance(result.content, str)):
            return result
        text = result.content
        if len(text) <= self.threshold_chars:
            return result
        omitted = len(text) - self.head_chars - self.tail_chars
        pruned = f"{text[: self.head_chars]}\n\n[... {omitted} characters omitted ...]\n\n{text[-self.tail_chars :]}"
        return _with_text(result, pruned)
