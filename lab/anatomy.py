"""What a harness actually is: its middleware stack, tools and the exact first request.

Builds the harness with a probe model that records what the agent would send and
answers "done" without calling any API. Like DeepSeek Harness's read-only preset
viewer, but showing the composed result rather than the config.
"""

from __future__ import annotations

import inspect
import tempfile
import threading
from pathlib import Path
from typing import Any
from unittest import mock

from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

_PATCH_LOCK = threading.Lock()  # module-global patching: one anatomy build at a time
HOOKS = ("before_agent", "before_model", "wrap_model_call", "after_model", "wrap_tool_call", "after_agent")


class _Probe(BaseChatModel):
    calls: list[dict[str, Any]] = []
    bound_tools: list[Any] = []

    @property
    def _llm_type(self) -> str:
        return "probe"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        clone = self.model_copy()
        clone.bound_tools = list(tools)
        clone.calls = self.calls
        return clone

    def _generate(self, messages: Any, stop: Any = None, run_manager: Any = None, **kw: Any) -> ChatResult:
        self.calls.append({"messages": list(messages), "tools": self.bound_tools})
        return ChatResult(generations=[ChatGeneration(message=AIMessage("done"))])


def _hooks(mw: AgentMiddleware) -> list[str]:
    out = []
    for hook in HOOKS:
        mine = getattr(type(mw), hook, None)
        base = getattr(AgentMiddleware, hook, None)
        if mine is not None and mine is not base:
            out.append(hook)
    return out


def _middleware_row(mw: Any) -> dict[str, Any]:
    cls = type(mw)
    return {
        "name": getattr(mw, "name", cls.__name__),
        "class": f"{cls.__module__}.{cls.__qualname__}",
        "hooks": _hooks(mw),
        "tools": [t.name for t in getattr(mw, "tools", []) or []],
        "doc": (inspect.getdoc(cls) or "").split("\n\n")[0][:300],
    }


def _tool_row(tool: Any) -> dict[str, Any]:
    try:
        schema = convert_to_openai_tool(tool)["function"]
    except Exception:  # provider-native dict tools
        schema = tool if isinstance(tool, dict) else {"name": getattr(tool, "name", "?")}
    return {"name": schema.get("name"), "description": schema.get("description", ""), "parameters": schema.get("parameters", {}),
            "description_chars": len(schema.get("description", ""))}


def anatomy(harness_name: str) -> dict[str, Any]:
    import langchain.agents.factory as factory

    from lab.harnesses import BuildContext, get

    probe = _Probe()
    probe.calls = []
    graphs: list[dict[str, Any]] = []
    real = factory.create_agent

    owner = threading.get_ident()

    def spy(*args: Any, **kwargs: Any) -> Any:
        built = real(*args, **kwargs)
        if threading.get_ident() != owner:  # a chat session being built meanwhile: not ours
            return built
        graphs.append({"name": kwargs.get("name"), "middleware": [_middleware_row(m) for m in kwargs.get("middleware") or []],
                       "system_prompt": str(kwargs.get("system_prompt") or "")[:4000], "graph": built})
        return built

    targets = ["langchain.agents.create_agent", "deepagents.graph.create_agent", "deepagents.middleware.subagents.create_agent"]
    targets += [f"lab.harnesses.{m}.create_agent" for m in ("minimal", "experiments", "advanced")]
    with _PATCH_LOCK, tempfile.TemporaryDirectory() as tmp:
        patches = [mock.patch(t, spy) for t in targets]
        for p in patches:
            p.start()
        try:
            agent = get(harness_name).build(BuildContext(model=probe, model_name="probe", workdir=Path(tmp)))
        finally:
            for p in patches:
                p.stop()
        agent.invoke({"messages": [{"role": "user", "content": "hi"}]}, config={"recursion_limit": 20})

    first = probe.calls[0] if probe.calls else {"messages": [], "tools": []}
    system = "\n\n".join(m.text if hasattr(m, "text") else str(m.content) for m in first["messages"] if m.type == "system")
    tools = [_tool_row(t) for t in first["tools"]]
    # The outer agent is built last (create_deep_agent may wrap it with `with_config`).
    main = graphs[-1] if graphs else {"middleware": []}
    subagents: dict[str, dict[str, Any]] = {}
    for g in graphs[:-1]:  # deepagents can build a subagent spec more than once
        subagents.setdefault(str(g["name"]), {k: v for k, v in g.items() if k != "graph"})
    return {
        "harness": harness_name,
        "middleware": main["middleware"],
        "subagents": list(subagents.values()),
        "system_prompt": system,
        "system_chars": len(system),
        "tools": tools,
        "tool_schema_chars": sum(len(str(t)) for t in tools),
        "graph_nodes": list(agent.nodes),
    }


def dsh_anatomy(name: str) -> dict[str, Any]:
    from lab import dsh

    files = dsh.HARNESSES.get(name)
    if files is None:
        raise ValueError(f"unknown dsh harness {name!r}")
    return {"harness": name, "patches": [{"file": f, "text": (dsh.PATCH_DIR / f).read_text(encoding="utf-8")} for f in files]}
