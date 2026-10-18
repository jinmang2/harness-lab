"""Ralph loop mechanisms (lab/middleware/ralph.py): multi-round paths with fake children, plus a keyless run of all four."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lab.middleware import ralph as R
from lab.runner import Task, run_batch


class FakeChild:
    """Stands in for a compiled child agent: returns queued reports, records the prompts it got."""

    def __init__(self, reports: list[Any], prompts: list[str], kit: R.StructuredOutput | None = None) -> None:
        self.reports, self.prompts, self.kit = reports, prompts, kit

    def invoke(self, state: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        assert config["configurable"]["ralph_depth"] == 1 and config["configurable"]["thread_id"].startswith("ralph-child-")
        assert config["metadata"]["delegation_depth"] == 1
        self.prompts.append(state["messages"][0].content)
        report = self.reports.pop(0)
        if isinstance(report, Exception):
            raise report
        if report is not None:  # what the model would send: invalid args leave nothing captured
            self.kit.tool.invoke(report)
        return {"messages": []}


def _factory(reports: list[Any], prompts: list[str]):
    return lambda kit: FakeChild(reports, prompts, kit)


def _dsh(status: str, **extra: Any) -> dict[str, Any]:
    base = {"status": status, "summary": f"did {status}", "evidence": [], "nextSteps": [], "blocker": ""}
    return {**base, **extra}


def test_fresh_hands_only_the_report_to_the_next_round():
    events: list[dict] = []
    prompts: list[str] = []
    reports = [_dsh("continue", nextSteps=["finish rule 8"]), _dsh("complete", evidence=["13/13"])]
    tool = R.ralph_tool(_factory(reports, prompts), R.emitter(events, "fresh"), max_rounds=5)
    out = tool.invoke({"objective": "do it", "maxRounds": 3})
    assert out.startswith("Ralph worker reported completion after 2 rounds.")
    assert "Ralph round: 1 of 3." in prompts[0] and "(none — this is the first round)" in prompts[0]
    assert '"nextSteps":["finish rule 8"]' in prompts[1] and "Ralph round: 2 of 3." in prompts[1]
    assert [(e["round"], e["decision"]) for e in events] == [(1, "continue"), (2, "complete")]


def test_fresh_trusts_the_worker_and_stops_at_the_ceiling():
    # DSH throws these as tool errors: the parent model gets the text and keeps going
    out = R.ralph_tool(_factory([], []), R.emitter([], "fresh"), max_rounds=5).invoke({"objective": "x", "maxRounds": 6})
    assert out == "Ralph maxRounds 6 exceeds the deployment ceiling 5"
    out = R.ralph_tool(_factory([], []), R.emitter([], "fresh"), max_rounds=5).invoke({"objective": "x", "maxRounds": 1.5})
    assert out == "Ralph maxRounds must be a positive safe integer"
    reports = [_dsh("continue", nextSteps=["more"]) for _ in range(2)]
    out = R.ralph_tool(_factory(reports, []), R.emitter([], "fresh"), max_rounds=2).invoke({"objective": "x"})
    assert out.startswith("Ralph reached its 2 rounds limit; the worker reported work remaining.")


def test_fresh_rejects_invalid_reports_like_dsh():
    with pytest.raises(ValueError, match="a complete Ralph report needs evidence"):
        R.validate_dsh_report(_dsh("complete"), 16384)
    with pytest.raises(ValueError, match="a continuing Ralph report needs nextSteps"):
        R.validate_dsh_report(_dsh("continue"), 16384)
    with pytest.raises(ValueError, match="exceeds maxHandoffChars"):
        R.validate_dsh_report(_dsh("blocked", blocker="x" * 100), 50)
    with pytest.raises(ValueError, match="summary must be non-empty and normalized"):
        R.validate_dsh_report(_dsh("blocked", blocker="b", summary=" padded"), 16384)
    assert R._js_length("😀") == 2  # JSON.stringify(...).length counts UTF-16 code units


def test_fresh_invalid_report_fails_the_workflow_and_missing_report_fails_the_round():
    out = R.ralph_tool(_factory([_dsh("complete")], []), R.emitter([], "fresh")).invoke({"objective": "x"})
    assert out == "Ralph workflow failed: a complete Ralph report needs evidence, no nextSteps, and an empty blocker"
    out = R.ralph_tool(_factory([None], []), R.emitter([], "fresh")).invoke({"objective": "x"})
    assert out == "Ralph round 1 child failed before producing a structured report.\nNo previous handoff was available."


def test_fresh_child_failure_ends_the_run_with_the_last_handoff():
    reports = [_dsh("continue", nextSteps=["a"]), RuntimeError("boom")]
    out = R.ralph_tool(_factory(reports, []), R.emitter([], "fresh")).invoke({"objective": "x"})
    assert out.startswith("Ralph round 2 child failed before producing a structured report.\nLast successful handoff:\n{")


def _vreport(status: str) -> dict[str, Any]:
    return {"status": status, "summary": f"claims {status}", "nextSteps": [] if status != "continue" else ["x"], "blocker": ""}


def test_verified_ignores_a_false_completion_claim(tmp_path: Path):
    # The worker says "complete" in round 1, but the verifier fails; round 2 sees the failure and fixes it.
    script = tmp_path / "verify.sh"
    script.write_text('test -f fixed && echo PASS && exit 0; echo "rule 8 failed"; exit 1\n')
    events: list[dict] = []
    prompts: list[str] = []

    class Fixer(FakeChild):
        def invoke(self, state, config):
            out = super().invoke(state, config)
            if len(self.prompts) == 2:
                (tmp_path / "fixed").write_text("")
            return out

    reports = [_vreport("complete"), _vreport("complete")]
    tool = R.verified_ralph_tool(lambda kit: Fixer(reports, prompts, kit), R.emitter(events, "verified"), tmp_path, f"sh {script}")
    out = tool.invoke({"objective": "fix"})
    assert out.startswith("verified_ralph ended as verified after 2 rounds.\nVerifier: round 1 fail (exit 1), round 2 pass (exit 0).")
    assert "Previous round verifier result: exit code 1.\nLast 4000 characters of its output:\nrule 8 failed" in prompts[1]
    assert [(e["worker_status"], e["verify_exit"], e["decision"]) for e in events] == [("complete", 1, "continue"), ("complete", 0, "verified")]
    progress = (tmp_path / ".ralph" / "progress.md").read_text()
    assert progress.startswith("# Verified RALPH progress log\n\n## Round 1\n- Worker status: complete")
    assert "- Verifier: failed (exit code 1)" in progress and "## Round 2" in progress


def test_verified_retries_once_then_fails_and_honours_blocked(tmp_path: Path):
    events: list[dict] = []
    reports = [RuntimeError("x"), _vreport("blocked")]
    out = R.verified_ralph_tool(_factory(reports, []), R.emitter(events, "verified"), tmp_path, "exit 1").invoke({"objective": "x"})
    assert out.startswith("verified_ralph ended as blocked after 1 round.") and events[0]["attempt"] == 1
    out = R.verified_ralph_tool(_factory([RuntimeError("a"), {"bad": 1}], []), R.emitter([], "verified"), tmp_path, "exit 1").invoke({"objective": "x"})
    assert out.startswith("verified_ralph ended as round-failed after 1 round.") and "Failure: child returned no valid structured report" in out


def test_verified_normalizes_reports_like_the_plugin():
    got = R.read_verified_report({"status": "continue", "summary": "  did a  ", "nextSteps": [" one ", "  "], "blocker": " "})
    assert got == {"status": "continue", "summary": "did a", "nextSteps": ["one"], "blocker": ""}
    assert R.read_verified_report({"status": "done", "summary": "x", "nextSteps": [], "blocker": ""}) is None


def test_verified_without_a_command_falls_back_to_the_worker(tmp_path: Path):
    out = R.verified_ralph_tool(_factory([_vreport("complete")], []), R.emitter([], "verified"), tmp_path, "").invoke({"objective": "x"})
    assert out.startswith("verified_ralph ended as self-reported after 1 round.\nVerifier: not configured; no round was machine-checked.")


def test_all_mechanisms_run_keyless(mock_gateway, monkeypatch):
    monkeypatch.setenv("LAB_RALPH_VERIFY", "true")
    task = Task(id="r", prompt="[mock:ralph] [mock:vralph] write DONE.md")
    harnesses = ("ralph-fresh", "ralph-verified", "ralph-judge", "ralph-reset", "ralph-check")
    batch_dir = run_batch([task], [("lab", h) for h in harnesses], label="pytest-ralph-lab")
    runs = {json.loads(line)["harness"]: json.loads(line) for line in (batch_dir / "summary.jsonl").read_text().splitlines()}
    assert all(r["status"] == "ok" for r in runs.values()), {h: r["error"] for h, r in runs.items()}
    rounds = {}
    for harness in runs:
        trace = [json.loads(line) for line in (batch_dir / f"r__lab-{harness}__1" / "trace.jsonl").read_text().splitlines()]
        rounds[harness] = [e["decision"] for e in trace if e["kind"] == "round"]
        if harness in ("ralph-fresh", "ralph-verified"):  # each round child's calls are tagged in the batch trace
            llm = [e for e in trace if e["kind"] == "llm"]
            assert any(e.get("child") and e.get("depth") == 1 for e in llm) and any(not e.get("child") for e in llm)
            assert any(e.get("child") for e in trace if e["kind"] == "tool")
    verified = (batch_dir / "r__lab-ralph-verified__1" / "trace.jsonl").read_text()
    assert "verified_ralph round 1/" in verified, sorted({e.get("child_label") for e in map(json.loads, verified.splitlines())})  # the Creator plugin labels its children; tool-ralph does not
    assert rounds == {"ralph-fresh": ["complete"], "ralph-verified": ["verified"], "ralph-judge": ["complete"],
                      "ralph-reset": ["complete"], "ralph-check": ["verified"]}
    assert runs["ralph-fresh"]["tools_used"]["ralph"] == 1 and runs["ralph-reset"]["tools_used"]["ralph_handoff"] == 1


def test_structured_output_records_one_valid_report_like_dsh():
    kit = R.StructuredOutput(R.VERIFIED_REPORT_SCHEMA)
    assert kit.tool.return_direct  # the call ends the child's turn (DSH `concludeTurn`)
    assert "Invalid arguments" in kit.tool.invoke({"status": "done", "summary": "x", "nextSteps": [], "blocker": ""})
    assert kit.captured is None
    ok = {"status": "complete", "summary": "x", "nextSteps": [], "blocker": ""}
    assert kit.tool.invoke(ok) == "Structured output recorded." and kit.captured == ok
    assert "already recorded" in kit.tool.invoke({**ok, "summary": "y"}) and kit.captured == ok


def test_goal_rounds_run_in_batch_like_the_dsh_driver(mock_gateway):
    # `/goal` creates the goal without a model call; round 1 reads and completes it (mock), then the driver stops.
    task = Task(id="g", prompt="/goal write DONE.md")
    batch_dir = run_batch([task], [("lab", "goal")], label="pytest-goal")
    run = json.loads((batch_dir / "summary.jsonl").read_text().splitlines()[0])
    assert run["status"] == "ok", run["error"]
    trace = [json.loads(line) for line in (batch_dir / "g__lab-goal__1" / "trace.jsonl").read_text().splitlines()]
    rounds = [(e["round"], e["decision"]) for e in trace if e["kind"] == "round"]
    assert rounds == [(0, "created"), (1, "continue"), (1, "complete")]
    created = next(e for e in trace if e["kind"] == "round")["goal"]
    assert created["maxGoalRounds"] == 5 and created["objective"] == "write DONE.md"
    assert run["tools_used"].get("update_goal") == 1


def test_check_feeds_the_failing_output_back_into_the_same_thread(mock_gateway, monkeypatch):
    monkeypatch.setenv("LAB_RALPH_VERIFY", "test -f .seen && exit 0; touch .seen; echo 'rule 7 failed'; exit 1")
    batch_dir = run_batch([Task(id="c", prompt="write DONE.md")], [("lab", "ralph-check")], label="pytest-check")
    trace = [json.loads(line) for line in (batch_dir / "c__lab-ralph-check__1" / "trace.jsonl").read_text().splitlines()]
    assert [(e["round"], e["verify_exit"], e["decision"]) for e in trace if e["kind"] == "round"] == [(1, 1, "continue"), (2, 0, "verified")]
    sent = [e for e in trace if e["kind"] == "llm"]
    assert len(sent) >= 2  # the second model call answers the injected check output in the same thread
