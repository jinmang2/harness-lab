"""Run tasks x harnesses x engines and write one trace per run.

    runs/<batch>/
      summary.jsonl                  one line per run (lab.trace.summarize + check)
      report.md                      comparison tables
      <task>__<engine>-<harness>__<n>/
        workspace/                   the agent's cwd (fixture copied in)
        trace.jsonl                  normalized events
        wire.jsonl                   gateway calls in this run's window (if the gateway was used)
        final.md                     the final answer
        dsh-session.jsonl, stderr.txt  (dsh engine only)
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from lab import RUNS_DIR, TASKS_DIR, gateway
from lab.evaluate import recovery, tool_selection
from lab.trace import chronological, summarize, write_events


@dataclass
class Task:
    id: str
    prompt: str
    fixture: str | None = None
    check: str | None = None
    tools: dict[str, Any] | None = None  # {allowed: [categories], required: bool} -> lab.evaluate
    rubric: list[str] | None = None  # criteria for `lab judge`
    expect: str | None = None  # regex the final answer must match (answer-only tasks); counts as `check`
    base_dir: Path = TASKS_DIR  # directory of the tasks file: fixtures/ and `{tasks}` resolve here


def batch_tasks(batch_dir: Path) -> dict[str, Task]:
    """The task definitions a batch ran with (from batch.json)."""
    meta = json.loads((batch_dir / "batch.json").read_text(encoding="utf-8"))
    if not meta.get("tasks_file"):
        raise SystemExit(f"{batch_dir} has no tasks_file in batch.json")
    return {t.id: t for t in load_tasks(Path(meta["tasks_file"]))}


def load_tasks(path: Path, only: list[str] | None = None) -> list[Task]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    tasks = [Task(**t, base_dir=path.resolve().parent) for t in data["tasks"]]
    if only:
        unknown = set(only) - {t.id for t in tasks}
        if unknown:
            raise SystemExit(f"unknown task(s): {', '.join(sorted(unknown))}")
        tasks = [t for t in tasks if t.id in only]
    return tasks


def _final_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if getattr(message, "type", None) == "ai":
            content = message.content
            if isinstance(content, str):
                return content
            return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _check(task: Task, workdir: Path) -> bool | None:
    if not task.check:
        return None
    try:
        command = task.check.replace("{tasks}", shlex.quote(str(task.base_dir)))
        result = subprocess.run(command, shell=True, cwd=workdir, capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def _prepare(run_dir: Path, task: Task) -> Path:
    workdir = run_dir / "workspace"
    if task.fixture:
        shutil.copytree(task.base_dir / "fixtures" / task.fixture, workdir)
    else:
        workdir.mkdir(parents=True)
    return workdir


def _uses_gateway() -> bool:
    base = os.environ.get("DEEPSEEK_BASE_URL", "")
    return base.startswith(("http://127.0.0.1", "http://localhost"))


def _header(run_id: str, batch: str, engine: str, harness: str, task: Task, repeat: int, model: str, workdir: Path) -> dict[str, Any]:
    return {
        "kind": "run", "run_id": run_id, "batch": batch, "engine": engine, "harness": harness,
        "task": task.id, "repeat": repeat, "model": model, "cwd": str(workdir), "prompt": task.prompt,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }


def hitl_decisions(interrupts: list[Any], policy: str) -> tuple[Any, list[dict[str, Any]]]:
    """Answer HumanInTheLoopMiddleware interrupts automatically (batch runs have no human)."""
    decision = {"type": "approve"} if policy == "approve" else {"type": "reject", "message": "Rejected by the batch policy (LAB_HITL=reject)."}
    answers, log = {}, []
    for intr in interrupts:
        requests = (intr.value or {}).get("action_requests") or []
        answers[intr.id] = {"decisions": [decision] * len(requests)}
        log.append({"kind": "interrupt", "t": time.time(), "policy": policy, "actions": [{"name": r.get("name"), "args": r.get("args")} for r in requests]})
    resume = next(iter(answers.values())) if len(answers) == 1 else answers
    return resume, log


def run_lab(task: Task, harness_name: str, run_dir: Path, batch: str, repeat: int) -> list[dict[str, Any]]:
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.types import Command

    from lab.harnesses import BuildContext, get
    from lab.model import make_model, model_name
    from lab.tracing import TraceRecorder, extra_callbacks

    workdir = _prepare(run_dir, task)
    ctx = BuildContext(model=make_model(), model_name=model_name(), workdir=workdir, checkpointer=InMemorySaver())
    header = _header(run_dir.name, batch, "lab", harness_name, task, repeat, ctx.model_name, workdir)
    recorder = TraceRecorder()
    interrupts: list[dict[str, Any]] = []
    status, error, final = "ok", None, ""
    policy = os.environ.get("LAB_HITL", "approve")
    t0 = time.perf_counter()
    try:
        agent = get(harness_name).build(ctx)
        config = {
            "callbacks": [recorder, *extra_callbacks()],
            "recursion_limit": 200,
            "configurable": {"thread_id": run_dir.name},
            "run_name": f"{harness_name}:{task.id}",
            "metadata": {"harness": harness_name, "task": task.id, "batch": batch},
        }
        result = agent.invoke({"messages": [{"role": "user", "content": task.prompt}]}, config=config)
        for _ in range(50):
            pending = result.get("__interrupt__")
            if not pending:
                break
            resume, log = hitl_decisions(pending, policy)
            interrupts.extend(log)
            result = agent.invoke(Command(resume=resume), config=config)
        if result.get("__interrupt__"):
            raise RuntimeError("still waiting for approval after 50 automatic decisions")
        final = _final_text(result.get("messages", []))
    except Exception as exc:  # a failed run is a result, not a crash of the batch
        status, error = "error", repr(exc)
    wall_ms = int((time.perf_counter() - t0) * 1000)
    end = {"kind": "end", "status": status, "error": error, "wall_ms": wall_ms, "turn_ms": wall_ms, "final": final,
           "check": _check(task, workdir)}
    return [header, *chronological([*recorder.events, *ctx.hooks, *interrupts]), end]


def run_dsh(task: Task, harness_name: str, run_dir: Path, batch: str, repeat: int) -> list[dict[str, Any]]:
    from lab import dsh

    workdir = _prepare(run_dir, task)
    model = os.environ.get("LAB_MODEL", "deepseek-v4-flash")
    header = _header(run_dir.name, batch, "dsh", harness_name, task, repeat, model, workdir)
    outcome = dsh.run(task.prompt, harness_name, workdir)
    (run_dir / "stderr.txt").write_text(outcome["stderr"], encoding="utf-8")
    events: list[dict[str, Any]] = []
    if outcome["session_logs"]:
        main_log = Path(outcome["session_logs"][0])
        shutil.copy(main_log, run_dir / "dsh-session.jsonl")
        for extra, log in enumerate(outcome["session_logs"][1:], start=1):  # subagent sessions
            shutil.copy(log, run_dir / f"dsh-session.{extra}.jsonl")
        for log in outcome["session_logs"]:
            events.extend(dsh.convert_session(Path(log)))
    status = "ok" if outcome["exit_code"] == 0 else "error"
    error = None if status == "ok" else outcome["stderr"].strip()[-2000:]
    end = {
        "kind": "end", "status": status, "error": error, "wall_ms": outcome["wall_ms"],
        "turn_ms": dsh.turn_ms(Path(outcome["session_logs"][0])) if outcome["session_logs"] else None,
        "final": outcome["stdout"].strip(), "check": _check(task, workdir),
    }
    return [header, *events, end]


def run_batch(
    tasks: list[Task],
    combos: list[tuple[str, str]],
    repeat: int = 1,
    label: str | None = None,
    judge: bool = False,
    tasks_file: Path | None = None,
) -> Path:
    batch = datetime.now().strftime("%Y%m%d-%H%M%S") + (f"-{label}" if label else "")
    batch_dir = RUNS_DIR / batch
    batch_dir.mkdir(parents=True)
    print(f"batch: {batch}", flush=True)
    (batch_dir / "batch.json").write_text(
        json.dumps({"tasks_file": str(tasks_file) if tasks_file else None, "tasks": [t.id for t in tasks],
                    "combos": combos, "repeat": repeat}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_path = batch_dir / "summary.jsonl"
    total = len(tasks) * len(combos) * repeat
    n = 0
    for task in tasks:
        for i in range(1, repeat + 1):
            for engine, harness_name in combos:
                n += 1
                run_dir = batch_dir / f"{task.id}__{engine}-{harness_name}__{i}"
                run_dir.mkdir()
                print(f"[{n}/{total}] {task.id} · {engine}/{harness_name} · #{i}", flush=True)
                t_start = int(time.time() * 1000)
                runner = run_lab if engine == "lab" else run_dsh
                events = runner(task, harness_name, run_dir, batch, i)
                t_end = int(time.time() * 1000)
                write_events(run_dir / "trace.jsonl", events)
                final = events[-1].get("final") or ""
                (run_dir / "final.md").write_text(final, encoding="utf-8")
                summary = summarize(events)
                summary["check"] = events[-1].get("check")
                if task.expect:
                    summary["expect"] = bool(re.search(task.expect, final, re.IGNORECASE | re.DOTALL))
                    if summary["check"] is None:
                        summary["check"] = summary["expect"]
                summary["tool_selection"] = tool_selection(summary["tool_sequence"], task.tools)
                summary["recovery"] = recovery(summary)
                if _uses_gateway():
                    time.sleep(0.5)  # the gateway records a call after the response is flushed
                    calls = gateway.calls_between(t_start, t_end)
                    write_events(run_dir / "wire.jsonl", calls)
                    summary["wire"] = {
                        "calls": len(calls),
                        **{f: sum(c.get(f, 0) for c in calls) for f in ("input_uncached", "cache_read", "output", "reasoning")},
                        "latency_ms": sum(c.get("latency_ms", 0) for c in calls),
                    }
                with summary_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
                print(
                    f"    {summary['status']} · {summary['wall_ms']} ms · llm {summary['llm_calls']} · tools {summary['tool_calls']}"
                    f" · in {summary['input_billed']} (cached {summary['cache_read']}) · out {summary['output']}",
                    flush=True,
                )
    from lab.report import write_report

    write_report(batch_dir)
    if judge:
        from lab.evaluate import judge_batch

        judge_batch(batch_dir, {t.id: t for t in tasks})  # same Task objects the batch ran
    return batch_dir
