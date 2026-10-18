"""Building blocks shared by several harnesses."""

from __future__ import annotations

import html
import os
import re
import urllib.request
from pathlib import Path
from typing import Any

from langchain.agents.middleware import HumanInTheLoopMiddleware, ShellToolMiddleware
from langchain.agents.middleware.shell_tool import HostExecutionPolicy, ShellSession
from langchain_core.tools import tool

# Tool description copied from DeepSeek Harness `presets/minimal/agent.cordis.yml` (MIT)
# so the minimal comparison sends the same words.
DSH_BASH_DESCRIPTION = """Run commands in a bash shell
* When invoking this tool, the contents of the "command" parameter does NOT need to be XML-escaped.
* Network access depends on the task environment. Prefer configured mirrors/proxies when they are available.
* State is persistent across command calls and discussions with the user.
* To inspect a particular line range of a file, e.g. lines 10-25, try 'sed -n 10,25p /path/to/the/file'.
* Please avoid commands that may produce a very large amount of output.
* Please run long lived commands in the background, e.g. 'sleep 10 &' or start a server in the background."""


SENSITIVE_ENV = re.compile(r"KEY|PASSWORD|SECRET|TOKEN", re.I)  # same rule as DSH's subprocess scrub


def shell_env() -> dict[str, str]:
    """Environment for agent shells: the parent's minus API keys and other secrets."""
    return {k: v for k, v in os.environ.items() if not SENSITIVE_ENV.search(k)}


APPROVAL_TOOLS = ("bash", "execute", "write_file", "edit_file")


def interrupts(ctx: Any, base: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """`interrupt_on` for create_deep_agent: the harness's own plus the session's approval policy."""
    merged = dict(base or {})
    if getattr(ctx, "approval", "auto") == "ask":
        merged.update({name: True for name in APPROVAL_TOOLS})
    return merged or None


def collaboration(ctx: Any) -> list[Any]:
    """DSH standard's ask_user_question + plan mode (see lab/middleware/collaboration.py)."""
    from lab.middleware.collaboration import CollaborationMiddleware
    from lab.middleware.goal import GoalMiddleware

    return [CollaborationMiddleware(interactive=getattr(ctx, "interactive", False)),
            GoalMiddleware(default_max_rounds=getattr(ctx, "goal_rounds", 256)), *getattr(ctx, "session", [])]


def approvals(ctx: Any) -> list[Any]:
    """Middleware for create_agent harnesses: approval before shell and file writes when asked."""
    on = interrupts(ctx)
    return [*([HumanInTheLoopMiddleware(interrupt_on=on)] if on else []), *getattr(ctx, "session", [])]


class _MarkerSplitQueue:
    """Queue view that splits `text<marker> 0` into `text` and `<marker> 0`."""

    def __init__(self, inner: Any, marker: str) -> None:
        self._inner = inner
        self._marker = marker
        self._pending: list[tuple[str, str | None]] = []

    def get(self, *args: Any, **kwargs: Any) -> tuple[str, str | None]:
        if self._pending:
            return self._pending.pop(0)
        source, data = self._inner.get(*args, **kwargs)
        if source == "stdout" and data and self._marker in data and not data.startswith(self._marker):
            cut = data.index(self._marker)
            self._pending.append((source, data[cut:]))
            return source, data[:cut]
        return source, data

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _NewlineSafeSession(ShellSession):
    """LangChain's session only sees its done marker at the start of a line, so output
    without a trailing newline (`curl ... | head -c 2000`, `printf x`) hangs until the
    command timeout. DSH's persistent bash has no such limit; split the marker off instead."""

    def _collect_output(self, marker: str, deadline: float, timeout: float) -> Any:
        inner = self._queue
        self._queue = _MarkerSplitQueue(inner, marker)  # type: ignore[assignment]
        try:
            return super()._collect_output(marker, deadline, timeout)
        finally:
            self._queue = inner


class _PersistentBash(ShellToolMiddleware):
    @property
    def name(self) -> str:
        return "ShellToolMiddleware"

    def _create_resources(self) -> Any:
        resources = super()._create_resources()
        resources.session.__class__ = _NewlineSafeSession
        return resources


def persistent_bash(workdir: Path) -> ShellToolMiddleware:
    """One long-lived bash session exposed as a `bash` tool (DSH `persistent-bash`)."""
    return _PersistentBash(
        workspace_root=workdir,
        env=shell_env(),
        tool_name="bash",
        tool_description=DSH_BASH_DESCRIPTION,
        execution_policy=HostExecutionPolicy(command_timeout=300, max_output_lines=400),
    )


_TAGS = re.compile(r"<(script|style)[^>]*>.*?</\1>|<[^>]+>", re.S | re.I)


@tool
def fetch_url(url: str) -> str:
    """Fetch a web page or API endpoint over HTTP GET and return its text (HTML tags stripped, max 20000 chars)."""
    request = urllib.request.Request(url, headers={"User-Agent": "harness-lab/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read(2_000_000).decode(response.headers.get_content_charset() or "utf-8", "replace")
    text = html.unescape(_TAGS.sub(" ", raw)) if "<html" in raw[:2000].lower() else raw
    return re.sub(r"\s+\n", "\n", text)[:20000]
