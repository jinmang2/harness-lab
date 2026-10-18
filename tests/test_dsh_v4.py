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


@pytest.mark.skipif(not os.environ.get("LAB_TEST_DSH"), reason="set LAB_TEST_DSH=1 (needs `lab dsh-install --version 0.2.0-rc.2`)")
def test_dsh_custom_ralph_overrides_a_false_completion(mock_gateway):
    # The mock worker reports `complete` every round, but the deployment verifier (week2 acceptance) fails on an
    # empty workspace, so the Creator-built plugin starts round 2 and stops at the call's maxRounds.
    if not dsh.bin_path(dsh.WEEK2_VERSION).exists():
        pytest.skip(f"DeepSeek Harness {dsh.WEEK2_VERSION} not installed")
    if not (dsh.home_dir(dsh.WEEK2_VERSION) / "profiles" / "headless" / "node_modules" / "@local" / "verified-ralph").exists():
        pytest.skip("verified-ralph bundle not installed in the headless profile")
    task = Task(id="vralph-smoke", prompt="[mock:vralph] write DONE.md")
    batch_dir = run_batch([task], [("dsh", "ralph-custom")], label="pytest-vralph")
    run = json.loads((batch_dir / "summary.jsonl").read_text().splitlines()[0])
    assert run["status"] == "ok", run["error"]
    assert run["tools_used"]["verified_ralph"] == 1 and run["tools_used"]["structured_output"] == 2
    run_dir = batch_dir / run["run_id"]
    assert (run_dir / "dsh-session.2.jsonl").is_file()  # two rounds, two fresh children
    trace = [json.loads(line) for line in (run_dir / "trace.jsonl").read_text().splitlines()]
    result = next(e for e in trace if e["kind"] == "tool" and e["name"] == "verified_ralph")["result_preview"]
    assert result.startswith("verified_ralph ended as budget-limited after 2 rounds.")
    assert "round 1 fail (exit 2), round 2 fail (exit 2)" in result  # empty workspace: week2_verify finds no SPEC.md
    progress = (run_dir / "workspace" / ".ralph" / "progress.md").read_text()
    assert "Round 1" in progress and "Round 2" in progress  # written by the plugin, not the worker


@pytest.mark.skipif(not os.environ.get("LAB_TEST_DSH"), reason="set LAB_TEST_DSH=1 (needs DSH 0.2 and `lab dsh-web-setup`)")
def test_dsh_web_runs_presets_and_goal_rounds(mock_gateway):
    from lab import dsh_web
    from lab.week2 import rounds

    if not dsh.bin_path(dsh.WEEK2_VERSION).exists() or not dsh_web.profile_dir().exists():
        pytest.skip("DSH 0.2 or the dsh-web profile is missing")
    tasks = [Task(id="goal", prompt="/goal write DONE.md"), Task(id="ralph", prompt="[mock:ralph] write DONE.md")]
    batch_dir = run_batch(tasks, [("dsh-web", "goal"), ("dsh-web", "ralph-official")], label="pytest-dsh-web")
    runs = {json.loads(line)["run_id"]: json.loads(line) for line in (batch_dir / "summary.jsonl").read_text().splitlines()}
    goal_run = runs["goal__dsh-web-goal__1"]
    assert goal_run["status"] == "ok", goal_run["error"]
    # `/goal` went through commands/execute (no model call), then the Web driver sent round 1 and the mock completed it
    assert [(r["round"], r["decision"]) for r in rounds(batch_dir / "goal__dsh-web-goal__1", "dsh-web")] == [(1, "complete")]
    header = json.loads((batch_dir / "ralph__dsh-web-ralph-official__1" / "dsh-session.jsonl").read_text().splitlines()[0])
    assert header["agentPreset"] == "lab-ralph-official"
    assert (batch_dir / "ralph__dsh-web-ralph-official__1" / "dsh-session.1.jsonl").is_file()  # the round's fresh child
    assert runs["ralph__dsh-web-ralph-official__1"]["tools_used"]["ralph"] == 1


def test_ralph_preset_patch_differs_from_standard_only_in_the_ralph_row():
    from lab import dsh_web

    if not dsh_web.shipped_standard_preset().exists():
        pytest.skip("DSH 0.2 not installed")
    generated = dsh_web.ralph_preset_patch(dsh_web.shipped_standard_preset().read_text())
    assert generated == (dsh.PATCH_DIR / "web-ralph-official.yml").read_text()  # the committed file is current
    shipped = [ln for ln in dsh_web.shipped_standard_preset().read_text().splitlines() if not ln.startswith("#")]
    ours = [ln for ln in generated.splitlines() if not ln.startswith("#") and ln]
    import difflib

    removed = [ln[1:].strip() for ln in difflib.ndiff([x for x in shipped if x.strip()], ours) if ln.startswith("- ")]
    assert removed == ["- id: preset-standard", "id: standard", "order: 1", "disabled: true", "maxRounds: 64"]
