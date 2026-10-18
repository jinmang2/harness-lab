"""DSH 0.2.x support: session format v4, the Messages wire format, per-harness runtimes (ADR-0014)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lab import dsh, gateway
from lab.runner import Task, run_batch


def _write_log(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_v4_tool_results_are_read(tmp_path):
    # v4 makes the tool message itself the result; v3 nested `tool-result` blocks in it.
    log = _write_log(tmp_path / "session.v4.jsonl", [
        {"type": "session", "version": 4, "id": "s", "cwd": "/w", "isSeeded": False, "delegationDepth": 0},
        {"type": "assistant/message", "data": {"turn": 1, "step": 1, "usage": {"inputTokens": 10, "cacheReadTokens": 5, "outputTokens": 3},
                                               "message": {"content": [{"type": "tool-call", "id": "c1", "name": "bash", "arguments": "{}"}]}}},
        {"type": "tool/call", "data": {"callId": "c1", "name": "bash", "arguments": "{\"command\": \"ls\"}", "step": 1}},
        {"type": "tool/result", "data": {"message": {"role": "tool", "toolCallId": "c1", "content": [{"type": "text", "text": "a.txt"}], "isError": False}}},
        {"type": "tool/result", "data": {"message": {"role": "tool", "toolCallId": "c2", "content": [{"type": "text", "text": "boom"}], "isError": True}}},
    ])
    events = dsh.convert_session(log)
    tools = [e for e in events if e["kind"] == "tool"]
    assert [(t["name"], t["result_preview"], t["error"]) for t in tools] == [("bash", "a.txt", None), ("?", "boom", "boom")]
    assert tools[0]["args"] == {"command": "ls"}
    llm = next(e for e in events if e["kind"] == "llm")
    assert (llm["input_uncached"], llm["cache_read"], llm["requested_tools"]) == (10, 5, ["bash"])


def test_harness_versions_get_their_own_runtime_and_home():
    assert dsh.version_of("minimal") == dsh.DSH_VERSION
    assert dsh.runtime_dir(dsh.DSH_VERSION) == dsh.RUNTIME_DIR and dsh.home_dir() == dsh.DSH_HOME
    week2 = dsh.version_of("ralph-official")
    assert week2 == dsh.WEEK2_VERSION != dsh.DSH_VERSION
    assert dsh.runtime_dir(week2).name == f".dsh-runtime-{week2}"
    assert dsh.environment(week2)["DSH_HOME"].endswith(f".dsh-home-{week2}")


def test_messages_usage_is_disjoint_and_merged():
    usage = {"input_tokens": 275, "cache_read_input_tokens": 5888, "cache_creation_input_tokens": 0, "output_tokens": 130}
    assert gateway.usage_to_tokens(usage) == {"input_uncached": 275, "cache_read": 5888, "cache_write": 0, "output": 130, "reasoning": 0}
    # chat/completions keeps its old meaning: prompt_tokens includes the cache hits
    assert gateway.usage_to_tokens({"prompt_tokens": 100, "prompt_cache_hit_tokens": 60, "completion_tokens": 5})["input_uncached"] == 40


def test_mock_messages_drives_a_structured_child():
    report_tool = {"name": "structured_output", "input_schema": {"type": "object", "properties": {
        k: {"type": "string"} for k in ("status", "summary", "evidence", "nextSteps", "blocker")}}}
    tools = [{"name": "bash", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}}}, report_tool]
    first = gateway.mock_messages_reply({"messages": [{"role": "user", "content": "work"}], "tools": tools})
    assert first["stop"] == "tool_use" and first["content"][0]["name"] == "bash"
    history = [{"role": "user", "content": "work"},
               {"role": "assistant", "content": first["content"]},
               {"role": "user", "content": [{"type": "tool_result", "tool_use_id": first["content"][0]["id"], "content": "MOCK_OK"}]}]
    second = gateway.mock_messages_reply({"messages": history, "tools": tools})
    assert second["content"][0]["name"] == "structured_output"
    assert second["content"][0]["input"]["status"] == "complete"


@pytest.mark.skipif(not os.environ.get("LAB_TEST_DSH"), reason="set LAB_TEST_DSH=1 (needs `lab dsh-install --version 0.2.0-rc.2`)")
def test_dsh_official_ralph_runs_fresh_child(mock_gateway):
    if not dsh.bin_path(dsh.WEEK2_VERSION).exists():
        pytest.skip(f"DeepSeek Harness {dsh.WEEK2_VERSION} not installed")
    task = Task(id="ralph-smoke", prompt="[mock:ralph] write DONE.md")
    batch_dir = run_batch([task], [("dsh", "ralph-official")], label="pytest-ralph")
    run = json.loads((batch_dir / "summary.jsonl").read_text().splitlines()[0])
    assert run["status"] == "ok", run["error"]
    assert run["tools_used"] == {"ralph": 1, "bash": 1, "structured_output": 1}
    run_dir = batch_dir / run["run_id"]
    assert (run_dir / "dsh-session.1.jsonl").is_file()  # the round's fresh child has its own session log
    wire = [json.loads(line) for line in (run_dir / "wire.jsonl").read_text().splitlines()]
    assert wire and all(w["path"].endswith("/v1/messages") for w in wire)
    bodies = [json.loads(gateway.body_path(w["id"]).read_text()) for w in wire]
    assert not any("dsh_session_log" in b or "dsh_plugin_packages" in b for b in bodies)  # nothing but the request leaves

