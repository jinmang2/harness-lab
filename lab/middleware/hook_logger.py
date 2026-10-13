"""Record the order in which middleware hooks fire.

Put one `HookLogger` first and one last in a middleware list to see how the stack
nests: `before_*` run in list order, `after_*` in reverse, `wrap_*` like onions.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware


class HookLogger(AgentMiddleware):
    def __init__(self, label: str, sink: list[dict[str, Any]]) -> None:
        super().__init__()
        self.label = label
        self.sink = sink

    @property
    def name(self) -> str:
        return f"HookLogger[{self.label}]"

    def _log(self, hook: str, **extra: Any) -> None:
        self.sink.append({"kind": "hook", "label": self.label, "hook": hook, "t": time.time(), **extra})

    def before_agent(self, state: Any, runtime: Any) -> None:
        self._log("before_agent", messages=len(state.get("messages", [])))

    def before_model(self, state: Any, runtime: Any) -> None:
        self._log("before_model", messages=len(state.get("messages", [])))

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        self._log("wrap_model_call:enter", tools=len(request.tools or []))
        response = handler(request)
        self._log("wrap_model_call:exit")
        return response

    def after_model(self, state: Any, runtime: Any) -> None:
        self._log("after_model", messages=len(state.get("messages", [])))

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        self._log("wrap_tool_call:enter", tool=request.tool_call["name"])
        result = handler(request)
        self._log("wrap_tool_call:exit", tool=request.tool_call["name"])
        return result

    def after_agent(self, state: Any, runtime: Any) -> None:
        self._log("after_agent", messages=len(state.get("messages", [])))
