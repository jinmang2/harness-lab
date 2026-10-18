"""Chat UI events for child agents that loop tools start (lab/viewer/play.py `_Stream`)."""

from __future__ import annotations

import time
import uuid
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, LLMResult


class _FakeSession:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.tool_runs: set[Any] = set()
        self.request_seen = True

    def emit(self, kind: str, **data: Any) -> None:
        self.events.append({"type": kind, **data})

    def first_token(self) -> None:
        pass

    def add_usage(self, usage: dict[str, Any]) -> None:
        pass


def _result(text: str) -> LLMResult:
    msg = AIMessage(text, usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12})
    return LLMResult(generations=[[ChatGeneration(message=msg)]])


def test_stream_tags_a_ralph_child_and_its_runs():
    from lab.viewer.play import _Stream

    session = _FakeSession()
    s = _Stream(session)  # type: ignore[arg-type]
    agent, model, ralph = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    s.on_chain_start({}, {}, run_id=agent, parent_run_id=None, metadata={})
    s.on_chat_model_start({}, [[]], run_id=model, parent_run_id=agent, metadata={})
    s.on_llm_end(_result(""), run_id=model)
    s.on_tool_start({"name": "ralph"}, "", run_id=ralph, parent_run_id=agent, inputs={"objective": "x"}, metadata={})

    meta = {"ralph_child": True, "child_thread": "ralph-child-1", "child_label": None, "delegation_depth": 1}
    root, node, cm, bash = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    prompt = "You are one fresh worker.\n\nImmutable objective:\nx\n\nRalph round: 2 of 5.\n\nPrevious structured handoff:\n{}"
    s.on_chain_start({}, {"messages": [HumanMessage(prompt)]}, run_id=root, parent_run_id=ralph, metadata=meta)
    s.on_chain_start({}, {}, run_id=node, parent_run_id=root, metadata={**meta, "langgraph_node": "model"})
    s.on_chat_model_start({}, [[]], run_id=cm, parent_run_id=node, metadata={**meta, "langgraph_node": "model"})
    s.on_llm_new_token("hi", run_id=cm)
    s.on_llm_end(_result("hi"), run_id=cm)
    s.on_tool_start({"name": "bash"}, "", run_id=bash, parent_run_id=node, inputs={"command": "ls"}, metadata=meta)
    s.on_tool_end("ok", run_id=bash)
    s.on_chain_end({}, run_id=node)
    s.on_chain_end({}, run_id=root)
    s.on_tool_end("Ralph worker reported completion after 1 round.", run_id=ralph)

    by = {}
    for e in session.events:
        by.setdefault(e["type"], []).append(e)
    start = by["child_start"]
    assert len(start) == 1
    assert start[0] | {"prompt": None} == {"type": "child_start", "child_id": "ralph-child-1", "label": None, "title": "Ralph round 2",
                                           "depth": 1, "parent_tool_run_id": str(ralph), "parent": None, "prompt": None}
    assert start[0]["prompt"] == prompt
    assert by["child_end"] == [{"type": "child_end", "child_id": "ralph-child-1", "error": False}]
    parent_llm, child_llm = by["llm_start"]
    assert "child" not in parent_llm and parent_llm["nested"] is False
    assert child_llm["child"] == "ralph-child-1" and child_llm["nested"] is True and child_llm["child_nested"] is False
    assert by["token"][0]["child"] == "ralph-child-1"
    assert "child" not in by["llm_end"][0] and by["llm_end"][1]["child"] == "ralph-child-1"
    ralph_start, bash_start = by["tool_start"]
    assert "child" not in ralph_start
    assert bash_start["child"] == "ralph-child-1" and bash_start["child_nested"] is False
    bash_end, ralph_end = by["tool_end"]
    assert bash_end["child"] == "ralph-child-1" and "child" not in ralph_end


def test_stream_labels_and_failed_children():
    from lab.viewer.play import _Stream

    session = _FakeSession()
    s = _Stream(session)  # type: ignore[arg-type]
    tool, root = uuid.uuid4(), uuid.uuid4()
    s.on_tool_start({"name": "verified_ralph"}, "", run_id=tool, parent_run_id=None, inputs={}, metadata={})
    meta = {"child_thread": "ralph-child-2", "child_label": "verified_ralph round 1/5 attempt 1", "delegation_depth": 1}
    s.on_chain_start({}, {"messages": [HumanMessage("Round 1 of 5.")]}, run_id=root, parent_run_id=tool, metadata=meta)
    s.on_chain_error(RuntimeError("boom"), run_id=root)
    start = next(e for e in session.events if e["type"] == "child_start")
    assert start["label"] == "verified_ralph round 1/5 attempt 1" and start["title"] == "Ralph round 1"
    end = next(e for e in session.events if e["type"] == "child_end")
    assert end["error"] is True and "boom" in end["text"]


def test_task_subagents_keep_the_nested_flag_only():
    from lab.viewer.play import _Stream

    session = _FakeSession()
    s = _Stream(session)  # type: ignore[arg-type]
    task, inner, cm = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    s.on_tool_start({"name": "task"}, "", run_id=task, parent_run_id=None, inputs={}, metadata={})
    s.on_chain_start({}, {}, run_id=inner, parent_run_id=task, metadata={"lc_agent_name": "general-purpose"})
    s.on_chat_model_start({}, [[]], run_id=cm, parent_run_id=inner, metadata={})
    llm = next(e for e in session.events if e["type"] == "llm_start")
    assert llm["nested"] is True and "child" not in llm
    assert not [e for e in session.events if e["type"].startswith("child_")]


def _wait(session: Any) -> None:
    for _ in range(300):
        if session.status not in ("running", "waiting"):
            return
        time.sleep(0.1)
    raise AssertionError(f"session still {session.status}")


def test_ralph_session_streams_child_events(mock_gateway):
    from lab.viewer.play import PlaySession

    session = PlaySession("ralph-fresh")
    session.send("[mock:ralph] write DONE.md")
    _wait(session)
    assert session.status == "idle", session.error
    kinds = [e["type"] for e in session.events]
    starts = [e for e in session.events if e["type"] == "child_start"]
    assert starts and all(e["title"].startswith("Ralph round ") for e in starts), starts
    ids = {e["child_id"] for e in starts}
    assert {e["child_id"] for e in session.events if e["type"] == "child_end"} == ids
    ralph = next(e for e in session.events if e["type"] == "tool_start" and e["name"] == "ralph")
    assert all(e["parent_tool_run_id"] == ralph["run_id"] for e in starts)
    tagged = [e for e in session.events if e.get("child") in ids]
    assert {"llm_start", "llm_end", "tool_start", "tool_end"} <= {e["type"] for e in tagged}
    assert kinds.index("child_start") < kinds.index("child_end")
    end = next(e for e in session.events if e["type"] == "tool_end" and e["name"] == "ralph")
    assert "\nFinal report:\n" in end["preview"] and "child" not in end


def test_verified_ralph_session_labels_children(mock_gateway, monkeypatch):
    from lab.viewer.play import PlaySession

    monkeypatch.setenv("LAB_RALPH_VERIFY", "true")
    session = PlaySession("ralph-verified")
    session.send("[mock:vralph] write DONE.md")
    _wait(session)
    assert session.status == "idle", session.error
    starts = [e for e in session.events if e["type"] == "child_start"]
    assert starts and starts[0]["label"].startswith("verified_ralph round 1/"), starts
    end = next(e for e in session.events if e["type"] == "tool_end" and e["name"] == "verified_ralph")
    assert end["preview"].startswith("verified_ralph ended as verified after 1 round.")
