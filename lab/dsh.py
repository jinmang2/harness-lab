"""Run DeepSeek Harness headless and convert its session log into the lab trace format.

No source build and no Web UI: `lab dsh-install` puts the pinned npm package in
`.dsh-runtime/`, and every run uses an isolated `DSH_HOME` (`.dsh-home/`) so it never
touches `~/.dsh`. Harness compositions are `--patch` overlays in `dsh/patches/`.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lab import ROOT

DSH_VERSION = os.environ.get("DSH_VERSION", "0.1.5-rc.3")
RUNTIME_DIR = ROOT / ".dsh-runtime"
DSH_HOME = ROOT / ".dsh-home"
PATCH_DIR = ROOT / "dsh" / "patches"

# harness name -> patch overlays applied on top of the headless profile, in order.
HARNESSES: dict[str, list[str]] = {
    "standard": ["common.yml"],
    "minimal": ["common.yml", "minimal.yml"],
}


def bin_path() -> Path:
    return RUNTIME_DIR / "node_modules" / ".bin" / "dsh"


def install() -> None:
    if shutil.which("npm") is None:
        raise SystemExit("npm is required (Node.js ^22.19 or >=24).")
    RUNTIME_DIR.mkdir(exist_ok=True)
    package_json = RUNTIME_DIR / "package.json"
    if not package_json.exists():
        package_json.write_text('{"name": "dsh-runtime", "private": true}\n')
    subprocess.run(
        ["npm", "install", "--no-audit", "--no-fund", f"@deepseek-ai/dsh@{DSH_VERSION}"],
        cwd=RUNTIME_DIR,
        check=True,
    )
    print(f"installed @deepseek-ai/dsh@{DSH_VERSION} -> {bin_path()}")


def environment() -> dict[str, str]:
    env = dict(os.environ)
    env["DSH_HOME"] = str(DSH_HOME)
    env["DSH_TELEMETRY_MODE"] = "DISABLED"
    env.setdefault("LAB_MODEL", "deepseek-v4-flash")
    return env


def _log_state() -> dict[Path, tuple[float, int]]:
    root = DSH_HOME / "sessions"
    if not root.is_dir():
        return {}
    return {p: (p.stat().st_mtime, p.stat().st_size) for p in root.rglob("session*.jsonl")}


def _header(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        first = fh.readline()
    try:
        return json.loads(first)
    except json.JSONDecodeError:
        return {}


def _new_logs(before: dict[Path, tuple[float, int]], cwd: Path | None = None) -> list[Path]:
    """Session logs created or appended during this run: the main session first, then subagents.

    Ordered by the session header's `delegationDepth` (0 = main), then creation time.
    `st_ctime` is not creation time on POSIX: the parent keeps writing after a child ends.
    """
    after = _log_state()
    changed = [p for p, state in after.items() if before.get(p) != state]
    if cwd is not None:  # other DSH runs may be going on at the same time (UI + batch)
        changed = [p for p in changed if _header(p).get("cwd") == str(cwd)]

    def key(p: Path) -> tuple[int, float]:
        stat = p.stat()
        return int(_header(p).get("delegationDepth") or 0), getattr(stat, "st_birthtime", stat.st_mtime)

    return sorted(changed, key=key)


def _kill_group(proc: subprocess.Popen, grace_s: float = 3) -> None:
    """End the run's whole process group: SIGTERM, then SIGKILL anything still there after `grace_s`."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return  # leader and every shell it started are already gone
    try:
        proc.wait(timeout=grace_s)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _safe_prompt(prompt: str) -> str:
    """Headless takes the task as argv; a leading '-' would be read as a flag (even after '--')."""
    return " " + prompt if prompt.startswith("-") else prompt


def run(
    prompt: str,
    harness: str,
    workdir: Path,
    timeout_s: int = 1800,
    env: dict[str, str] | None = None,
    on_stderr: Callable[[str], None] | None = None,
    on_start: Callable[[subprocess.Popen], None] | None = None,
) -> dict[str, Any]:
    """Run one headless task. Returns stdout/stderr, exit code, wall time and the session log path.

    `env` adds variables for this run (e.g. LAB_MODEL); `on_stderr` gets stderr lines as
    they arrive (reasoning is streamed there); `on_start` gets the process (to stop it).
    """
    if harness not in HARNESSES:
        raise SystemExit(f"unknown dsh harness {harness!r}; known: {', '.join(HARNESSES)}")
    binary = bin_path()
    if not binary.exists():
        raise SystemExit("DeepSeek Harness is not installed: run `uv run lab dsh-install`.")
    cmd = [str(binary), "--profile", "headless"]
    for patch in HARNESSES[harness]:
        cmd += ["--patch", str(PATCH_DIR / patch)]
    cmd.append(_safe_prompt(prompt))

    DSH_HOME.mkdir(exist_ok=True)
    before = _log_state()
    started = time.time()
    t0 = time.perf_counter()
    # Own process group so a timeout also stops the shells DSH started.
    proc = subprocess.Popen(
        cmd, cwd=workdir, env={**environment(), **(env or {})}, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    out: list[bytes] = []
    err: list[bytes] = []

    def pump(stream: Any, sink: list[bytes], callback: Callable[[str], None] | None) -> None:
        for raw in stream:
            sink.append(raw)
            if callback:
                callback(raw.decode("utf-8", "replace"))

    readers = [threading.Thread(target=pump, args=(proc.stdout, out, None), daemon=True),
               threading.Thread(target=pump, args=(proc.stderr, err, on_stderr), daemon=True)]
    for r in readers:
        r.start()
    try:
        if on_start:
            on_start(proc)
        code = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        err.append(f"\n[lab] timed out after {timeout_s}s".encode())
        code = -1
    finally:  # normal end, timeout, Stop, or this process being terminated: no DSH or shell outlives the run
        _kill_group(proc, grace_s=0 if proc.poll() is not None else 3)
        if proc.poll() is None:
            proc.wait()
    for r in readers:
        r.join(timeout=5)
    stdout, stderr = b"".join(out).decode("utf-8", "replace"), b"".join(err).decode("utf-8", "replace")
    wall_ms = int((time.perf_counter() - t0) * 1000)
    logs = _new_logs(before, Path(workdir).resolve())
    return {
        "exit_code": code,
        "stdout": stdout,
        "stderr": stderr,
        "wall_ms": wall_ms,
        "session_logs": [str(p) for p in logs],
        "started_ms": int(started * 1000),
    }


# ── session log -> normalized events ────────────────────────────────────────


def _text_chars(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(part.get("text", "")) for part in content if isinstance(part, dict))
    return 0


def _tool_names(tools: Any) -> list[str]:
    if isinstance(tools, list):
        names = []
        for t in tools:
            if isinstance(t, dict):
                names.append(t.get("name") or t.get("function", {}).get("name") or "?")
        return names
    if isinstance(tools, dict):
        return list(tools)
    return []


def turn_ms(path: Path) -> int | None:
    """Agent time inside the session: first `turn/start` to last `turn/end` (DSH Web's "Ran for").

    The headless process also spends time booting and shutting down its host (the
    persistent terminal of `minimal` takes seconds to close), which is not the agent's.
    """
    start = end = None
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line) if line.strip() else {}
            if row.get("type") == "turn/start" and start is None:
                start = row.get("time")
            elif row.get("type") == "turn/end":
                end = row.get("time")
    return end - start if isinstance(start, int) and isinstance(end, int) else None


def session_request(path: Path) -> dict[str, Any]:
    """The first system prompt and tool names a session sent (DSH Web's "System prompt" row)."""
    system, tools = "", []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line) if line.strip() else {}
            data = row.get("data") or {}
            if row.get("type") == "system/message" and not system:
                content = (data.get("message") or {}).get("content")
                system = content if isinstance(content, str) else "".join(
                    p.get("text", "") for p in content or [] if isinstance(p, dict))
            elif row.get("type") == "request/header" and not tools:
                tools = _tool_names((data.get("header") or {}).get("tools"))
            if system and tools:
                break
    return {"system": system, "tools": tools}


def convert_session(path: Path) -> list[dict[str, Any]]:
    """Map DSH session events (format v3) to `llm` / `tool` trace events."""
    events: list[dict[str, Any]] = []
    system_chars = 0
    tools: list[str] = []
    tool_schema_chars = 0
    pending_tools: dict[str, dict[str, Any]] = {}
    last_stream_end: int | None = None
    step = 0

    with path.open(encoding="utf-8") as fh:
        rows = [json.loads(line) for line in fh if line.strip()]

    # A forked child (subagent_fork) starts with a copy of the parent's history up to
    # `session/end-seed`; those calls are already counted in the parent's log.
    if rows and rows[0].get("type") == "session" and rows[0].get("isSeeded"):
        seed_ends = [i for i, r in enumerate(rows) if r.get("type") == "session/end-seed"]
        if seed_ends:
            rows = rows[seed_ends[-1] + 1 :]

    for row in rows:
        kind = row.get("type")
        data = row.get("data") or {}
        if kind == "system/message":
            system_chars = _text_chars((data.get("message") or {}).get("content"))
        elif kind == "request/header":
            raw_tools = (data.get("header") or {}).get("tools")
            tools = _tool_names(raw_tools)
            tool_schema_chars = len(json.dumps(raw_tools, ensure_ascii=False)) if raw_tools else 0
        elif kind == "assistant/message":
            step += 1
            usage = data.get("usage") or {}
            stream = data.get("stream") or []
            times = [c["time"] for c in stream if isinstance(c, dict) and isinstance(c.get("time"), int)]
            message = data.get("message") or {}
            content = message.get("content") or []
            requested = [b.get("name") for b in content if isinstance(b, dict) and b.get("type") == "tool-call"]
            events.append({
                "kind": "llm",
                "step": step,
                "turn": data.get("turn"),
                "system_chars": system_chars,
                "tool_count": len(tools),
                "tools": tools,
                "tool_schema_chars": tool_schema_chars,
                "input_uncached": int(usage.get("inputTokens") or 0),
                "cache_read": int(usage.get("cacheReadTokens") or 0),
                "cache_write": int(usage.get("cacheWriteTokens") or 0),
                "output": int(usage.get("outputTokens") or 0),
                "reasoning": int(usage.get("reasoningTokens") or 0),
                # DSH logs chunk arrival times only; this is stream duration, not request latency.
                "latency_ms": (times[-1] - times[0]) if times else None,
                "ttft_ms": None,
                "requested_tools": requested,
                "text_chars": sum(len(b.get("text", "")) for b in content if isinstance(b, dict) and b.get("type") == "text"),
                "t_stream_start": times[0] if times else None,
            })
            last_stream_end = times[-1] if times else last_stream_end
        elif kind == "tool/call":
            try:
                args: Any = json.loads(data.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = data.get("arguments")
            pending_tools[data.get("callId")] = {
                "kind": "tool",
                "name": data.get("name"),
                "args": args,
                "call_id": data.get("callId"),
                "step": data.get("step"),
                "t_after": last_stream_end,
            }
        elif kind == "tool/result":
            message = data.get("message") or {}
            for block in message.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool-result":
                    continue
                event = pending_tools.pop(block.get("toolCallId"), None) or {"kind": "tool", "name": "?"}
                text = "".join(p.get("text", "") for p in block.get("content") or [] if isinstance(p, dict))
                event.update(result_chars=len(text), result_preview=text[:500], error=text[:500] if block.get("isError") else None)
                events.append(event)

    # Tool time ~= gap between the stream that requested it and the next stream (upper bound).
    llm_starts = [e["t_stream_start"] for e in events if e["kind"] == "llm" and e.get("t_stream_start")]
    for event in events:
        if event["kind"] == "tool" and event.get("t_after"):
            nxt = next((t for t in llm_starts if t > event["t_after"]), None)
            event["latency_ms"] = (nxt - event["t_after"]) if nxt else None
    return events
