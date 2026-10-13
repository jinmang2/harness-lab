"""Playground sessions: chat with one harness, watch it stream, approve or stop its work.

Lab engine: one agent per session with an in-memory checkpointer, so it is multi-turn
and can pause on HumanInTheLoopMiddleware interrupts. Turns run in a background thread
and push UI events into the session; the browser polls them.

DSH engine: every message is one `dsh --profile headless` task in the session's
workspace (reasoning streams live from stderr; tools and usage come from the session
log when the task ends). Headless has no resume, so files carry over between messages
but the conversation does not.

After every turn the session is written as an ordinary run under
`runs/playground-<date>/`, so the trace viewer, summary and report work on it unchanged.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from lab import RUNS_DIR
from lab.trace import chronological, read_events, summarize, write_events

_BATCH_LOCKS: dict[str, threading.Lock] = {}
_BATCH_LOCKS_GUARD = threading.Lock()


def _batch_lock(batch_dir: Any) -> threading.Lock:
    with _BATCH_LOCKS_GUARD:
        return _BATCH_LOCKS.setdefault(str(batch_dir), threading.Lock())


class Cancelled(Exception):
    pass


class _CancelCheck(BaseCallbackHandler):
    """Stops a lab turn at the next model token, model call or tool call after Stop."""

    raise_error = True

    def __init__(self, session: PlaySession) -> None:
        self.session = session

    def _check(self, *args: Any, **kwargs: Any) -> None:
        if self.session.cancel_requested:
            raise Cancelled("stopped by the user")

    on_chat_model_start = on_llm_new_token = on_tool_start = _check


class _Stream(BaseCallbackHandler):
    """Turns LangChain callbacks into UI events."""

    raise_error = False

    def __init__(self, session: PlaySession) -> None:
        self.session = session
        self._tools: dict[UUID, str] = {}
        self._parents: dict[UUID, UUID | None] = {}  # run tree, to find model calls inside a tool (subagents)
        # A tool that pauses on interrupt() runs again from the start on resume; the rerun
        # reports under the first run's id so the UI keeps one card for the call.
        self._paused: dict[str, str] = {}
        self._ids: dict[UUID, str] = {}
        self._keys: dict[UUID, str] = {}

    def _inside_tool(self, run_id: UUID | None) -> bool:
        for _ in range(200):
            if run_id is None:
                return False
            if run_id in self._tools or run_id in self.session.tool_runs:
                return True
            run_id = self._parents.get(run_id)
        return False

    def on_chain_start(self, serialized: Any, inputs: Any, *, run_id: UUID, parent_run_id: UUID | None = None, **kw: Any) -> None:
        self._parents[run_id] = parent_run_id

    def on_chat_model_start(self, serialized: Any, messages: Any, *, run_id: UUID, parent_run_id: UUID | None = None, **kw: Any) -> None:
        self._parents[run_id] = parent_run_id
        nested = self._inside_tool(parent_run_id)
        if not nested and not self.session.request_seen:  # what the model got on the first call: DSH's "System prompt" row
            self.session.request_seen = True
            batch = messages[0] if messages else []
            system = "\n\n".join(m.text if hasattr(m, "text") else str(m.content) for m in batch if getattr(m, "type", "") == "system")
            tools = [(t.get("function") or t).get("name") for t in ((kw.get("invocation_params") or {}).get("tools") or []) if isinstance(t, dict)]
            self.session.emit("request", system=system, tools=tools)
        self.session.emit("llm_start", run_id=str(run_id), nested=nested)

    def on_llm_new_token(self, token: str, *, run_id: UUID, chunk: Any = None, **kw: Any) -> None:
        message = getattr(chunk, "message", None)
        reasoning = (getattr(message, "additional_kwargs", None) or {}).get("reasoning_content")
        if reasoning or token:
            self.session.first_token()
        if reasoning:
            self.session.emit("reasoning", run_id=str(run_id), text=reasoning)
        if token:
            self.session.emit("token", run_id=str(run_id), text=token)

    def on_llm_end(self, response: Any, *, run_id: UUID, **kw: Any) -> None:
        message = None
        if response.generations and response.generations[0]:
            message = getattr(response.generations[0][0], "message", None)
        usage = getattr(message, "usage_metadata", None) or {}
        self.session.add_usage(usage)
        self.session.emit("llm_end", run_id=str(run_id), usage=usage)

    def on_tool_start(self, serialized: Any, input_str: str, *, run_id: UUID, parent_run_id: UUID | None = None, inputs: Any = None, **kw: Any) -> None:
        name = (serialized or {}).get("name") or "?"
        self._parents[run_id] = parent_run_id
        self._tools[run_id] = name
        self.session.tool_runs.add(run_id)
        args = inputs if inputs is not None else input_str
        # The model's tool_call_id is stable across the rerun; name+args is a fallback for callers without it.
        key = kw.get("tool_call_id") or name + json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        self._keys[run_id] = key
        if key in self._paused:
            self._ids[run_id] = self._paused.pop(key)
            return
        self._ids[run_id] = str(run_id)
        self.session.emit("tool_start", run_id=str(run_id), name=name, args=args, nested=self._inside_tool(parent_run_id))

    def on_tool_end(self, output: Any, *, run_id: UUID, **kw: Any) -> None:
        update = getattr(output, "update", None)
        if isinstance(update, dict):
            output = next((m for m in reversed(update.get("messages") or []) if getattr(m, "type", None) == "tool"), output)
        text = getattr(output, "content", output)
        text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False, default=str)
        self._keys.pop(run_id, None)
        self.session.emit("tool_end", run_id=self._ids.pop(run_id, str(run_id)), name=self._tools.pop(run_id, "?"),
                          preview=text[:2000], error=getattr(output, "status", None) == "error")

    def close_paused(self) -> None:
        """The turn ended without resuming these calls (error, stop): settle their cards."""
        for rid in self._paused.values():
            self.session.emit("tool_end", run_id=rid, name="?", preview="Not answered: the turn ended first.", error=True)
        self._paused.clear()

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kw: Any) -> None:
        from langgraph.errors import GraphBubbleUp

        if isinstance(error, GraphBubbleUp):  # interrupt(): the call is waiting for a person, not failed
            key = self._keys.pop(run_id, None)
            if key is not None:
                self._paused[key] = self._ids.get(run_id, str(run_id))
            self._tools.pop(run_id, None)
            self._ids.pop(run_id, None)
            return
        self.session.emit("tool_end", run_id=self._ids.pop(run_id, str(run_id)), name=self._tools.pop(run_id, "?"),
                          preview=repr(error), error=True)


def _effort_env(model: str | None, effort: str | None) -> dict[str, str]:
    env: dict[str, str] = {}
    if model:
        env["LAB_MODEL"] = model
    if effort:
        env["LAB_THINKING"] = "disabled" if effort == "off" else "enabled"
        if effort != "off":
            env["LAB_REASONING_EFFORT"] = effort
    return env


class PlaySession:
    def __init__(self, harness_name: str, engine: str = "lab", model: str | None = None, effort: str | None = None,
                 approval: str = "auto", workdir: Path | None = None) -> None:
        from lab import dsh
        from lab.harnesses import REGISTRY
        from lab.model import CATALOG, EFFORTS, model_name
        from lab.runner import _uses_gateway

        # Validated before anything touches the filesystem (names end up in paths).
        if engine not in ("lab", "dsh"):
            raise ValueError(f"unknown engine {engine!r}")
        if harness_name not in (REGISTRY if engine == "lab" else dsh.HARNESSES):
            raise ValueError(f"unknown {engine} harness {harness_name!r}")
        if model and model not in CATALOG and not model.replace("-", "").replace(".", "").replace("_", "").isalnum():
            raise ValueError(f"bad model id {model!r}")
        if effort and effort not in EFFORTS:
            raise ValueError(f"effort must be one of {EFFORTS}")
        if approval not in ("auto", "ask"):
            raise ValueError("approval must be auto or ask")
        if engine == "dsh" and not dsh.bin_path().exists():
            raise ValueError("DeepSeek Harness is not installed: run `uv run lab dsh-install`")

        self.id = uuid.uuid4().hex[:10]
        self.engine = engine
        self.harness = harness_name
        self.effort = effort
        self.approval = approval if engine == "lab" else "auto"  # headless cannot ask a person
        self.title = ""
        self.created = time.time()
        self.updated = self.created
        self.request_seen = False
        self.batch = "playground-" + datetime.now().strftime("%Y%m%d")
        self.run_id = f"chat__{engine}-{harness_name}__{self.id}"
        self.run_dir = RUNS_DIR / self.batch / self.run_id
        self.workdir = workdir or self.run_dir / "workspace"  # a chosen workspace, or a fresh folder per session
        self.status = "idle"  # idle | running | waiting | error
        self.events: list[dict[str, Any]] = []
        self.pending: list[Any] = []  # langgraph Interrupt objects awaiting a decision
        self.turns: list[str] = []
        self.interrupt_log: list[dict[str, Any]] = []
        self.dsh_events: list[dict[str, Any]] = []
        self.final = ""
        self.error: str | None = None
        self.cancel_requested = False
        self._proc: Any = None
        self._lock = threading.RLock()  # guards events, status and pending together
        self.tool_runs: set[UUID] = set()
        self._t0 = time.perf_counter()
        self._t0_ms = int(time.time() * 1000)
        self._turn: dict[str, Any] = {}
        self.gateway = _uses_gateway()
        self.supports_plan = False  # harness has DSH's plan mode + ask_user_question (lab engine only)
        self.plan_mode = False
        self._plan_told: bool | None = None  # plan state the model last saw at a turn start

        if engine == "lab":
            from langgraph.checkpoint.memory import InMemorySaver

            from lab.harnesses import BuildContext, get
            from lab.model import make_model
            from lab.tracing import TraceRecorder, extra_callbacks

            model_obj = make_model(model, effort)  # may raise SystemExit (no key) before any mkdir
            self.model_name = model_name(model)
            self.run_dir.mkdir(parents=True)
            self.workdir.mkdir(parents=True, exist_ok=True)
            self.ctx = BuildContext(model=model_obj, model_name=self.model_name, workdir=self.workdir,
                                    checkpointer=InMemorySaver(), approval=self.approval, interactive=True)
            self.recorder = TraceRecorder()
            self._stream = _Stream(self)
            self.agent = get(harness_name).build(self.ctx)
            self.supports_plan = "plan_mode" in getattr(self.agent, "channels", {})
            self.config = {
                "callbacks": [_CancelCheck(self), self.recorder, self._stream, *extra_callbacks()],
                "recursion_limit": 200,
                "configurable": {"thread_id": self.id},
                "run_name": f"play:{harness_name}",
            }
        else:
            self.env = _effort_env(model, effort)
            self.model_name = model or os.environ.get("LAB_MODEL", "deepseek-v4-flash")
            self.run_dir.mkdir(parents=True)
            self.workdir.mkdir(parents=True, exist_ok=True)
        self.emit("session", engine=engine, harness=harness_name, workdir=str(self.workdir), model=self.model_name,
                  effort=effort or "default", gateway=self.gateway, approval=self.approval)

    # ── events ─────────────────────────────────────────────────────────────

    def emit(self, kind: str, **data: Any) -> None:
        with self._lock:
            now = time.time()
            self.events.append({"seq": len(self.events), "type": kind, "t": now, **data})
            self.updated = now

    def events_after(self, after: int) -> list[dict[str, Any]]:
        with self._lock:
            return self.events[after:]

    def first_token(self) -> None:
        with self._lock:
            self._turn.setdefault("t_first", time.perf_counter())

    def add_usage(self, usage: dict[str, Any]) -> None:
        with self._lock:
            t = self._turn
            t["steps"] = t.get("steps", 0) + 1
            t["input"] = t.get("input", 0) + int(usage.get("input_tokens") or 0)
            t["cached"] = t.get("cached", 0) + int((usage.get("input_token_details") or {}).get("cache_read") or 0)
            t["output"] = t.get("output", 0) + int(usage.get("output_tokens") or 0)
            t["last_input"] = int(usage.get("input_tokens") or 0)

    def _turn_stats(self) -> dict[str, Any]:
        t = self._turn
        start = t.get("t_start", time.perf_counter())
        return {
            "wall_ms": int((time.perf_counter() - start) * 1000),
            "ttft_ms": int((t["t_first"] - start) * 1000) if "t_first" in t else None,
            **{k: t.get(k, 0) for k in ("steps", "input", "cached", "output", "last_input")},
        }

    # ── turns ──────────────────────────────────────────────────────────────

    def rename(self, title: str) -> None:
        with self._lock:
            self.title = title.strip()[:80]
            meta = self.describe()
        if (self.run_dir / "session.json").is_file():  # already saved once: keep the new title across restarts
            _atomic_json(self.run_dir / "session.json", {**meta, "status": "archived"})

    def send(self, text: str) -> None:
        with self._lock:
            if self.status in ("running", "waiting"):
                raise ValueError(f"session is {self.status}")
            self.status = "running"
            self.cancel_requested = False
            self._turn = {"t_start": time.perf_counter()}
            self.turns.append(text)
            if not self.title:
                self.title = text.strip().splitlines()[0][:40]
            self.emit("user", text=text)
        if self.engine == "dsh":
            threading.Thread(target=self._run_dsh, args=(text,), daemon=True).start()
            return
        messages = [{"role": "user", "content": text}]
        if self._plan_told is not None and self._plan_told != self.plan_mode:
            # DSH narrates a user switch the model has not been told about yet.
            from lab.middleware.collaboration import SWITCHED_OFF, SWITCHED_ON

            messages.insert(0, {"role": "user", "content": SWITCHED_ON if self.plan_mode else SWITCHED_OFF})
        self._plan_told = self.plan_mode
        self._start({"messages": messages})

    def set_plan(self, active: bool) -> str:
        """`/plan` and `/plan off` between turns (DSH commits these at once when no turn is open)."""
        with self._lock:
            if not self.supports_plan:
                raise ValueError("plan mode needs a lab harness with plan mode (standard family); "
                                 "headless DSH runs one-shot and cannot review a plan")
            if self.status in ("running", "waiting"):
                raise ValueError(f"session is {self.status}; change plan mode between turns")
            if active == self.plan_mode:
                text = "Plan mode is already on. Use /plan off to leave." if active else "Plan mode is already inactive."
            else:
                self.agent.update_state(self.config, {"plan_mode": active})
                self.plan_mode = active
                text = "Plan mode on. Use /plan off to leave." if active else "Plan mode off."
                self.emit("plan_mode", active=active)
            self.emit("command", name="plan", text=text)
            self.interrupt_log.append({"kind": "plan_mode", "t": time.time(), "active": active})
        self._persist(self.status)  # a session that only ran /plan still survives a restart
        return text

    def resume(self, decision: str, message: str | None = None) -> None:
        from langgraph.types import Command

        with self._lock:
            if self.status != "waiting" or not self.pending:
                raise ValueError("nothing is waiting for approval")
            if any(_question_kind(i) for i in self.pending):
                raise ValueError("a question is waiting; answer it instead")
            pending, self.pending, self.status = self.pending, [], "running"
            self.cancel_requested = False
        chosen = {"type": "approve"} if decision == "approve" else {"type": "reject", "message": message or "Rejected by the user."}
        answers = {}
        for intr in pending:
            requests = (intr.value or {}).get("action_requests") or []
            answers[intr.id] = {"decisions": [chosen] * len(requests)}
            self.interrupt_log.append({"kind": "interrupt", "t": time.time(), "policy": f"human:{decision}",
                                       "actions": [{"name": r.get("name"), "args": r.get("args")} for r in requests]})
        resume = next(iter(answers.values())) if len(answers) == 1 else answers
        self.emit("decision", decision=decision)
        self._start(Command(resume=resume))

    def answer(self, reply: dict[str, Any]) -> None:
        """Answer the first pending ask_user_question / plan review: {"answers": [...]} or {"cancelled": true}."""
        from langgraph.types import Command

        with self._lock:
            first = next((i for i in self.pending if _question_kind(i)), None)
            if self.status != "waiting" or first is None:
                raise ValueError("no question is waiting")
            cancelled = bool(reply.get("cancelled"))
            answers = reply.get("answers")
            if not cancelled and not (isinstance(answers, list) and all(isinstance(a, dict) for a in answers)):
                raise ValueError("answers must be a list of {id, selected, custom?}")
            value = {"cancelled": True} if cancelled else {"answers": answers}
            self.pending, self.status = [], "running"
            self.cancel_requested = False
            tool = "exit_plan_mode" if _question_kind(first) == "plan-review" else "ask_user_question"
            self.interrupt_log.append({"kind": "interrupt", "t": time.time(), "policy": "human:answer",
                                       "actions": [{"name": tool}], "question": first.value, "answer": value})
        self.emit("answered", key=first.id, cancelled=cancelled, answers=value.get("answers"))
        self._start(Command(resume={first.id: value}))

    def cancel(self) -> None:
        with self._lock:
            if self.status != "running":
                raise ValueError("nothing is running")
            self.cancel_requested = True
            proc = self._proc
        self.emit("note", text="stop requested")
        if proc is not None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def _start(self, payload: Any) -> None:
        threading.Thread(target=self._run, args=(payload,), daemon=True).start()

    def _run(self, payload: Any) -> None:
        from lab.runner import _final_text

        pending: list[Any] = []
        try:
            result = self.agent.invoke(payload, config=self.config)
            pending = result.get("__interrupt__") or []
            if not pending:
                self.final = _final_text(result.get("messages", []))
            self.error = None
            next_status = "waiting" if pending else "idle"
        except Exception as exc:  # surface to the UI instead of killing the thread silently
            if self.cancel_requested or isinstance(exc, Cancelled):
                self._close_dangling_tool_calls()
                next_status, self.error = "cancelled", None
            else:
                next_status, self.error = "error", repr(exc)
        self._finish(next_status, pending)

    def _close_dangling_tool_calls(self) -> None:
        """After Stop, answer tool calls the model made but that never ran, so the next turn is valid."""
        from langchain_core.messages import ToolMessage

        try:
            state = self.agent.get_state(self.config)
            messages = state.values.get("messages") or []
            answered = {m.tool_call_id for m in messages if getattr(m, "type", None) == "tool"}
            last_ai = next((m for m in reversed(messages) if getattr(m, "type", None) == "ai"), None)
            missing = [c for c in (getattr(last_ai, "tool_calls", None) or []) if c["id"] not in answered]
            if missing:
                self.agent.update_state(self.config, {"messages": [
                    ToolMessage("Stopped by the user before this ran.", tool_call_id=c["id"], name=c["name"], status="error")
                    for c in missing]})
        except Exception as exc:  # the session stays usable for reading; report it
            self.emit("warning", text=f"could not tidy the stopped turn: {exc!r}")

    def _run_dsh(self, text: str) -> None:
        from lab import dsh

        key = f"dsh-{len(self.turns)}"
        self.emit("llm_start", run_id=key, nested=False)

        def on_stderr(line: str) -> None:
            if line.startswith("dsh: reasoning:"):
                return
            self.first_token()
            self.emit("reasoning", run_id=key, text=line)

        def on_start(proc: Any) -> None:
            with self._lock:
                self._proc = proc
                stop = self.cancel_requested  # Stop pressed before the process existed
            if stop:
                os.killpg(proc.pid, signal.SIGTERM)

        try:
            outcome = dsh.run(text, self.harness, self.workdir, env=self.env, on_stderr=on_stderr, on_start=on_start)
        except Exception as exc:
            outcome = {"exit_code": -1, "stdout": "", "stderr": repr(exc), "session_logs": []}
        with self._lock:
            self._proc = None
        self.emit("llm_end", run_id=key, usage={})  # reasoning stream done; usage comes with the answer below
        try:
            next_status = self._digest_dsh(outcome, key)
        except Exception as exc:  # e.g. a session log cut off by Stop: report it, never leave the turn running
            next_status, self.error = "error", f"could not read the DSH session log: {exc!r}"
        self._finish(next_status, [])

    def _digest_dsh(self, outcome: dict[str, Any], key: str) -> str:
        from lab import dsh

        events: list[dict[str, Any]] = []
        for n, log in enumerate(outcome["session_logs"]):
            shutil.copy(log, self.run_dir / f"dsh-session.t{len(self.turns)}.{n}.jsonl")
            if n == 0 and not self.request_seen:
                self.request_seen = True
                self.emit("request", **dsh.session_request(Path(log)))
            converted = dsh.convert_session(Path(log))
            for e in converted:
                e["nested"] = n > 0  # logs after the first are subagent sessions
            events.extend(converted)
        self.dsh_events.extend(events)
        for i, e in enumerate(events):
            if e["kind"] == "tool":
                tid = f"{key}-tool-{i}"
                self.emit("tool_start", run_id=tid, name=e.get("name"), args=e.get("args"), nested=e["nested"])
                self.emit("tool_end", run_id=tid, name=e.get("name"), preview=e.get("error") or e.get("result_preview") or "",
                          error=bool(e.get("error")))
            elif e["kind"] == "llm" and not e["nested"]:
                self.add_usage({"input_tokens": e["input_uncached"] + e["cache_read"] + e["cache_write"],
                                "input_token_details": {"cache_read": e["cache_read"]}, "output_tokens": e["output"]})
        llm = [e for e in events if e["kind"] == "llm" and not e["nested"]]
        usage = {"input_tokens": sum(e["input_uncached"] + e["cache_read"] + e["cache_write"] for e in llm),
                 "input_token_details": {"cache_read": sum(e["cache_read"] for e in llm)},
                 "output_tokens": sum(e["output"] for e in llm), "steps": len(llm),
                 "last_input": (llm[-1]["input_uncached"] + llm[-1]["cache_read"] + llm[-1]["cache_write"]) if llm else 0}
        answer = f"{key}-answer"
        self.emit("llm_start", run_id=answer, nested=False)
        self.emit("token", run_id=answer, text=outcome["stdout"].strip())
        self.emit("llm_end", run_id=answer, usage=usage)
        if self.cancel_requested:
            self.error = None
            return "cancelled"
        if outcome["exit_code"] == 0:
            self.error = None
            self.final = outcome["stdout"].strip()
            return "idle"
        self.error = outcome["stderr"].strip()[-2000:]
        return "error"

    def _finish(self, next_status: str, pending: list[Any]) -> None:
        stats = self._turn_stats()
        if not pending and self.engine == "lab":
            self._stream.close_paused()
        with self._lock:  # closing events first, so the saved chat-events.jsonl has them too
            if pending and (question := next((i for i in pending if _question_kind(i)), None)) is not None:
                self.emit("question", key=question.id, qkind=question.value["kind"], questions=question.value["questions"],
                          title=question.value.get("title"))
            elif pending:
                actions = [r for intr in pending for r in ((intr.value or {}).get("action_requests") or [])]
                self.emit("interrupt", actions=[{"name": a.get("name"), "args": a.get("args"), "description": a.get("description")} for a in actions])
            elif next_status == "error":
                self.emit("error", text=self.error)
                self.emit("turn_end", stats=stats)
            else:
                self.emit("cancelled" if next_status == "cancelled" else "final", text=self.final)
                self.emit("turn_end", stats=stats)
        self._sync_plan()
        self._persist(next_status)  # before the status flips, so the next turn cannot overlap it
        with self._lock:
            if pending:
                self.pending = list(pending)
            self.status = "idle" if next_status == "cancelled" else next_status

    def _sync_plan(self) -> None:
        """exit_plan_mode approval turns plan mode off inside the graph; mirror it for the UI."""
        if not self.supports_plan:
            return
        try:
            active = bool(self.agent.get_state(self.config).values.get("plan_mode"))
        except Exception:  # a broken checkpoint read must not hide the turn result; keep the last known state
            return
        with self._lock:
            if active != self.plan_mode:
                self.plan_mode = active
                self.emit("plan_mode", active=active)
            self._plan_told = active  # the model saw this state at the end of the turn

    # ── persistence (as an ordinary run) ───────────────────────────────────

    def _persist(self, status: str) -> None:
        try:
            self._write(status)
        except Exception as exc:  # a failed save must not hide the turn's result
            self.emit("warning", text=f"could not save trace: {exc!r}")

    def _write(self, status: str) -> None:
        header = {
            "kind": "run", "run_id": self.run_id, "batch": self.batch, "engine": self.engine, "harness": self.harness,
            "task": "chat", "repeat": 1, "model": self.model_name, "cwd": str(self.workdir), "title": self.title,
            "prompt": "\n\n---\n\n".join(self.turns),
        }
        end = {"kind": "end", "status": "error" if status == "error" else "ok", "error": self.error,
               "wall_ms": int((time.perf_counter() - self._t0) * 1000), "final": self.final, "check": None}
        middle = self.dsh_events if self.engine == "dsh" else chronological([*self.recorder.events, *self.interrupt_log])
        events = [header, *middle, end]
        batch_dir = self.run_dir.parent
        with _batch_lock(batch_dir):  # sessions in one batch share summary.jsonl
            tmp = self.run_dir / "trace.jsonl.tmp"
            write_events(tmp, events)
            os.replace(tmp, self.run_dir / "trace.jsonl")
            (self.run_dir / "final.md").write_text(self.final, encoding="utf-8")
            if self.gateway:
                from lab.gateway import calls_between

                time.sleep(0.3)  # the gateway records a call after the response is flushed
                # Time window: calls from anything else running at the same moment land here too.
                write_events(self.run_dir / "wire.jsonl", calls_between(self._t0_ms, int(time.time() * 1000)))
            with self._lock:
                snapshot, meta = list(self.events), self.describe()
            _atomic_lines(self.run_dir / "chat-events.jsonl", snapshot)  # reopened after a restart, read-only
            _atomic_json(self.run_dir / "session.json", {**meta, "status": "archived"})
            lines = [json.dumps(summarize(read_events(t)), ensure_ascii=False) for t in sorted(batch_dir.glob("*/trace.jsonl"))]
            tmp = batch_dir / "summary.jsonl.tmp"
            tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(tmp, batch_dir / "summary.jsonl")

    def describe(self) -> dict[str, Any]:
        return {"id": self.id, "engine": self.engine, "harness": self.harness, "model": self.model_name, "effort": self.effort,
                "approval": self.approval, "title": self.title, "status": self.status, "batch": self.batch,
                "run_id": self.run_id, "workdir": str(self.workdir), "created": self.created, "updated": self.updated,
                "turns": len(self.turns), "events": len(self.events),
                "supports_plan": self.supports_plan, "plan_mode": self.plan_mode}


def _question_kind(intr: Any) -> str | None:
    kind = (intr.value or {}).get("kind") if isinstance(intr.value, dict) else None
    return kind if kind in ("question", "plan-review") else None


def _atomic_json(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _atomic_lines(path: Path, rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, path)


class ArchivedSession:
    """A session from an earlier `lab ui` run: its events replay in the chat view, nothing runs.

    The agent's in-memory state did not survive the restart, so it cannot continue.
    """

    status = "archived"

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.meta = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
        self.id = self.meta["id"]
        self.workdir = Path(self.meta.get("workdir") or run_dir / "workspace")
        self._events: list[dict[str, Any]] | None = None

    def events_after(self, after: int) -> list[dict[str, Any]]:
        if self._events is None:
            self._events = read_events(self.run_dir / "chat-events.jsonl")
        return self._events[after:]

    def describe(self) -> dict[str, Any]:
        return {**self.meta, "status": "archived", "supports_plan": False}

    def rename(self, title: str) -> None:
        self.meta["title"] = title.strip()[:80]
        _atomic_json(self.run_dir / "session.json", self.meta)

    def _closed(self, *_: Any, **__: Any) -> None:
        raise ValueError("this session is from an earlier `lab ui` run and is read-only; start a new one")

    send = resume = cancel = answer = set_plan = _closed


class PlayRegistry:
    def __init__(self) -> None:
        self.sessions: dict[str, PlaySession | ArchivedSession] = {}
        self._lock = threading.Lock()
        for meta in sorted(RUNS_DIR.glob("playground-*/chat__*/session.json")):
            try:
                old = ArchivedSession(meta.parent)
            except (OSError, ValueError, KeyError):
                continue  # a half-written or foreign folder: skip it, the run itself stays in Runs
            self.sessions[old.id] = old

    def start(self, harness: str, engine: str = "lab", model: str | None = None, effort: str | None = None,
              approval: str = "auto", workdir: Path | None = None, plan: bool = False) -> PlaySession:
        session = PlaySession(harness, engine, model, effort, approval, workdir)
        if plan and not session.supports_plan:
            # `/plan` from the start page: refuse before the session exists anywhere. run_dir was
            # created just now (mkdir without exist_ok), so removing it touches nothing else.
            shutil.rmtree(session.run_dir, ignore_errors=True)
            raise ValueError(f"{engine}/{harness} has no plan mode; pick a lab standard-family preset for /plan")
        if plan:
            session.set_plan(True)
        with self._lock:
            self.sessions[session.id] = session
        return session

    def get(self, sid: str) -> PlaySession:
        try:
            return self.sessions[sid]
        except KeyError:
            raise KeyError(f"no session {sid}") from None
