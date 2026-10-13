"""Normalized trace events shared by every engine (lab and DeepSeek Harness).

Each run writes `trace.jsonl`: one JSON object per line, `kind` is one of

- `run`   : header (engine, harness, task, model, cwd)
- `llm`   : one model call (tokens, latency, tool calls it requested, request size)
- `tool`  : one tool execution (name, args, result size, latency, error)
- `hook`  : a middleware hook fired (HookLogger only)
- `interrupt`: a human-in-the-loop pause and the decision applied
- `end`   : footer (status, wall time, final answer)

Token fields are DISJOINT so engines compare cleanly:

    input_uncached + cache_read + cache_write = everything the provider billed as input

LangChain reports `input_tokens` as the total (cache included); DeepSeek Harness
reports `inputTokens` as uncached only. Both are converted to the form above.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

TOKEN_FIELDS = ("input_uncached", "cache_read", "cache_write", "output", "reasoning")


def write_events(path: Path, events: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for event in events:
            fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")


def read_events(path: Path) -> list[dict[str, Any]]:
    events = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                events.append(json.loads(line))
    return events


def chronological(middle: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order llm/tool/hook/interrupt events by their `t` stamp (stable; untimed lists stay as-is)."""
    if middle and all("t" in e for e in middle):
        return sorted(middle, key=lambda e: e["t"])
    return middle


def summarize(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Collapse one run's events into the metrics the week reports compare."""
    header = next((e for e in events if e["kind"] == "run"), {})
    footer = next((e for e in reversed(events) if e["kind"] == "end"), {})
    llm = [e for e in events if e["kind"] == "llm"]
    tools = [e for e in events if e["kind"] == "tool"]

    totals = {f: sum(int(e.get(f) or 0) for e in llm) for f in TOKEN_FIELDS}
    billed_input = totals["input_uncached"] + totals["cache_read"] + totals["cache_write"]
    first = llm[0] if llm else {}
    return {
        "run_id": header.get("run_id"),
        "batch": header.get("batch"),
        "engine": header.get("engine"),
        "harness": header.get("harness"),
        "task": header.get("task"),
        "repeat": header.get("repeat"),
        "model": header.get("model"),
        "status": footer.get("status", "unknown"),
        "error": footer.get("error"),
        "wall_ms": footer.get("wall_ms"),
        # Agent time (DSH: turn start→end in its session log; lab: same as wall_ms). Process boot/exit excluded.
        "turn_ms": footer.get("turn_ms") if footer.get("turn_ms") is not None else footer.get("wall_ms"),
        "llm_calls": len(llm),
        "tool_calls": len(tools),
        "tool_errors": sum(1 for t in tools if t.get("error")),
        "interrupts": sum(len(e.get("actions") or []) for e in events if e["kind"] == "interrupt"),
        "tools_used": dict(Counter(t["name"] for t in tools)),
        "tool_sequence": [t["name"] for t in tools],
        **totals,
        "input_billed": billed_input,
        "total_tokens": billed_input + totals["output"],
        "first_request": {
            "system_chars": first.get("system_chars"),
            "tool_count": first.get("tool_count"),
            "tools": first.get("tools"),
            "input_billed": (first.get("input_uncached") or 0) + (first.get("cache_read") or 0) + (first.get("cache_write") or 0)
            if first
            else None,
        },
        "llm_ms": sum(int(e.get("latency_ms") or 0) for e in llm),
        "tool_ms": sum(int(e.get("latency_ms") or 0) for e in tools),
        "final": footer.get("final"),
    }
