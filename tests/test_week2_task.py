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
        suite = "week2_sizes_acceptance.py" if task.id.startswith("sizes") else "week2_acceptance.py"
        assert suite in task.check and task.isolate


def test_week2_grades_each_task_with_its_own_suite():
    from lab.week2 import acceptance

    assert acceptance(SIZES_REFERENCE, "sizes-backlog-goal")["passed"] == 13
    assert acceptance(REFERENCE, "durations-backlog")["passed"] == 13
    for task in load_tasks(ROOT / "tasks" / "week2.yaml"):
        assert task.id.split("-")[0] in ("durations", "sizes")


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
