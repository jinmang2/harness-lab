"""LangChain callback handler that records the normalized trace (see `lab.trace`).

Callbacks see every model and tool call, including ones inside subagents, so this is
the lab's equivalent of DeepSeek Harness's session log. Langfuse/LangSmith can run
alongside it (see `extra_callbacks`).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _child(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Which loop child a run belongs to (lab/middleware/ralph.py `_run_child` puts it in the metadata)."""
    meta = metadata or {}
    if not meta.get("child_thread"):
        return {}
    return {"child": meta["child_thread"], "child_label": meta.get("child_label"), "depth": meta.get("delegation_depth")}


def _content_chars(message: BaseMessage) -> int:
    content = message.content
    return len(content) if isinstance(content, str) else len(json.dumps(content, ensure_ascii=False))


class TraceRecorder(BaseCallbackHandler):
    """Collects `llm` and `tool` events; `run`/`end` are added by the runner."""

    raise_error = False

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._llm: dict[UUID, dict[str, Any]] = {}
        self._tool: dict[UUID, dict[str, Any]] = {}
        self._step = 0

    # ── model calls ────────────────────────────────────────────────────────

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        batch = messages[0] if messages else []
        params = kwargs.get("invocation_params") or {}
        tools = params.get("tools") or []
        tool_names = [t.get("function", {}).get("name") or t.get("name") for t in tools if isinstance(t, dict)]
        system = [m for m in batch if m.type == "system"]
        self._step += 1
        self._llm[run_id] = {
            "start": time.perf_counter(),
            "ttft_ms": None,
            "event": {
                "kind": "llm",
                "t": time.time(),
                "step": self._step,
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "messages": len(batch),
                "system_chars": sum(_content_chars(m) for m in system),
                "request_chars": sum(_content_chars(m) for m in batch),
                "tool_count": len(tool_names),
                "tools": tool_names,
                "tool_schema_chars": len(json.dumps(tools, ensure_ascii=False)) if tools else 0,
                **_child(kwargs.get("metadata")),
            },
        }

    def on_llm_new_token(self, token: str, *, run_id: UUID, **kwargs: Any) -> None:
        pending = self._llm.get(run_id)
        if pending is not None and pending["ttft_ms"] is None:
            pending["ttft_ms"] = _ms(pending["start"])

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        pending = self._llm.pop(run_id, None)
        if pending is None:
            return
        event = pending["event"]
        event["latency_ms"] = _ms(pending["start"])
        event["ttft_ms"] = pending["ttft_ms"]
        message = None
        if response.generations and response.generations[0]:
            message = getattr(response.generations[0][0], "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        details = usage.get("input_token_details") or {}
        out_details = usage.get("output_token_details") or {}
        cache_read = int(details.get("cache_read") or 0)
        cache_write = int(details.get("cache_creation") or 0)
        event.update(
            input_uncached=max(int(usage.get("input_tokens") or 0) - cache_read - cache_write, 0),
            cache_read=cache_read,
            cache_write=cache_write,
            output=int(usage.get("output_tokens") or 0),
            reasoning=int(out_details.get("reasoning") or 0),
            requested_tools=[c["name"] for c in (getattr(message, "tool_calls", None) or [])],
            text_chars=_content_chars(message) if message is not None else 0,
        )
        self.events.append(event)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        pending = self._llm.pop(run_id, None)
        if pending is not None:
            event = pending["event"]
            event.update(latency_ms=_ms(pending["start"]), error=repr(error))
            self.events.append(event)

    # ── tool calls ─────────────────────────────────────────────────────────

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self._tool[run_id] = {
            "start": time.perf_counter(),
            "event": {
                "kind": "tool",
                "t": time.time(),
                "run_id": str(run_id),
                "parent_run_id": str(parent_run_id) if parent_run_id else None,
                "name": (serialized or {}).get("name") or kwargs.get("name") or "?",
                "args": inputs if inputs is not None else input_str,
                **_child(kwargs.get("metadata")),
            },
        }

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        pending = self._tool.pop(run_id, None)
        if pending is None:
            return
        update = getattr(output, "update", None)  # langgraph Command, e.g. deepagents `task`
        if isinstance(update, dict):
            output = next((m for m in reversed(update.get("messages") or []) if getattr(m, "type", None) == "tool"), output)
        text = getattr(output, "content", output)
        text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
        event = pending["event"]
        failed = getattr(output, "status", None) == "error"
        event.update(
            latency_ms=_ms(pending["start"]),
            result_chars=len(text),
            result_preview=text[:500],
            error=text[:500] if failed else None,
        )
        self.events.append(event)

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        pending = self._tool.pop(run_id, None)
        if pending is not None:
            event = pending["event"]
            event.update(latency_ms=_ms(pending["start"]), result_chars=0, error=repr(error))
            self.events.append(event)


def extra_callbacks() -> list[BaseCallbackHandler]:
    """Optional third-party tracers. LangSmith needs no code: set LANGSMITH_TRACING=true."""
    handlers: list[BaseCallbackHandler] = []
    if os.environ.get("LANGFUSE_PUBLIC_KEY"):
        try:
            from langfuse.langchain import CallbackHandler
        except ImportError as exc:
            raise SystemExit("LANGFUSE_* is set but langfuse is not installed: `uv sync --extra langfuse`") from exc
        handlers.append(CallbackHandler())
    return handlers
