"""Run DeepSeek Harness through its Web host (0.2.x), with no browser: the `dsh-web` engine.

Headless (`lab.dsh`) answers one turn and exits at the first idle, so it cannot run what
lives past a turn: goal rounds (goal-round-driver) and agent presets (the one-shot runner
does not compose them). The Web host does both. Each run starts its own host on a free
port with an isolated `DSH_HOME` (`.dsh-home-<version>-web/`, never the one a person uses
in the browser), signs in with the launch token, and drives it over the same unary
`/api/<namespace>/<method>` bridge the Web client uses (ADR-0016):

    workspace/create -> session/create {agentPreset} -> session/prompt -> poll session/list + goals/get

A run is done when the agent is idle and no goal is active and armed, three polls in a row.
Session logs (the main one, then the children whose header names it as `parentSession`)
are returned like `lab.dsh.run`, so `lab.dsh.convert_session` reads them.
"""

from __future__ import annotations

import http.cookiejar
import json
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from lab import ROOT
from lab import dsh

VERSION = dsh.WEEK2_VERSION
PATCH_DIR = dsh.PATCH_DIR
BUNDLES = ROOT / "dsh" / "bundles"

# harness -> (patch overlays on the web profile, agent preset of the session)
HARNESSES: dict[str, tuple[list[str], str]] = {
    "standard": (["common.yml"], "standard"),
    "ralph-official": (["common.yml", "web-ralph-official.yml"], "lab-ralph-official"),
    "ralph-custom": (["common.yml"], "verified-ralph"),
    "ralph-custom-tests": (["common.yml", "web-ralph-custom-tests.yml"], "lab-verified-ralph-tests"),
    "ralph-custom-tests-v2": (["common.yml", "web-ralph-custom-tests-v2.yml"], "lab-verified-ralph-tests-v2"),
    "ralph-custom-tests-v3": (["common.yml", "web-ralph-custom-tests-v3.yml"], "lab-verified-ralph-tests-v3"),
    "ralph-custom-tests-v3-low": (["common.yml", "web-ralph-custom-tests-v3-low.yml"], "lab-verified-ralph-tests-v3-low"),
    "goal": (["common.yml", "goal-5.yml"], "standard"),
}
# bundles the web profile needs (installed by `lab dsh-web-setup`)
PROFILE_BUNDLES = ["verified-ralph"]


def home_dir() -> Path:
    return ROOT / f".dsh-home-{VERSION}-web"


def profile_dir() -> Path:
    return home_dir() / "profiles" / "web"


def setup() -> None:
    """Create the web profile and link the repo's bundles into it (Plugin Manager's install, without the UI)."""
    if shutil.which("pnpm") is None:
        raise SystemExit("pnpm is required on PATH: DSH's Plugin Manager installs bundles with `pnpm add`.")
    home = home_dir()
    home.mkdir(exist_ok=True)
    env = {**dsh.environment(VERSION), "DSH_HOME": str(home)}
    for name in PROFILE_BUNDLES:
        subprocess.run([str(dsh.bin_path(VERSION)), "plugin", "--profile", "web", "add", f"link:{BUNDLES / name}"],
                       env=env, check=True)
    print(f"web profile ready: {profile_dir()}")


class RemoteError(RuntimeError):
    def __init__(self, endpoint: str, error: dict[str, Any]) -> None:
        super().__init__(f"{endpoint}: {error.get('code')}: {error.get('message')}")
        self.code = str(error.get("code"))


class Client:
    """Cookie-authenticated unary RPC to `/api/<namespace>/<method>` (dsh-client-connection, dsh-api-gateway)."""

    def __init__(self, url: str, timeout: float = 60.0) -> None:
        parts = urllib.parse.urlsplit(url)
        token = urllib.parse.parse_qs(parts.query)["token"][0]
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        with self.opener.open(f"{self.origin}/?token={urllib.parse.quote(token)}", timeout=timeout) as resp:
            resp.read()  # 303 + Set-Cookie dsh-auth-*; the query token is accepted only on `/`
        if not any(c.name.startswith("dsh-auth-") for c in self.jar):
            raise RuntimeError("the launch token did not yield a dsh-auth cookie")

    def call(self, endpoint: str, args: dict[str, Any] | None = None) -> Any:
        rpc = str(uuid.uuid4())
        body = json.dumps({"type": "client-request", "rpcId": rpc, "method": endpoint, "payload": {"args": args or {}}}).encode()
        req = urllib.request.Request(f"{self.origin}/api/{endpoint}", data=body, method="POST",
                                     headers={"content-type": "application/json"})
        try:
            with self.opener.open(req, timeout=self.timeout) as resp:
                envelope = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"{endpoint}: HTTP {exc.code}: {exc.read()[:300]!r}") from exc
        result = envelope["result"]
        if not result.get("ok"):
            raise RemoteError(endpoint, result["error"])
        return result.get("value")

    def session_row(self, sid: str) -> dict[str, Any]:
        cursor = None
        while True:
            value = self.call("session/list", {"_request": {"cursor": cursor} if cursor else {}})
            for item in value.get("items", []):
                if item.get("sessionId") == sid:
                    return item
            cursor = value.get("nextCursor") or value.get("cursor")
            if not cursor:
                return {}

    def goal(self, sid: str) -> dict[str, Any] | None:
        return self.call("goals/get", {"agentId": sid})  # a root session's agent id is its session id


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Host:
    """One Web host process for one run: own port, the harness's patches, killed (with its group) at the end."""

    def __init__(self, patches: list[str], env: dict[str, str] | None = None) -> None:
        self.port = _free_port()
        cmd = [str(dsh.bin_path(VERSION)), "--profile", "web"]
        for patch in patches:
            cmd += ["--patch", str(PATCH_DIR / patch)]
        cmd += ["--no-open", "--host", "127.0.0.1", "--port", str(self.port)]
        self.output: list[str] = []
        self.proc = subprocess.Popen(cmd, env={**dsh.environment(VERSION), "DSH_HOME": str(home_dir()), **(env or {})},
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True, text=True)
        self.url = self._wait_url()

    def _wait_url(self, timeout_s: float = 60) -> str:
        found: list[str] = []

        def pump() -> None:
            for line in self.proc.stdout:  # type: ignore[union-attr]
                self.output.append(line)
                m = re.search(r"http://127\.0\.0\.1:\d+/\?token=\S+", line)
                if m and not found:
                    found.append(m.group(0))

        threading.Thread(target=pump, daemon=True).start()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline and not found:
            if self.proc.poll() is not None:
                raise RuntimeError("DSH Web exited during startup:\n" + "".join(self.output[-30:]))
            time.sleep(0.2)
        if not found:
            self.stop()
            raise RuntimeError("DSH Web did not print its URL:\n" + "".join(self.output[-30:]))
        return found[0]

    def stop(self) -> None:
        dsh._kill_group(self.proc)
        if self.proc.poll() is None:
            self.proc.wait()


def _settled(goal: dict[str, Any] | None) -> bool:
    return not goal or goal.get("phase") != "active" or goal.get("activation") != "armed"


def _seq(row: dict[str, Any]) -> int:
    seq = (row.get("projections") or {}).get("asOfSeq")
    return int(seq) if isinstance(seq, (int, float)) else -1


def wait_idle(client: Client, sid: str, baseline: int, timeout_s: float, poll_s: float = 1.0, settle: int = 3) -> str:
    """Idle with no armed active goal for `settle` polls in a row; the driver queues the next round right after idle."""
    deadline = time.monotonic() + timeout_s
    active, stable = False, 0
    while time.monotonic() < deadline:
        row = client.session_row(sid)
        running = bool(row.get("running"))
        active = active or running or _seq(row) > baseline
        if active and not running and _settled(client.goal(sid)):
            stable += 1
            if stable >= settle:
                return "idle"
        else:
            stable = 0
        time.sleep(poll_s)
    return "timeout"


def session_logs(sid: str) -> list[Path]:
    """The main session log, then its children (header `parentSession == sid`), oldest first."""
    root = home_dir() / "sessions"
    main = next(root.glob(f"*/{sid}/session.v4.jsonl"), None)
    if main is None:
        return []
    children = [p for p in root.glob("*/*/session.v4.jsonl") if dsh._header(p).get("parentSession") == sid]
    children.sort(key=lambda p: (dsh._header(p).get("createdAt") or "", p.stat().st_mtime))
    return [main, *children]


def final_text(log: Path) -> str:
    """The last assistant text of the session (what DSH Web shows as the answer)."""
    text = ""
    for line in log.read_text(encoding="utf-8").splitlines():
        row = json.loads(line) if line.strip() else {}
        if row.get("type") == "assistant/message":
            parts = [b.get("text", "") for b in (row.get("data", {}).get("message", {}).get("content") or [])
                     if isinstance(b, dict) and b.get("type") == "text"]
            if any(p.strip() for p in parts):
                text = "".join(parts)
    return text


def turn_error(log: Path) -> str:
    """The error of the main session's last turn, or "" when it ended normally."""
    last = None
    for line in log.read_text(encoding="utf-8").splitlines():
        if '"turn/end"' in line:
            last = json.loads(line)
    reason = ((last or {}).get("data") or {}).get("reason") or {}
    if reason.get("kind") != "error":
        return ""
    err = reason.get("error") or {}
    return f"turn ended with an error: {err.get('code', '')} {err.get('message', '')}".strip()


def run(prompt: str, harness: str, workdir: Path, timeout_s: int = 1800, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run one task on a fresh Web host. Same result shape as `lab.dsh.run`."""
    if harness not in HARNESSES:
        raise SystemExit(f"unknown dsh-web harness {harness!r}; known: {', '.join(HARNESSES)}")
    if not dsh.bin_path(VERSION).exists():
        raise SystemExit(f"DeepSeek Harness {VERSION} is not installed: run `uv run lab dsh-install --version {VERSION}`.")
    if not profile_dir().exists():
        raise SystemExit("the dsh-web profile is missing: run `uv run lab dsh-web-setup`.")
    patches, preset = HARNESSES[harness]
    started = time.time()
    t0 = time.perf_counter()
    host = Host(patches, env)
    status, sid, error = "idle", "", ""
    try:
        client = Client(host.url)
        workspace = client.call("workspace/create", {"request": {"path": str(Path(workdir).resolve())}})["workspace"]
        sid = client.call("session/create", {"request": {"workspaceId": workspace["workspaceId"], "agentPreset": preset}})["sessionId"]
        baseline = _seq(client.session_row(sid))
        if prompt.startswith("/"):  # a slash command, as the composer sends it (e.g. `/goal <objective>`, no model call)
            client.call("commands/execute", {"agentId": sid, "line": prompt, "submittedAttachments": []})
        else:
            client.call("session/prompt", {"request": {"requestId": str(uuid.uuid4()), "sessionId": sid, "mode": "queue",
                                                       "content": [{"type": "text", "text": prompt}]}})
        status = wait_idle(client, sid, baseline, timeout_s)
        if status == "timeout":
            goal = client.goal(sid)
            if goal and goal.get("phase") == "active":
                client.call("goals/pause", {"agentId": sid, "ref": {"id": goal["id"], "revision": goal["revision"]}})
            client.call("session/cancel", {"request": {"sessionId": sid}})
    except Exception as exc:  # a failed run is a result
        status, error = "error", repr(exc)
    finally:
        host.stop()
    logs = session_logs(sid) if sid else []
    final = final_text(logs[0]) if logs else ""
    failed = turn_error(logs[0]) if logs and status == "idle" else ""
    if failed:  # the host went idle because the turn died (e.g. the model API was unreachable), not because it finished
        status, error = "error", failed
    return {
        "exit_code": 0 if status == "idle" else 1,
        "stdout": final,
        "stderr": "".join(host.output) + (f"\n[lab] {status}: {error}" if status != "idle" else ""),
        "wall_ms": int((time.perf_counter() - t0) * 1000),
        "session_logs": [str(p) for p in logs],
        "started_ms": int(started * 1000),
        "session_id": sid,
    }


def ralph_preset_patch(standard_patch: str, ralph_rounds: int = 5) -> str:
    """`lab-ralph-official` from the shipped `presets/standard.patch.yml`, as text: only the preset's id and
    name, and its nested tool-ralph row (enabled, maxRounds 5), differ from standard."""
    lines = standard_patch.splitlines()
    out = ["# Generated by lab.dsh_web.ralph_preset_patch from dsh-web-app presets/standard.patch.yml.",
           "# The shipped standard preset with its official tool-ralph row switched on at the week2 ceiling.", ""]
    in_ralph = False
    body = [ln for ln in lines if not ln.startswith("#")]
    for ln in body:
        stripped = ln.strip()
        if stripped == "- id: preset-standard":
            ln = ln.replace("preset-standard", "preset-lab-ralph-official")
        elif stripped == "id: standard":
            indent = ln[: len(ln) - len(ln.lstrip())]
            out += [f"{indent}id: lab-ralph-official", f"{indent}name: Standard + Ralph",
                    f"{indent}description: The shipped standard preset with the official tool-ralph switched on."]
            continue
        elif stripped == "order: 1":
            ln = ln.replace("order: 1", "order: 21")
        if stripped == "- id: tool-ralph":
            in_ralph = True
        elif in_ralph and stripped.startswith("- id:"):
            in_ralph = False
        if in_ralph and stripped == "disabled: true":
            continue
        if in_ralph and stripped.startswith("maxRounds:"):
            ln = ln.replace(stripped, f"maxRounds: {ralph_rounds}")
        out.append(ln)
    return "\n".join(out) + "\n"


PROJECT_TESTS = "python3 -m unittest discover -s tests"


WORKER_TOOLS = ["bash", "read", "edit", "write", "glob", "grep"]
# preset variant -> (preset id, display name, order, description/header note, extra plugin config lines)
CUSTOM_TESTS_VARIANTS: dict[str, tuple[str, str, int, str, list[str]]] = {
    "v1": ("lab-verified-ralph-tests", "Verified RALPH (project tests)", 22, "", []),
    "v2": ("lab-verified-ralph-tests-v2", "Verified RALPH v2 (project tests)", 23,
           " A passing verifier ends the loop only with a worker 'complete'.", ["stopWhen: verifier-and-worker"]),
    "v3": ("lab-verified-ralph-tests-v3", "Verified RALPH v3 (project tests)", 24,
           " A passing verifier ends the loop only with a worker 'complete'; workers get only the coding tools"
           " and a focused brief.",
           ["stopWhen: verifier-and-worker", f"workerTools: [{', '.join(WORKER_TOOLS)}]", "workerProtocol: focused"]),
    "v3-low": ("lab-verified-ralph-tests-v3-low", "Verified RALPH v3 low effort (project tests)", 25,
               " As v3, with workers pinned to low reasoning effort.",
               ["stopWhen: verifier-and-worker", f"workerTools: [{', '.join(WORKER_TOOLS)}]", "workerProtocol: focused",
                "workerEffort: low"]),
}


def custom_tests_preset_patch(bundle_patch: str, variant: str = "v1") -> str:
    """`lab-verified-ralph-tests` from the Creator bundle's `cordis.patch.yml`, as text: the same preset and
    plugin, but the deployment verifier runs the workspace's own tests instead of the grading suite, so the
    worker never sees the suite it is graded on (week2 held-out comparison). Later variants only add plugin
    config lines (`CUSTOM_TESTS_VARIANTS`): v2 stops only when the verifier passes and the worker reports
    `complete`; v3 also scopes the workers' tools and briefs them for focus; v3-low pins them to low effort."""
    pid, label, order, rule, extra = CUSTOM_TESTS_VARIANTS[variant]
    out = ["# Generated by lab.dsh_web.custom_tests_preset_patch from dsh/bundles/verified-ralph/cordis.patch.yml.",
           f"# The Verified RALPH preset with verifyCommand set to the workspace's own tests (held-out grading).{rule}", ""]
    for ln in (ln for ln in bundle_patch.splitlines() if not ln.lstrip().startswith("#")):
        stripped = ln.strip()
        indent = ln[: len(ln) - len(ln.lstrip())]
        if stripped == "- id: preset-verified-ralph":
            ln = ln.replace("preset-verified-ralph", f"preset-{pid}")
        elif stripped == "id: verified-ralph":
            ln = f"{indent}id: {pid}"
        elif stripped == "name: Verified RALPH":
            ln = f"{indent}name: {label}"
        elif stripped.startswith("description: Standard tools plus a fresh-agent RALPH loop"):
            ln = f"{indent}description: Verified RALPH whose verifier is the workspace's own unit tests.{rule}"
        elif stripped == "order: 20":
            ln = f"{indent}order: {order}"
        elif stripped.startswith("verifyCommand:"):
            out.append(f"{indent}verifyCommand: '{PROJECT_TESTS}'")
            out.extend(f"{indent}{x}" for x in extra[:-1])
            ln = f"{indent}{extra[-1]}" if extra else out.pop()
        out.append(ln)
    return "\n".join(out) + "\n"


def shipped_standard_preset() -> Path:
    return dsh.runtime_dir(VERSION) / "node_modules" / "@deepseek-ai" / "dsh-web-app" / "presets" / "standard.patch.yml"
