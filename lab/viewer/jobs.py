"""Background `lab run` / `lab judge` jobs started from the UI.

Each job is the ordinary CLI in a subprocess (same environment as this process, so the
settings and gateway in effect apply), with its output kept for the UI to tail.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from typing import Any

from lab import ROOT



class Job:
    def __init__(self, kind: str, argv: list[str], batch: str | None = None) -> None:
        self.id = uuid.uuid4().hex[:10]
        self.kind = kind
        self.argv = argv
        self.lines: list[str] = []
        self.status = "running"  # running | done | failed | stopped
        self.batch = batch  # known up front for `judge`; `run` prints it first
        self.started = time.time()
        self._lock = threading.Lock()
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "lab.cli", *argv], cwd=ROOT, env={**os.environ, "PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
        )
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.proc.stdout is not None
        for raw in self.proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip("\n")
            with self._lock:
                self.lines.append(line)
                m = re.match(r"batch: (\S+)$", line)
                if m and self.batch is None:
                    self.batch = m.group(1)
        code = self.proc.wait()
        with self._lock:
            if self.status == "running":
                self.status = "done" if code == 0 else "failed"

    def stop(self) -> None:
        with self._lock:
            if self.status != "running":
                return
            self.status = "stopped"
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)  # `lab` turns this into SystemExit and ends its DSH runs
        except ProcessLookupError:
            return

        def force() -> None:
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

        threading.Thread(target=force, daemon=True).start()

    def describe(self, tail: int = 400) -> dict[str, Any]:
        with self._lock:
            return {"id": self.id, "kind": self.kind, "argv": self.argv, "status": self.status, "batch": self.batch,
                    "started": self.started, "lines": self.lines[-tail:]}


class JobRegistry:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    def start(self, kind: str, argv: list[str], batch: str | None = None) -> Job:
        job = Job(kind, argv, batch)
        self.jobs[job.id] = job
        return job

    def get(self, jid: str) -> Job:
        try:
            return self.jobs[jid]
        except KeyError:
            raise KeyError(f"no job {jid}") from None


def run_argv(body: dict[str, Any]) -> list[str]:
    """Validated `lab run` arguments from the UI form."""
    from lab import TASKS_DIR
    from lab.harnesses import REGISTRY
    from lab import dsh

    name = re.compile(r"^[\w\-]+$")
    stem = body.get("tasks_file") or "week1"
    if not isinstance(stem, str) or not name.match(stem):  # task files run shell `check`s: only tasks/*.yaml
        raise ValueError("unknown task file")
    tasks_file = TASKS_DIR / f"{stem}.yaml"
    if not tasks_file.is_file():
        raise ValueError("unknown task file")
    harnesses, engines = body.get("harnesses") or [], body.get("engines") or ["lab"]
    if not isinstance(harnesses, list) or not isinstance(engines, list):
        raise ValueError("harnesses and engines must be lists")
    harnesses = [h for h in harnesses if isinstance(h, str)]
    engines = [e for e in engines if e in ("lab", "dsh")]
    if not harnesses or any(h not in REGISTRY and h not in dsh.HARNESSES for h in harnesses):
        raise ValueError("pick known harnesses")
    if not engines:
        raise ValueError("pick an engine")
    argv = ["run", "-T", str(tasks_file), "-H", ",".join(harnesses), "-e", ",".join(engines)]
    from lab.runner import load_tasks

    known = {t.id for t in load_tasks(tasks_file)}
    picked = body.get("tasks") or []
    if not isinstance(picked, list):
        raise ValueError("tasks must be a list")
    for t in picked:  # empty = every task in the file
        if not isinstance(t, str) or t not in known:
            raise ValueError(f"no task {t!r} in {tasks_file.name}")
        argv += ["-t", t]
    repeat = body.get("repeat") or 1
    if not isinstance(repeat, int) or not 1 <= repeat <= 20:
        raise ValueError("repeat must be 1-20")
    argv += ["-n", str(repeat)]
    label = str(body.get("label") or "").strip()
    if label:
        if not name.match(label):
            raise ValueError("label: letters, digits, - and _ only")
        argv += ["-l", label]
    if body.get("judge"):
        argv.append("--judge")
    return argv
