"""The week2 task is fair: the acceptance suite is satisfiable, and the starter tests leave rules uncovered."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from lab.runner import load_tasks

ROOT = Path(__file__).resolve().parent.parent
ACCEPTANCE = ROOT / "tasks" / "checks" / "week2_acceptance.py"
FIXTURE = ROOT / "tasks" / "fixtures" / "week2-durations"
REFERENCE = Path(__file__).resolve().parent / "data" / "week2_reference"


def _accept(workspace: Path) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, str(ACCEPTANCE), str(workspace)], capture_output=True, text=True, timeout=60)
    return proc.returncode, json.loads(proc.stdout)


def test_reference_passes_every_rule_and_the_stub_none(tmp_path):
    code, result = _accept(REFERENCE)
    assert code == 0 and result["passed"] == result["total"] == 13
    code, result = _accept(FIXTURE)
    assert code == 1 and result["passed"] == 0


def test_starter_tests_pass_with_the_reference(tmp_path):
    workspace = tmp_path / "ws"
    shutil.copytree(FIXTURE, workspace)
    shutil.copy(REFERENCE / "durations.py", workspace / "durations.py")
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=workspace, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_task_check_uses_the_acceptance_suite():
    task = load_tasks(ROOT / "tasks" / "week2.yaml", ["durations"])[0]
    assert task.fixture == "week2-durations" and "week2_acceptance.py" in task.check


def test_backlog_task_shares_the_spec_and_starts_unchecked():
    backlog = ROOT / "tasks" / "fixtures" / "week2-durations-backlog"
    assert (backlog / "SPEC.md").read_text() == (FIXTURE / "SPEC.md").read_text()
    assert (backlog / "durations.py").read_text() == (FIXTURE / "durations.py").read_text()
    items = [line for line in (backlog / "BACKLOG.md").read_text().splitlines() if line.startswith("- [")]
    assert len(items) == 4 and all(line.startswith("- [ ]") for line in items)
    code, _ = _accept(backlog)
    assert code == 1
    task = load_tasks(ROOT / "tasks" / "week2.yaml", ["durations-backlog"])[0]
    assert task.fixture == "week2-durations-backlog" and "BACKLOG.md" in task.prompt


def test_isolated_workspace_hides_the_batch_and_is_archived(mock_gateway):
    from lab.runner import Task, run_batch
    from lab.week2 import outside_access

    task = Task(id="iso", prompt="write DONE.md", fixture="week2-durations", isolate=True)
    batch_dir = run_batch([task], [("lab", "standard")], label="pytest-isolate")
    run_dir = batch_dir / "iso__lab-standard__1"
    header = json.loads((run_dir / "trace.jsonl").read_text().splitlines()[0])
    assert not header["cwd"].startswith(str(batch_dir)) and not Path(header["cwd"]).exists()  # temp dir, removed
    assert (run_dir / "workspace" / "SPEC.md").is_file()  # archived
    assert outside_access(run_dir) == []
    root = Path(header["cwd"]).parent.parent  # lab-ws: enterable, not listable
    assert root.name == "lab-ws" and oct(root.stat().st_mode & 0o777) == oct(0o300)


def test_outside_access_flags_paths_beyond_the_workspace(tmp_path):
    from lab.week2 import outside_access

    run_dir = tmp_path / "run"
    (run_dir / "workspace").mkdir(parents=True)
    ws = run_dir / "workspace"
    events = [{"kind": "run", "cwd": str(ws)},
              {"kind": "tool", "name": "read_file", "args": {"file_path": f"{ws}/SPEC.md"}},
              {"kind": "tool", "name": "execute", "args": {"command": "python3 /tmp/check.py"}},
              {"kind": "tool", "name": "execute", "args": {"command": "cat /Users/someone/repo/tests/data/ref.py"}}]
    (run_dir / "trace.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    assert outside_access(run_dir) == ["/Users/someone/repo/tests/data/ref.py"]


def test_week2_metrics_tell_a_caught_claim_from_a_wrong_stop():
    from lab.week2 import _verifier_exits, ended_unmet, false_completions, stop_reason

    full, partial = {"passed": 13, "total": 13}, {"passed": 12, "total": 13}
    caught = {"loop": "verified_ralph ended as verified after 2 rounds.\nVerifier: round 1 fail (exit 1), round 2 pass (exit 0).",
              "status": "ok", "acc": full,
              "rounds": [{"round": 1, "status": "complete", "verify_exit": 1, "decision": ""},
                         {"round": 2, "status": "complete", "verify_exit": 0, "decision": ""}]}
    assert _verifier_exits(caught["loop"]) == {1: 1, 2: 0}
    assert stop_reason(caught) == "verified" and false_completions(caught) == 1 and ended_unmet(caught) == 0
    judged = {"loop": "", "status": "ok", "acc": partial, "rounds": [{"round": 1, "status": "", "verify_exit": None, "decision": "complete"}]}
    assert stop_reason(judged) == "complete" and false_completions(judged) == 1 and ended_unmet(judged) == 1
    official = {"loop": "Ralph worker reported completion after 4 rounds.", "status": "ok", "acc": full,
                "rounds": [{"round": i, "status": s, "verify_exit": None, "decision": ""} for i, s in enumerate(["continue"] * 3 + ["complete"], 1)]}
    assert stop_reason(official) == "worker complete" and false_completions(official) == 0
    crashed = {"loop": "", "status": "error", "error": "GraphRecursionError('x')", "acc": partial, "rounds": []}
    assert stop_reason(crashed) == "error: GraphRecursionError" and ended_unmet(crashed) == 0


SIZES = ROOT / "tasks" / "fixtures" / "week2-sizes-backlog"
SIZES_REFERENCE = Path(__file__).resolve().parent / "data" / "week2_sizes_reference"
VERIFY = ROOT / "tasks" / "checks" / "week2_verify.py"


def test_sizes_task_is_satisfiable_and_the_starter_tests_leave_rules_open(tmp_path):
    proc = subprocess.run([sys.executable, str(ROOT / "tasks" / "checks" / "week2_sizes_acceptance.py"), str(SIZES_REFERENCE)],
                          capture_output=True, text=True)
    assert proc.returncode == 0 and json.loads(proc.stdout)["passed"] == 13
    workspace = tmp_path / "ws"
    shutil.copytree(SIZES, workspace)
    stub = subprocess.run([sys.executable, str(VERIFY), str(workspace)], capture_output=True, text=True)
    assert stub.returncode == 1 and json.loads(stub.stdout)["passed"] == 0
    shutil.copy(SIZES_REFERENCE / "sizes.py", workspace / "sizes.py")
    starter = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=workspace, capture_output=True, text=True)
    assert starter.returncode == 0, starter.stderr
    full = subprocess.run([sys.executable, str(VERIFY), str(workspace)], capture_output=True, text=True)
    assert full.returncode == 0 and json.loads(full.stdout)["passed"] == 13
    items = [line for line in (SIZES / "BACKLOG.md").read_text().splitlines() if line.startswith("- [ ]")]
    assert len(items) == 4


def test_week2_verify_picks_the_suite_from_the_spec(tmp_path):
    durations = tmp_path / "d"
    shutil.copytree(ROOT / "tasks" / "fixtures" / "week2-durations-backlog", durations)
    shutil.copy(REFERENCE / "durations.py", durations / "durations.py")
    assert subprocess.run([sys.executable, str(VERIFY), str(durations)], capture_output=True).returncode == 0
    assert subprocess.run([sys.executable, str(VERIFY), str(tmp_path)], capture_output=True).returncode == 2
    for task in load_tasks(ROOT / "tasks" / "week2.yaml"):
        suite = {"sizes": "week2_sizes_acceptance.py", "versions": "week2_versions_acceptance.py"}.get(task.id.split("-")[0], "week2_acceptance.py")
        assert suite in task.check and task.isolate


def test_week2_grades_each_task_with_its_own_suite():
    from lab.week2 import acceptance

    assert acceptance(SIZES_REFERENCE, "sizes-backlog-goal")["passed"] == 13
    assert acceptance(REFERENCE, "durations-backlog")["passed"] == 13
    for task in load_tasks(ROOT / "tasks" / "week2.yaml"):
        assert task.id.split("-")[0] in ("durations", "sizes", "versions")


def test_round_count_sums_repeated_loop_calls():
    from lab.week2 import round_count

    def run(*ns):
        return {"rounds": [{"round": n} for n in ns]}

    assert round_count(run(1, 2, 2, 3)) == 3  # a retry or stop event repeats a number
    assert round_count(run(1, 2, 1, 2)) == 4  # round 2 failed, the parent called the loop again
    assert round_count(run()) == 0


def test_rounds_keep_only_the_harness_own_loop_and_no_handoff_counts_as_done(tmp_path):
    from lab.week2 import ended_unmet, rounds

    events = [{"kind": "round", "mechanism": "check", "round": 1, "decision": "continue", "verify_exit": 1},
              {"kind": "round", "mechanism": "check", "round": 2, "decision": "verified", "verify_exit": 0},
              {"kind": "round", "mechanism": "goal", "round": 0, "decision": "complete"}]  # the worker used goal tools
    (tmp_path / "trace.jsonl").write_text("\n".join(json.dumps(e) for e in events))
    assert [x["decision"] for x in rounds(tmp_path, "lab", "ralph-check")] == ["continue", "verified"]
    unmet = {"loop": "", "status": "ok", "acc": {"passed": 12, "total": 13},
             "rounds": [{"round": 3, "status": "", "decision": "stop-no-handoff", "verify_exit": None}]}
    assert ended_unmet(unmet) == 1


def test_only_answer_reaching_paths_disqualify(tmp_path):
    from lab.week2 import answer_access

    cwd = "/var/folders/x/T/lab-ws/tmpOWN/workspace"
    (tmp_path / "trace.jsonl").write_text(json.dumps({"cwd": cwd}))
    paths = [str(ROOT / "tasks" / "checks" / "week2_acceptance.py"), str(ROOT / "tests" / "data"),
             "/var/folders/x/T/lab-ws/tmpOTHER/workspace/sizes.py",
             str(ROOT / ".dsh-runtime-0.2.0-rc.2" / "README.md"), "/var/folders/x/T/lab-ws", "/etc.",
             "/var/folders/x/T/lab-ws/tmpOWN"]
    assert answer_access(tmp_path, paths) == paths[:3]


VERSIONS = ROOT / "tasks" / "fixtures" / "week2-versions-backlog"
VERSIONS_REFERENCE = Path(__file__).resolve().parent / "data" / "week2_versions_reference"


def test_versions_task_is_satisfiable_and_the_starter_tests_leave_rules_open(tmp_path):
    from lab.week2 import acceptance

    assert acceptance(VERSIONS_REFERENCE, "versions-backlog") == {"passed": 17, "total": 17, "failed": []}
    workspace = tmp_path / "ws"
    shutil.copytree(VERSIONS, workspace)
    stub = subprocess.run([sys.executable, str(VERIFY), str(workspace)], capture_output=True, text=True)
    assert stub.returncode == 1 and json.loads(stub.stdout)["passed"] == 0
    shutil.copy(VERSIONS_REFERENCE / "versions.py", workspace / "versions.py")
    starter = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=workspace, capture_output=True, text=True)
    assert starter.returncode == 0, starter.stderr
    starter_names = (VERSIONS / "tests" / "test_versions.py").read_text()
    assert "prerelease" in starter_names and "satisfies" in starter_names  # some, not all, rules are covered
    items = [line for line in (VERSIONS / "BACKLOG.md").read_text().splitlines() if line.startswith("- [ ]")]
    assert len(items) == 4


def test_differential_check_agrees_with_the_reference_and_catches_a_hidden_bug(tmp_path):
    from lab.week2 import differential

    for kind, ref in (("durations", REFERENCE), ("sizes", SIZES_REFERENCE), ("versions", VERSIONS_REFERENCE)):
        result = differential(ref, f"{kind}-backlog")
        assert result["total"] > 1000 and result["agree"] == result["total"], (kind, result["samples"])
    # rule 2 allows whitespace between parts; rejecting "1d 1m1s" (a space, then parts written together)
    # still passes the per-rule suite, as one official run did
    source = (REFERENCE / "durations.py").read_text()
    broken = source.replace("    if s.startswith(\"-\"):", "    if re.search(r\"\\s\\d+[dhms]\\d\", s, re.IGNORECASE):\n        raise ValueError(text)\n    if s.startswith(\"-\"):", 1)
    assert broken != source
    (tmp_path / "durations.py").write_text(broken)
    from lab.week2 import acceptance

    assert acceptance(tmp_path, "durations-backlog")["passed"] == 13
    result = differential(tmp_path, "durations-backlog")
    assert result["agree"] < result["total"] and result["samples"]


def _session(path, events):
    path.write_text("\n".join(json.dumps(e) for e in events))


def test_loop_end_undoes_the_parent_edits_made_after_the_loop(tmp_path):
    from lab.week2 import after_loop, loop_end_acceptance

    run_dir = tmp_path / "run"
    shutil.copytree(REFERENCE, run_dir / "workspace")
    final = (run_dir / "workspace" / "durations.py").read_text()
    fix = {"file_path": "/elsewhere/workspace/durations.py", "old_string": "def format(seconds: int, *, iso: bool = False) -> str:  # noqa: A001\n",
           "new_string": "def format(seconds: int, *, iso: bool = False) -> str:  # noqa: A001\n    # audited\n"}
    (run_dir / "workspace" / "durations.py").write_text(final.replace(fix["old_string"], fix["new_string"]))
    broken_before = {**fix, "old_string": fix["old_string"] + "    raise NotImplementedError\n", "new_string": fix["new_string"]}
    _session(run_dir / "dsh-session.jsonl", [
        {"type": "tool/call", "data": {"name": "edit", "id": "e0", "arguments": json.dumps({"file_path": "durations.py", "old_string": "x", "new_string": "y"})}},
        {"type": "tool/call", "data": {"name": "ralph", "id": "loop1", "arguments": "{}"}},
        {"type": "tool/result", "data": {"message": {"toolCallId": "loop1"}}},
        {"type": "tool/call", "data": {"name": "bash", "id": "b1", "arguments": json.dumps({"command": "python3 -m unittest"})}},
        {"type": "tool/call", "data": {"name": "edit", "id": "e1", "arguments": json.dumps(broken_before)}},
        {"type": "tool/call", "data": {"name": "edit", "id": "e2", "arguments": json.dumps({"file_path": "tests/test_durations.py", "old_string": "a", "new_string": "b"})}},
    ])
    after = after_loop(run_dir, "durations-backlog")
    assert after["calls"] == 3 and after["shell_writes"] == 0 and after["module_edits"] == [broken_before]  # before the loop and test files: not counted
    loop_end = loop_end_acceptance(run_dir, "durations-backlog", after["module_edits"], tmp_path / "scratch")
    assert loop_end["exact"] and loop_end["passed"] < 13  # the loop left format unimplemented; the parent finished it
    assert after_loop(tmp_path, "durations-backlog") is None  # no DSH session log


def test_beyond_pass_rate_flags_a_verifier_stop_over_a_continue_report():
    from lab.week2 import one_item_rounds, stopped_on_continue

    rounds = [{"round": n, "status": "continue", "verify_exit": 1 if n < 3 else 0, "decision": ""} for n in (1, 2, 3)]
    early = {"loop": "verified_ralph ended as verified after 3 rounds.", "status": "ok", "rounds": rounds, "backlog": "4/4", "loop_calls": 1}
    assert stopped_on_continue(early) and not one_item_rounds(early)
    done = {**early, "rounds": rounds[:2] + [{**rounds[2], "round": 3}, {"round": 4, "status": "complete", "verify_exit": 0, "decision": ""}]}
    assert not stopped_on_continue(done) and one_item_rounds(done)
