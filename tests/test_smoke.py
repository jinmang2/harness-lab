"""Keyless end-to-end checks through the mock gateway.

    uv run pytest            # lab engine only
    LAB_TEST_DSH=1 uv run pytest   # also DeepSeek Harness (needs `lab dsh-install`)
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from lab import RUNS_DIR, dsh, gateway
from lab.runner import Task, run_batch
from lab.trace import read_events, summarize

TASK = Task(id="smoke", prompt="Run a command and report.")


@pytest.fixture(scope="module")
def mock_gateway(tmp_path_factory):
    server = gateway.serve("mock", port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    old = {k: os.environ.get(k) for k in ("DEEPSEEK_BASE_URL", "DEEPSEEK_API_KEY", "LAB_MODEL_SPEC")}
    os.environ["DEEPSEEK_BASE_URL"] = f"http://127.0.0.1:{server.server_address[1]}"
    os.environ["DEEPSEEK_API_KEY"] = "test"
    os.environ.pop("LAB_MODEL_SPEC", None)
    yield
    server.shutdown()
    for key, value in old.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _runs(batch_dir: Path) -> dict[str, dict]:
    return {json.loads(line)["run_id"]: json.loads(line) for line in (batch_dir / "summary.jsonl").read_text().splitlines()}


def test_lab_harnesses_run_and_trace(mock_gateway):
    combos = [("lab", h) for h in ("minimal", "standard", "prompt-only", "hooks")]
    batch_dir = run_batch([TASK], combos, label="pytest")
    runs = _runs(batch_dir)

    minimal = runs["smoke__lab-minimal__1"]
    assert minimal["status"] == "ok"
    assert minimal["tools_used"] == {"bash": 1}
    assert minimal["first_request"]["tools"] == ["bash"]

    standard = runs["smoke__lab-standard__1"]
    assert standard["tools_used"] == {"execute": 1}
    assert standard["first_request"]["tool_count"] > minimal["first_request"]["tool_count"]
    assert standard["first_request"]["input_billed"] > minimal["first_request"]["input_billed"]

    assert runs["smoke__lab-prompt-only__1"]["tool_calls"] == 0

    hooks = [e for e in read_events(batch_dir / "smoke__lab-hooks__1" / "trace.jsonl") if e["kind"] == "hook"]
    order = [(e["label"], e["hook"]) for e in hooks[:4]]
    assert order == [("outer", "before_agent"), ("inner", "before_agent"), ("outer", "before_model"), ("inner", "before_model")]

    wire = read_events(batch_dir / "smoke__lab-minimal__1" / "wire.jsonl")
    assert len(wire) == minimal["llm_calls"]
    assert (batch_dir / "report.md").read_text().count("## smoke") == 1


@pytest.mark.skipif(not os.environ.get("LAB_TEST_DSH"), reason="set LAB_TEST_DSH=1 (needs `lab dsh-install`)")
def test_dsh_minimal_matches_preset(mock_gateway):
    if not dsh.bin_path().exists():
        pytest.skip("DeepSeek Harness not installed")
    batch_dir = run_batch([TASK], [("dsh", "minimal"), ("dsh", "standard")], label="pytest-dsh")
    runs = _runs(batch_dir)
    minimal = runs["smoke__dsh-minimal__1"]
    assert minimal["status"] == "ok", minimal["error"]
    assert minimal["tools_used"] == {"bash": 1}
    wire = read_events(batch_dir / "smoke__dsh-minimal__1" / "wire.jsonl")
    agent_calls = [w for w in wire if w["tools"]]
    body = json.loads(gateway.body_path(agent_calls[0]["id"]).read_text())
    system = [m["content"] for m in body["messages"] if m["role"] == "system"]
    assert system == ["You are a helpful software engineer assistant."]
    assert runs["smoke__dsh-standard__1"]["first_request"]["tool_count"] > 10


def test_new_harnesses_eval_and_judge(mock_gateway, monkeypatch):
    tasks_file = Path(__file__).resolve().parent.parent / "tasks" / "delegation.yaml"
    from lab.runner import load_tasks

    task = load_tasks(tasks_file, ["usd-orders"])[0]
    batch_dir = run_batch([task], [("lab", "hitl"), ("lab", "delegate")], label="pytest-eval", judge=True, tasks_file=tasks_file)
    runs = _runs(batch_dir)
    hitl = runs["usd-orders__lab-hitl__1"]
    assert hitl["interrupts"] == 1 and hitl["tools_used"] == {"execute": 1}
    assert hitl["tool_selection"] == {"accuracy": 1.0, "required_met": True, "off_target": []}
    assert hitl["quality"] == 3  # mock judge
    assert (batch_dir / "usd-orders__lab-hitl__1" / "judge.json").exists()

    monkeypatch.setenv("LAB_HITL", "reject")
    rejected = _runs(run_batch([task], [("lab", "hitl")], label="pytest-reject"))["usd-orders__lab-hitl__1"]
    assert rejected["interrupts"] == 1 and rejected["tool_calls"] == 0
    assert rejected["tool_selection"]["required_met"] is False


def test_context_harnesses_run(mock_gateway):
    from lab.runner import load_tasks

    task = load_tasks(Path(__file__).resolve().parent.parent / "tasks" / "context.yaml", ["log-stats"])[0]
    runs = _runs(run_batch([task], [("lab", h) for h in ("ctx-prune", "ctx-edit", "ctx-summarize")], label="pytest-ctx"))
    assert all(r["status"] == "ok" and r["tools_used"] == {"bash": 1} for r in runs.values())


def test_playground_flow(mock_gateway):
    import time
    import urllib.request

    from lab.viewer.server import serve

    server = serve(port=0, play=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/api"

    def call(path, body=None, header=True):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET")
        req.add_header("Content-Type", "application/json")
        if header:
            req.add_header("X-Lab", "1")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def wait(sid, status):
        for _ in range(100):
            _, d = call(f"/play/{sid}/events?after=0")
            if d["status"] == status:
                return d
            time.sleep(0.1)
        raise AssertionError(f"never reached {status}: {d['status']}")

    try:
        assert call("/play/start", {"harness": "hitl"}, header=False)[0] == 403
        status, s = call("/play/start", {"harness": "hitl"})
        assert status == 200
        sid = s["id"]
        assert call(f"/play/{sid}/send", {"text": "make a README"})[0] == 200
        d = wait(sid, "waiting")
        assert [e for e in d["items"] if e["type"] == "interrupt"][0]["actions"][0]["name"] == "execute"
        status, r = call(f"/play/{sid}/send", {"text": "again"})
        assert status == 200 and r["state"] == "queued"  # DSH queues a message sent while the turn waits
        qid = call(f"/play/{sid}/events?after=0")[1]["queue"][0]["id"]
        assert call(f"/play/{sid}/queue/{qid}", {"action": "steer"})[0] == 409  # a waiting turn takes no steering
        assert call(f"/play/{sid}/queue/{qid}", {"action": "remove"})[0] == 200
        assert call(f"/play/{sid}/resume", {"decision": "approve"})[0] == 200
        d = wait(sid, "idle")
        types = [e["type"] for e in d["items"]]
        assert "token" in types and "tool_end" in types and types[-2:] == ["final", "turn_end"]
        assert call(f"/play/{sid}/send", {"text": "thanks"})[0] == 200  # multi-turn
        d = wait(sid, "waiting")  # mock calls a tool again -> another approval
        summaries = [json.loads(x) for x in (RUNS_DIR / s["batch"] / "summary.jsonl").read_text().splitlines() if x]
        summary = next(x for x in summaries if x["run_id"] == s["run_id"])
        assert summary["interrupts"] >= 1 and summary["llm_calls"] >= 2
    finally:
        server.shutdown()


def test_playground_guards(mock_gateway):
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    from lab.viewer.server import serve

    server = serve(port=0, play=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/api"

    def post(path, raw):
        req = urllib.request.Request(base + path, data=raw, method="POST", headers={"X-Lab": "1", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    try:
        assert post("/play/start", b'{"harness": "/../../escaped"}')[0] == 409
        assert not (RUNS_DIR.parent / "escaped").exists()
        assert post("/play/start", b"[]")[0] == 400
        _, s = post("/play/start", b'{"harness": "hitl"}')  # first turn stops at an approval, so it cannot finish early
        with ThreadPoolExecutor(12) as pool:
            replies = list(pool.map(lambda _: post(f"/play/{s['id']}/send", b'{"text": "hi"}'), range(12)))
        states = [r[1].get("state") for r in replies]
        assert states.count("started") == 1 and states.count("queued") == 11, states  # exactly one turn may start
    finally:
        server.shutdown()


def _ui(play=True):
    import urllib.request

    from lab.viewer.server import serve

    server = serve(port=0, play=play)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/api"

    def call(path, body=None, raw=False):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(base + path, data=data, method="POST" if body is not None else "GET",
                                     headers={"X-Lab": "1", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as r:
                payload = r.read()
                return r.status, (payload if raw else json.loads(payload))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    return server, call


def test_settings_are_write_only(monkeypatch, tmp_path):
    from lab import DOTENV_KEYS, settings

    env_file = tmp_path / ".env"
    env_file.write_text("# keep me\nLAB_MODEL=deepseek-v4-pro\n")
    monkeypatch.setattr(settings, "ENV_FILE", env_file)
    for key in ("DEEPSEEK_API_KEY", "LAB_MODEL"):
        monkeypatch.delenv(key, raising=False)
    server, call = _ui()
    secret = "sk-test-SECRET-123"
    try:
        status, st = call("/settings", {"DEEPSEEK_API_KEY": secret, "LAB_MODEL": "deepseek-v4-flash"})
        assert status == 200 and st["secrets"]["DEEPSEEK_API_KEY"] == {"configured": True, "source": ".env"}
        _, raw = call("/settings", raw=True)
        assert secret.encode() not in raw  # never sent back
        text = env_file.read_text()
        assert "# keep me" in text and f"DEEPSEEK_API_KEY={secret}" in text and "LAB_MODEL=deepseek-v4-flash" in text
        assert text.count("LAB_MODEL=") == 1 and oct(env_file.stat().st_mode & 0o777) == "0o600"
        assert os.environ["DEEPSEEK_API_KEY"] == secret  # applies to this process now
        assert call("/settings", {"NOT_A_SETTING": "x"})[0] == 409
        assert call("/settings", {"LAB_MODEL": "a\nEVIL=1"})[0] == 409
        assert call("/settings", {"LAB_THINKING": "sometimes"})[0] == 409
        assert call("/settings", {"DEEPSEEK_API_KEY": None})[1]["secrets"]["DEEPSEEK_API_KEY"]["configured"] is False
        assert "DEEPSEEK_API_KEY" not in env_file.read_text()
        r_server, r_call = _ui(play=False)
        assert r_call("/settings", {"LAB_MODEL": "x"})[0] == 403 and r_call("/settings")[0] == 404  # read-only viewer
        r_server.shutdown()
    finally:
        server.shutdown()
        DOTENV_KEYS.discard("DEEPSEEK_API_KEY")
        DOTENV_KEYS.discard("LAB_MODEL")


def test_anatomy_and_export(mock_gateway):
    from lab.harnesses.minimal import PROMPT

    server, call = _ui(play=False)  # anatomy and export are read-only features
    try:
        _, a = call("/anatomy/lab/minimal")
        assert [t["name"] for t in a["tools"]] == ["bash"] and a["system_prompt"] == PROMPT
        assert [m["name"] for m in a["middleware"]] == ["ShellToolMiddleware"]
        _, a = call("/anatomy/lab/delegate")
        assert "SubAgentMiddleware" in [m["name"] for m in a["middleware"]]
        assert {"researcher", "coder"} <= {s["name"] for s in a["subagents"]}
        _, d = call("/anatomy/dsh/minimal")
        assert [p["file"] for p in d["patches"]] == ["common.yml", "minimal.yml"]
        assert call("/anatomy/lab/nope")[0] == 404

        batch = run_batch([TASK], [("lab", "minimal")], label="pytest-export")
        status, data = call(f"/export/{batch.name}/smoke__lab-minimal__1", raw=True)
        import io
        import zipfile

        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        assert status == 200 and "smoke__lab-minimal__1/trace.jsonl" in names
    finally:
        server.shutdown()


def test_stop_then_continue(mock_gateway):
    from langchain_core.callbacks import BaseCallbackHandler

    from lab.viewer.play import PlaySession

    session = PlaySession("minimal")

    class StopAfterModel(BaseCallbackHandler):  # Stop lands after the model asked for a tool
        def on_llm_end(self, *a, **k):
            session.cancel_requested = True

    session.config["callbacks"].append(StopAfterModel())
    session.status, session._turn = "running", {"t_start": 0}
    session.turns.append("run something")
    session._run({"messages": [{"role": "user", "content": "run something"}]})
    assert session.status == "idle" and "cancelled" in [e["type"] for e in session.events]
    assert not [e for e in session.recorder.events if e["kind"] == "tool"]  # the tool never ran
    session.config["callbacks"].pop()
    session.send("continue")  # dangling tool call was answered, so this turn is valid
    for _ in range(100):
        if session.status != "running":
            break
        import time

        time.sleep(0.1)
    assert session.status == "idle", session.error


def test_jobs_and_gateway_control(mock_gateway):
    import time

    from lab.viewer import gateway_control

    server, call = _ui()
    try:
        assert call("/jobs/run", {"harnesses": ["../x"]})[0] == 409
        assert call("/jobs/run", {"harnesses": ["minimal"], "tasks_file": "../secrets"})[0] == 409
        status, job = call("/jobs/run", {"tasks_file": "week1", "tasks": ["readme-structure"], "harnesses": ["minimal"],
                                         "engines": ["lab"], "label": "pytest-job"})
        assert status == 200
        for _ in range(300):
            _, job = call(f"/jobs/{job['id']}")
            if job["status"] != "running":
                break
            time.sleep(0.1)
        assert job["status"] == "done", job["lines"][-20:]
        assert job["batch"] and (RUNS_DIR / job["batch"] / "summary.jsonl").is_file()

        before = os.environ["DEEPSEEK_BASE_URL"]
        st = gateway_control.start("mock", port=0)
        assert st["running"] and os.environ["DEEPSEEK_BASE_URL"] == st["url"] != before
        assert call("/settings", {"DEEPSEEK_BASE_URL": "http://elsewhere"})[0] == 409  # not while routed
        gateway_control.stop()
        assert os.environ["DEEPSEEK_BASE_URL"] == before
    finally:
        gateway_control.stop()
        server.shutdown()


@pytest.mark.skipif(not os.environ.get("LAB_TEST_DSH"), reason="set LAB_TEST_DSH=1 (needs `lab dsh-install`)")
def test_dsh_chat_session(mock_gateway):
    import time

    from lab.viewer.play import PlaySession

    session = PlaySession("minimal", engine="dsh", effort="off")
    assert session.env == {"LAB_THINKING": "disabled"}
    for text in ("first", "second"):
        session.send(text)
        for _ in range(600):
            if session.status != "running":
                break
            time.sleep(0.1)
        assert session.status == "idle", session.error
    types = [e["type"] for e in session.events]
    assert types.count("turn_end") == 2 and "tool_end" in types and "token" in types
    summary = summarize(read_events(session.run_dir / "trace.jsonl"))
    assert summary["engine"] == "dsh" and summary["llm_calls"] >= 2


def test_judge_parsing_and_nesting():
    from uuid import uuid4

    from lab.evaluate import _parse_json
    from lab.viewer.play import _Stream

    assert _parse_json('note {not json} then ```json\n{"overall": 4, "scores": {}}\n```') == {"overall": 4, "scores": {}}

    class FakeSession:
        tool_runs: set = set()

        def emit(self, *a, **k):
            pass

    stream = _Stream(FakeSession())
    root, tool, sub_graph, sub_node = uuid4(), uuid4(), uuid4(), uuid4()
    stream.on_chain_start({}, {}, run_id=root)
    stream.on_tool_start({"name": "task"}, "", run_id=tool, parent_run_id=root)
    stream.on_chain_start({}, {}, run_id=sub_graph, parent_run_id=tool)
    stream.on_chain_start({}, {}, run_id=sub_node, parent_run_id=sub_graph)
    assert stream._inside_tool(sub_node) is True  # subagent model call, two levels below the tool
    assert stream._inside_tool(root) is False


def test_review_regressions(monkeypatch, tmp_path):
    """Fixes from review: .env injection, task-file paths, bad bodies, secret-free shells, process cleanup."""
    import subprocess
    import time
    from concurrent.futures import ThreadPoolExecutor

    import langchain.agents

    from lab import load_dotenv, settings
    from lab.anatomy import anatomy
    from lab.harnesses import BuildContext
    from lab.harnesses.standard import backend
    from lab.viewer.jobs import run_argv

    env_file = tmp_path / ".env"
    monkeypatch.setattr(settings, "ENV_FILE", env_file)
    for bad in ("x\x0bEVIL=1", "x EVIL=1", "x\x85EVIL=1", "x\x00y", "x\x1bz", 5):
        with pytest.raises(ValueError):
            settings.update({"LAB_MODEL": bad})
    assert not env_file.exists()
    env_file.write_text("A=1\x0bEVIL=1\n")  # written by hand: only \n separates lines when loading
    monkeypatch.delenv("EVIL", raising=False)
    load_dotenv(env_file)
    assert "EVIL" not in os.environ

    for stem in ("/tmp/x/evil", "../runs/evil", "week1/../../x", ["week1"]):
        with pytest.raises(ValueError):
            run_argv({"tasks_file": stem, "harnesses": ["minimal"]})
    for body in ({"harnesses": "minimal"}, {"harnesses": ["minimal"], "tasks": [{}]}, {"harnesses": ["minimal"], "repeat": [1]}):
        with pytest.raises(ValueError):
            run_argv(body)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-should-not-leak")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "lf-should-not-leak")
    out = backend(BuildContext(model=None, model_name="x", workdir=tmp_path)).execute("env").output
    assert "should-not-leak" not in out and "PATH=" in out

    real = langchain.agents.create_agent
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(anatomy, ["minimal", "standard", "hitl", "minimal"]))
    assert langchain.agents.create_agent is real  # concurrent builds restore the original

    # a run's whole process group goes away, including a shell it left in the background
    proc = subprocess.Popen(["bash", "-c", "sleep 60 & echo $!; wait"], stdout=subprocess.PIPE, start_new_session=True)
    child = int(proc.stdout.readline())
    dsh._kill_group(proc, grace_s=1)
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)
    assert dsh._safe_prompt("--help") == " --help" and dsh._safe_prompt("hi -x") == "hi -x"


def test_ui_static_workspaces_approval_and_archive(mock_gateway, tmp_path):
    """React UI is served; workspaces, per-session files, approval mode, archived sessions after restart."""
    import time

    from lab.viewer.play import PlayRegistry

    server, call = _ui()
    try:
        import urllib.request

        base = f"http://127.0.0.1:{server.server_address[1]}"
        with urllib.request.urlopen(base + "/") as r:
            page = r.read().decode()
        asset = page.split('src="/assets/')[1].split('"')[0]
        with urllib.request.urlopen(f"{base}/assets/{asset}") as r:
            assert r.headers["Content-Type"].startswith("text/javascript")

        folder = tmp_path / "proj"
        folder.mkdir()
        (folder / "notes.txt").write_text("hello")
        assert call("/workspaces/add", {"path": "relative/path"})[0] == 409
        assert call("/workspaces/add", {"path": str(folder)})[0] == 200
        assert call("/play/start", {"harness": "minimal", "workspace": "/not/registered"})[0] == 409
        status, s = call("/play/start", {"harness": "minimal", "workspace": str(folder), "approval": "ask"})
        assert status == 200 and s["workdir"] == str(folder) and s["approval"] == "ask"
        assert call("/play/start", {"harness": "minimal", "approval": "sometimes"})[0] == 409
        assert call(f"/play/{s['id']}/send", {"text": "list files"})[0] == 200
        for _ in range(100):
            _, d = call(f"/play/{s['id']}/events?after=0")
            if d["status"] == "waiting":
                break
            time.sleep(0.1)
        assert d["status"] == "waiting"  # ask mode paused the shell call
        assert any(e["type"] == "request" and e["tools"] == ["bash"] for e in d["items"])
        _, files = call(f"/play/{s['id']}/files")
        assert [f["path"] for f in files] == ["notes.txt"]
        assert call(f"/play/{s['id']}/file?path=notes.txt", raw=True)[1] == b"hello"
        assert call(f"/play/{s['id']}/file?path=../../etc/passwd")[0] == 404
        assert call(f"/play/{s['id']}/resume", {"decision": "reject"})[0] == 200
        for _ in range(100):
            _, d = call(f"/play/{s['id']}/events?after=0")
            if d["status"] == "idle":
                break
            time.sleep(0.1)
        assert d["status"] == "idle"
    finally:
        server.shutdown()

    reborn = PlayRegistry()  # what a restarted `lab ui` sees
    old = reborn.get(s["id"])
    assert old.describe()["status"] == "archived" and old.events_after(0)
    with pytest.raises(ValueError):
        old.send("again")


def test_week1_writeup(mock_gateway):
    from lab.week1 import build

    tasks = [Task(id="seoul-weather", prompt="오늘 서울 날씨는 어땠어?"),
             Task(id="weekday", prompt="2026년 12월 25일은 무슨 요일이야?", expect="금요일|Friday")]
    batch = run_batch(tasks, [("lab", "minimal"), ("lab", "standard")], label="pytest-week1",
                      tasks_file=Path(__file__).resolve().parent.parent / "tasks" / "week1-assignment.yaml")
    runs = _runs(batch)
    assert runs["weekday__lab-minimal__1"]["check"] is False  # mock answers MOCK_DONE, not a weekday
    assert runs["weekday__lab-minimal__1"]["turn_ms"] is not None
    text = build(batch, "tester")
    assert "## 1. 실험 질문" in text and "| 전체 토큰 |" in text and "## 3. 전체 후보 결과" in text


def test_review2_regressions(mock_gateway, tmp_path):
    import time

    from lab.viewer import workspaces
    from lab.viewer.play import PlayRegistry, PlaySession
    from lab.week1 import aggregate, minimal_advantage

    # archived sessions keep the closing events of their last turn
    s = PlaySession("minimal")
    s.send("hi")
    for _ in range(100):
        if s.status != "running":
            break
        time.sleep(0.1)
    old = PlayRegistry().get(s.id)
    assert [e["type"] for e in old.events_after(0)][-2:] == ["final", "turn_end"]

    # secrets in a workspace are neither listed nor served
    (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=sk-x")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "config").write_text("x")
    (tmp_path / "id_ed25519").write_text("x")
    (tmp_path / "ok.txt").write_text("fine")
    assert [f["path"] for f in workspaces.files(tmp_path)] == ["ok.txt"]
    assert workspaces.read(tmp_path, ".env") is None and workspaces.read(tmp_path, "a\0b") is None
    assert workspaces.read(tmp_path, "ok.txt") == b"fine"

    # a crashed Minimal run is never "better"
    good = {"status": "ok", "check": None, "total_tokens": 1000, "input_billed": 900, "output": 100, "wall_ms": 3000, "tools_used": [], "tool_calls": 0, "final": "x"}
    crash = {**good, "status": "error", "total_tokens": 0, "input_billed": 0, "output": 0, "wall_ms": 0, "final": ""}
    wins, _, _ = minimal_advantage(aggregate([crash, crash]), aggregate([good, good]))
    assert not wins


def test_bash_output_without_trailing_newline(tmp_path):
    """LangChain's shell waits for its done marker at a line start; `printf x` used to hang 300s."""
    from lab.harnesses.common import persistent_bash

    resources = persistent_bash(tmp_path)._create_resources()  # keep: its finalizer stops the shell
    session = resources.session
    try:
        for command, output, code in [("printf abc", "abc", 0), ("echo hi", "hi\n", 0), ("printf x; false", "x", 1)]:
            result = session.execute(command, timeout=5)
            assert (result.output, result.exit_code, result.timed_out) == (output, code, False)
    finally:
        session.stop(2)


def test_plan_mode_and_questions(mock_gateway):
    """DSH plan mode + ask_user_question in the chat UI: /plan, question takeover, plan review."""
    import time
    import urllib.request

    from lab.viewer.server import serve

    server = serve(port=0, play=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/api"

    def call(path, body=None):
        req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                     method="POST" if body is not None else "GET")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Lab", "1")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def wait(sid, status):
        for _ in range(100):
            _, d = call(f"/play/{sid}/events?after=0")
            if d["status"] == status:
                return d
            time.sleep(0.1)
        raise AssertionError(f"never reached {status}: {d['status']}")

    try:
        _, minimal = call("/play/start", {"harness": "minimal"})
        assert minimal["supports_plan"] is False and call(f"/play/{minimal['id']}/plan", {"active": True})[0] == 409

        _, s = call("/play/start", {"harness": "standard"})
        sid = s["id"]
        assert s["supports_plan"] is True and s["plan_mode"] is False
        status, r = call(f"/play/{sid}/plan", {"active": True, "message": "[mock:ask] pick a color"})
        assert status == 200 and r["text"] == "Plan mode on. Use /plan off to leave."

        d = wait(sid, "waiting")
        assert d["plan_mode"] is True
        q = [e for e in d["items"] if e["type"] == "question"][-1]
        assert q["qkind"] == "question" and q["questions"][0]["id"] == "color"
        assert call(f"/play/{sid}/resume", {"decision": "approve"})[0] == 409  # questions are answered, not approved
        assert call(f"/play/{sid}/answer", {"answers": [{"id": "color", "selected": ["Blue (Recommended)"]}]})[0] == 200
        d = wait(sid, "idle")
        asks = [e for e in d["items"] if e["type"] == "tool_start" and e["name"] == "ask_user_question"]
        ends = [e for e in d["items"] if e["type"] == "tool_end" and e["name"] == "ask_user_question"]
        assert len(asks) == 1 and len(ends) == 1 and ends[0]["run_id"] == asks[0]["run_id"]  # one card across the pause
        assert json.loads(ends[0]["preview"]) == {"answers": [{"id": "color", "selected": ["Blue (Recommended)"]}]}

        assert call(f"/play/{sid}/send", {"text": "[mock:plan] now plan it"})[0] == 200
        d = wait(sid, "waiting")
        review = [e for e in d["items"] if e["type"] == "question"][-1]
        assert review["qkind"] == "plan-review" and review["title"] == "Add a --greeting flag"
        assert review["questions"][0]["intent"] == {"kind": "plan-review", "approve": "Approve"}
        assert call(f"/play/{sid}/answer", {"answers": [{"id": "plan-review", "selected": ["Approve"]}]})[0] == 200
        d = wait(sid, "idle")
        assert d["plan_mode"] is False and [e for e in d["items"] if e["type"] == "plan_mode"][-1]["active"] is False
        plan_end = [e for e in d["items"] if e["type"] == "tool_end" and e["name"] == "exit_plan_mode"][-1]
        assert plan_end["preview"].startswith("Plan approved") and not plan_end["error"]

        # Cancelling a question is the user's own choice: the model is told so and the turn ends normally.
        assert call(f"/play/{sid}/send", {"text": "[mock:ask] again"})[0] == 200
        wait(sid, "waiting")
        assert call(f"/play/{sid}/answer", {"cancelled": True})[0] == 200
        d = wait(sid, "idle")
        end = [e for e in d["items"] if e["type"] == "tool_end" and e["name"] == "ask_user_question"][-1]
        assert end["error"] and "cancelled" in end["preview"]

        # Two identical questions in one step: answered one at a time, each keeps its own card.
        assert call(f"/play/{sid}/send", {"text": "[mock:ask2] twice"})[0] == 200
        for pick in ("Green", "Blue (Recommended)"):
            wait(sid, "waiting")
            assert call(f"/play/{sid}/answer", {"answers": [{"id": "color", "selected": [pick]}]})[0] == 200
        d = wait(sid, "idle")
        turn = d["items"][max(i for i, e in enumerate(d["items"]) if e["type"] == "user"):]
        starts = [e["run_id"] for e in turn if e["type"] == "tool_start"]
        ends = [e for e in turn if e["type"] == "tool_end"]
        assert len(starts) == 2 and sorted(e["run_id"] for e in ends) == sorted(starts)
        assert sorted(json.loads(e["preview"])["answers"][0]["selected"][0] for e in ends) == ["Blue (Recommended)", "Green"]
        summaries = [json.loads(x) for x in (RUNS_DIR / s["batch"] / "summary.jsonl").read_text().splitlines() if x]
        assert next(x for x in summaries if x["run_id"] == s["run_id"])["interrupts"] >= 5  # answers count as interrupts

        # `/plan` on the start page with a preset that has no plan mode: refused, nothing left behind.
        before = set((RUNS_DIR / s["batch"]).iterdir())
        assert call("/play/start", {"harness": "minimal", "plan": True})[0] == 409
        assert set((RUNS_DIR / s["batch"]).iterdir()) == before
        status, planned = call("/play/start", {"harness": "standard", "plan": True})
        assert status == 200 and planned["plan_mode"] is True
        assert (RUNS_DIR / planned["batch"] / planned["run_id"] / "session.json").is_file()  # saved without any turn
    finally:
        server.shutdown()


def test_collaboration_tools_without_a_person(tmp_path):
    """Batch runs (like DSH headless) have no one to answer: the tools fail instead of hanging."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage

    from lab.harnesses import BuildContext, get

    class Fake(GenericFakeChatModel):
        def bind_tools(self, tools, **kw):  # the fake ignores tool schemas
            return self

    model = Fake(messages=iter([
        AIMessage("", tool_calls=[{"id": "a", "name": "ask_user_question", "args": {"questions": [{"id": "x", "question": "?"}]}},
                                  {"id": "b", "name": "exit_plan_mode", "args": {"plan": "# P"}}]),
        AIMessage("done"),
    ]))
    out = get("standard").build(BuildContext(model=model, model_name="fake", workdir=tmp_path)).invoke({"messages": [{"role": "user", "content": "go"}]})
    results = {m.name: m for m in out["messages"] if m.type == "tool"}
    assert results["ask_user_question"].content == "no user-questions answerer accepted the request"
    assert results["exit_plan_mode"].content == "exit_plan_mode is only available in plan mode"


def test_queue_steer_goal_fork_upload_model(mock_gateway):
    """DSH Web's remaining chat features on the lab engine."""
    import base64
    import time
    import urllib.request

    from lab.viewer.server import serve

    server = serve(port=0, play=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}/api"

    def call(path, body=None):
        req = urllib.request.Request(base + path, data=None if body is None else json.dumps(body).encode(),
                                     method="POST" if body is not None else "GET")
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Lab", "1")
        try:
            with urllib.request.urlopen(req) as r:
                raw = r.read()
                return r.status, json.loads(raw) if r.headers.get_content_type() == "application/json" else raw
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def wait(sid, pred, what):
        for _ in range(150):
            _, d = call(f"/play/{sid}/events?after=0")
            if pred(d):
                return d
            time.sleep(0.1)
        raise AssertionError(f"never reached {what}: {d['status']}")

    idle = lambda d: d["status"] == "idle" and not d["queue"]  # noqa: E731
    try:
        _, s = call("/play/start", {"harness": "standard"})
        sid = s["id"]

        # queue while running, then it runs as the next turn
        assert call(f"/play/{sid}/send", {"text": "[mock:slow] wait"})[1]["state"] == "started"
        wait(sid, lambda d: d["status"] == "running", "running")
        assert call(f"/play/{sid}/send", {"text": "queued one"})[1]["state"] == "queued"
        _, d = call(f"/play/{sid}/events?after=0")
        assert [q["text"] for q in d["queue"]] == ["queued one"] and d["queue"][0]["target"] == "next-turn"
        qid = d["queue"][0]["id"]
        assert call(f"/play/{sid}/queue/{qid}", {"action": "edit", "text": "queued, edited"})[0] == 200
        d = wait(sid, idle, "queue drained")
        assert [e["text"] for e in d["items"] if e["type"] == "user"] == ["[mock:slow] wait", "queued, edited"]

        # steer: enters the running turn as a plain user message, no new turn
        call(f"/play/{sid}/send", {"text": "[mock:slow] again"})
        wait(sid, lambda d: d["status"] == "running", "running")
        assert call(f"/play/{sid}/send", {"text": "Interjection: say BANANA", "mode": "steer"})[1]["state"] == "queued"
        d = wait(sid, idle, "steered turn done")
        users = [e for e in d["items"] if e["type"] == "user"]
        steers = [e for e in d["items"] if e["type"] == "steer"]
        assert len(users) == 3 and [e["text"] for e in steers] == ["Interjection: say BANANA"]
        assert steers[0]["seq"] > users[-1]["seq"]  # inside the third turn

        # model switch mid-session is recorded and used by the next request
        assert call(f"/play/{sid}/model", {"model": "deepseek-v4-pro", "effort": "off"})[0] == 200
        assert call(f"/play/{sid}/model", {"model": "nope"})[0] == 409

        # uploads: a text file becomes a handle text; an image needs an image-capable model
        _, f = call(f"/play/{sid}/upload", {"name": "notes.txt", "mime": "text/plain", "data": base64.b64encode(b"hello").decode()})
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
        _, img = call(f"/play/{sid}/upload", {"name": "dot.png", "mime": "image/png", "data": base64.b64encode(png).decode()})
        assert f["kind"] == "file" and "path" not in f and img["kind"] == "image" and img["width"] == 1
        assert call(f"/play/{sid}/send", {"text": "look", "attachments": [img["id"]]})[0] == 409  # v4-pro is text-only
        assert call(f"/play/{sid}/attachment/{img['id']}")[1] == png
        assert call(f"/play/{sid}/send", {"text": "read it", "attachments": [f["id"]]})[0] == 200
        d = wait(sid, idle, "file turn")
        assert [e for e in d["items"] if e["type"] == "user"][-1]["attachments"][0]["name"] == "notes.txt"
        bodies = list((RUNS_DIR / "gateway").rglob("*.json"))
        sent = max(bodies, key=lambda p: p.stat().st_mtime).read_text() if bodies else ""
        assert d["model"] == "deepseek-v4-pro" and ("verbatim read-only copy saved at" in sent or not bodies)

        # fork: a new session with the history so far, title (1), same workspace
        status, child = call(f"/play/{sid}/fork", {})
        assert status == 200 and child["title"].endswith("(1)") and child["parent"] == sid and child["workdir"] == s["workdir"]
        _, cd = call(f"/play/{child['id']}/events?after=0")
        assert len([e for e in cd["items"] if e["type"] == "user"]) == 4
        assert call(f"/play/{child['id']}/send", {"text": "continue in the branch"})[0] == 200
        wait(child["id"], idle, "branch turn")

        # goal: /goal creates and arms it, the driver runs a round, the model completes it
        _, g = call("/play/start", {"harness": "standard"})
        gid = g["id"]
        status, r = call(f"/play/{gid}/goal", {"input": ""})
        assert r["text"].startswith("No goal is currently set.")
        status, r = call(f"/play/{gid}/goal", {"input": "Write DONE.md"})
        assert r["ok"] and r["text"].startswith("Goal created\nStatus: active") and "Rounds: 0/256" in r["text"]
        d = wait(gid, lambda d: d["status"] == "idle" and (d["goal"] or {}).get("phase") == "complete", "goal complete")
        rounds = [e for e in d["items"] if e["type"] == "user" and e["source"] == "goal"]
        assert len(rounds) == 1 and rounds[0]["text"].startswith("<goal_round>\nObjective: \"Write DONE.md\"\nRound: 1/256")
        assert d["goal"]["roundsStarted"] == 1 and d["goal"]["activation"] == "disarmed"
        assert call(f"/play/{gid}/goal", {"input": "pause"})[1]["kind"] == "error"  # complete goals cannot pause
        # the model can create a goal from a direct request too
        assert call(f"/play/{gid}/goal", {"input": "clear"})[1]["text"] == "Goal cleared."
        call(f"/play/{gid}/send", {"text": "[mock:goal] keep going until DONE.md exists"})
        d = wait(gid, lambda d: d["status"] == "idle" and (d["goal"] or {}).get("phase") == "complete", "model goal")
        assert d["goal"]["objective"] == "Write DONE.md" and d["goal"]["maxGoalRounds"] == 5

        # minimal has no goal tools
        _, m = call("/play/start", {"harness": "minimal"})
        assert m["supports_goal"] is False and call(f"/play/{m['id']}/goal", {"input": "x"})[0] == 409
    finally:
        server.shutdown()


def test_session_feature_regressions(mock_gateway):
    """Review findings: dispatch after errors, forks of forks, images in forks, pause on stop, steer authority."""
    import base64
    import time

    from lab.middleware.goal import command
    from lab.viewer.play import PlayRegistry

    def settle(s, pred=lambda s: True):
        for _ in range(200):
            if s.status in ("idle", "error") and pred(s):
                return s
            time.sleep(0.05)
        raise AssertionError(f"stuck {s.status}")

    reg = PlayRegistry()
    s = reg.start("standard")
    # after a failed turn, /goal still starts its rounds
    s.status, s.error = "error", "boom"
    kind, text = s.goal_command("Write DONE.md")
    assert kind == "success"
    settle(s, lambda s: s.goal and s.goal["phase"] == "complete")
    assert s.goal["roundsStarted"] == 1
    # DSH wording for an invalid /goal transition
    assert command(s.goal, "pause")[1] == "The goal command is not valid for the current state. Run /goal to view available commands."

    # images survive a fork; a fork of a fork can branch from an earlier turn
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    s.set_model("deepseek-flash", None)  # image-capable
    img = s.upload("a" * 300 + ".png", "image/png", base64.b64encode(png).decode())
    assert len(img["name"]) <= 120 and img["name"].endswith(".png")
    s.send("look", [img["id"]])
    settle(s)
    child = reg.fork(s.id)
    assert child.attachments[img["id"]]["path"].startswith(str(s.run_dir))
    child.send("one more")
    settle(child)
    grand = reg.fork(child.id, 0)  # the first turn: its state lives in the root session's checkpoints
    assert len(grand.agent.get_state(grand.config).values["messages"]) > 0 and grand.title.endswith("(2)")

    # a pause during a user turn is never lost, even if the turn finishes before the stop lands
    s2 = reg.start("standard")
    s2.goal_command("[mock:stay] keep going")
    for _ in range(100):
        if s2.status == "running":
            break
        time.sleep(0.05)
    s2.goal_command("pause")
    settle(s2, lambda s: s.goal["phase"] == "paused")
    assert s2.goal["activation"] == "disarmed"
    time.sleep(0.5)
    assert s2.status == "idle" and s2.goal["roundsStarted"] == 1  # no further round
