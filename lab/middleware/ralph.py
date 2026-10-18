"""Ralph-style loops for the lab engine (week2, ADR-0015): four ways to run one objective over rounds.

| mechanism | where the loop lives                 | context per round          | who decides "done"          |
|-----------|--------------------------------------|----------------------------|-----------------------------|
| fresh     | `ralph` tool (DSH `tool-ralph`)      | new child agent            | the worker's report         |
| verified  | `verified_ralph` tool                | new child agent            | a deployment-owned command  |
| judge     | `after_agent` hook, same thread      | the whole conversation     | a separate model call       |
| reset     | `ralph_handoff` tool + `after_agent` | same thread, wiped context | the worker's handoff        |

`fresh` copies DeepSeek Harness `packages/experimental/tool-ralph/src/index.ts` (MIT): the tool
name, description, prompt section, round prompt, report schema, validation rules and result text
are verbatim. One deviation: a round's child cannot start a nested loop (DSH only asks it not to).
The other three are written for this lab from the LangChain/LangGraph APIs.

Every round appends a `round` event to the trace (`ctx.hooks`), so `trace.jsonl` shows what
each round did, what crossed into the next one, and why the loop stopped.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import uuid
from collections.abc import Callable
from typing import Any, NotRequired

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain.agents.middleware.types import AgentState
from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool, ToolException, tool
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.types import Command

Emit = Callable[[dict[str, Any]], None]


def _emit_to(sink: list[dict[str, Any]], mechanism: str) -> Emit:
    def emit(event: dict[str, Any]) -> None:
        sink.append({"kind": "round", "t": time.time(), "mechanism": mechanism, **event})

    return emit


def _text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return str(content)


# ── structured child: DSH `dsh-subagent-in-process-driver` ──────────────────
# A child reports through a plain `structured_output` tool plus a prompt section, and the call
# ends its turn. No forced tool_choice: DeepSeek thinking mode rejects it (400), and DSH does not
# force it either. A child that ends with plain text has no report (the loop's failure path).

STRUCTURED_OUTPUT_INSTRUCTION = (
    "When you have your final answer, you MUST report it by calling the `structured_output` tool with arguments "
    "matching its parameter schema exactly. Do not finish with a plain text answer: only the tool call counts as your result."
)
STRUCTURED_OUTPUT_DESCRIPTION = (
    "Report your final structured result. Call this exactly once, when your answer is complete; "
    "the arguments must match this tool's parameter schema exactly."
)


def schema_violations(schema: dict[str, Any], value: Any, path: str = "$") -> list[str]:
    """The JSON Schema subset the report schemas use: object/array/string/integer, required, enum, additionalProperties."""
    kind = schema.get("type")
    checks = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}
    if kind in checks and (not isinstance(value, checks[kind]) or (kind == "integer" and isinstance(value, bool))):
        return [f"{path} must be {kind}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path} must be one of {schema['enum']}"]
    out: list[str] = []
    if kind == "object":
        props = schema.get("properties") or {}
        out += [f"{path}.{k} is required" for k in schema.get("required") or [] if k not in value]
        if schema.get("additionalProperties") is False:
            out += [f"{path}.{k} is not allowed" for k in value if k not in props]
        for k, v in value.items():
            if k in props:
                out += schema_violations(props[k], v, f"{path}.{k}")
    elif kind == "array" and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            out += schema_violations(schema["items"], item, f"{path}[{i}]")
    return out


class _StructuredGuard(AgentMiddleware):
    """The driver's `tool:structured_output` prompt section, and its guard: once a report is recorded, no tool runs."""

    def __init__(self, kit: "StructuredOutput") -> None:
        self.kit = kit

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        system = request.system_message
        base = _text(system) if system is not None else ""
        text = STRUCTURED_OUTPUT_INSTRUCTION
        return handler(request.override(system_message=SystemMessage(f"{base}\n\n{text}" if base else text)))

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        if self.kit.captured is not None:
            name = request.tool_call["name"]
            return ToolMessage(f"structured output already recorded: the run is complete, so `{name}` is not executed",
                               tool_call_id=request.tool_call["id"], name=name, status="error")
        return handler(request)


class StructuredOutput:
    """One child's capture tool and prompt section; `captured` holds the first valid report."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self.schema = {k: v for k, v in schema.items() if k not in ("title", "description")}
        self.captured: dict[str, Any] | None = None
        self.middleware = _StructuredGuard(self)

        def structured_output(**report: Any) -> str:
            if self.captured is not None:
                return "structured output already recorded: the run is complete"
            violations = schema_violations(self.schema, report)
            if violations:
                raise ToolException("Invalid arguments: " + "; ".join(violations))
            self.captured = report
            return "Structured output recorded."

        self.tool = StructuredTool.from_function(
            structured_output, name="structured_output", description=STRUCTURED_OUTPUT_DESCRIPTION,
            args_schema=self.schema, return_direct=True, handle_tool_error=True,
        )


ChildFactory = Callable[[StructuredOutput], Any]  # capture kit -> compiled child agent that mounts kit.tool and kit.middleware


def _run_child(make_child: ChildFactory, schema: dict[str, Any], prompt: str, config: RunnableConfig | None,
               label: str | None = None) -> dict[str, Any] | None:
    """One fresh child on a new thread: no parent messages, same workspace, the parent's callbacks (tracing).

    Like DSH's spawn provider: depth = parent depth + 1, and the child's label (verified_ralph passes one,
    tool-ralph's workflow does not) travels in the run metadata for the trace and the UI.
    """
    kit = StructuredOutput(schema)
    child = make_child(kit)
    depth = int(((config or {}).get("configurable") or {}).get("ralph_depth") or 0) + 1
    thread = f"ralph-child-{uuid.uuid4()}"
    child_config: RunnableConfig = {
        "callbacks": (config or {}).get("callbacks"),
        "recursion_limit": 200,
        "configurable": {"thread_id": thread, "ralph_depth": depth},
        "metadata": {"ralph_child": True, "child_thread": thread, "child_label": label, "delegation_depth": depth},
    }
    child.invoke({"messages": [HumanMessage(prompt)]}, config=child_config)
    return kit.captured


# ── fresh: DeepSeek Harness tool-ralph ───────────────────────────────────────

RALPH_GUIDANCE = (
    "Use the ralph tool ONLY when the direct human explicitly asks for a Ralph loop or fresh-agent iterative execution. "
    "Each Ralph round starts a fresh child with no conversation seed and uses the shared workspace as durable memory. "
    "Completion and blockers are worker reports, not independent evaluation. Use same-session goal tools for ordinary "
    "long-running objectives, and plain subagents or workflows for bounded delegation and fan-out."
)
RALPH_DESCRIPTION = (
    "Run a foreground fresh-agent Ralph loop toward one immutable objective. "
    "Use only when the direct human explicitly asks for Ralph or fresh-agent iteration. Each round "
    "opens a new child with no parent conversation or prior child session; the shared workspace is "
    "long-term memory, and only a bounded structured report crosses rounds. The call returns when "
    "a worker reports completion or a concrete blocker, or at the round limit. Ordinary long-running same-session work "
    "belongs to goal tools."
)
DSH_REPORT_SCHEMA: dict[str, Any] = {
    "title": "structured_output",
    "description": "Return the round report.",
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["continue", "complete", "blocked"]},
        "summary": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "nextSteps": {"type": "array", "items": {"type": "string"}},
        "blocker": {"type": "string"},
    },
    "required": ["status", "summary", "evidence", "nextSteps", "blocker"],
    "additionalProperties": False,
}


def _normalized(value: Any) -> bool:
    return isinstance(value, str) and len(value) > 0 and value == value.strip()


def validate_dsh_report(report: Any, max_chars: int) -> dict[str, Any]:
    """The fixed script's `validateReport`, same checks and messages."""
    if not isinstance(report, dict):
        raise ValueError("Ralph child returned no structured round report")
    if not _normalized(report.get("summary")):
        raise ValueError("Ralph round report summary must be non-empty and normalized")
    lists = (report.get("evidence"), report.get("nextSteps"))
    if not all(isinstance(v, list) and all(_normalized(x) for x in v) for v in lists):
        raise ValueError("Ralph round report evidence and nextSteps must contain only non-empty normalized strings")
    blocker = report.get("blocker")
    if not isinstance(blocker, str) or blocker != blocker.strip():
        raise ValueError("Ralph round report blocker must be a normalized string")
    status = report.get("status")
    if status == "continue":
        if not report["nextSteps"] or blocker != "":
            raise ValueError("a continuing Ralph report needs nextSteps and an empty blocker")
    elif status == "complete":
        if not report["evidence"] or report["nextSteps"] or blocker != "":
            raise ValueError("a complete Ralph report needs evidence, no nextSteps, and an empty blocker")
    elif status == "blocked":
        if not _normalized(blocker):
            raise ValueError("a blocked Ralph report needs a concrete blocker")
    else:
        raise ValueError("Ralph round report status is invalid")
    size = _js_length(json.dumps(report, separators=(",", ":"), ensure_ascii=False))
    if size > max_chars:
        raise ValueError(f"Ralph round report exceeds maxHandoffChars ({size} > {max_chars})")
    return report


def dsh_round_prompt(objective: str, round_no: int, max_rounds: int, previous: dict[str, Any] | None) -> str:
    prior = "(none — this is the first round)" if previous is None else json.dumps(previous, separators=(",", ":"), ensure_ascii=False)
    return "\n\n".join([
        "You are one fresh worker in a foreground Ralph loop. You receive no parent conversation and no prior child session. "
        "Do not call the ralph tool: this round already is its worker.",
        "Immutable objective:\n" + objective,
        f"Ralph round: {round_no} of {max_rounds}.",
        "The shared workspace and its current working tree are the long-term memory and source of truth. Inspect them before "
        "acting, preserve existing work, perform concrete in-scope work, and verify what you change. Treat the previous report "
        "only as a bounded handoff; confirm it against the workspace.",
        "Previous structured handoff:\n" + prior,
        "Return one report with exact normalized strings. Use status continue with at least one nextSteps entry while useful "
        "work remains; complete only with concrete evidence and no nextSteps; blocked only when no meaningful progress is "
        "possible without human input or an external-state change. blocker must be empty unless blocked.",
    ])


def _js_length(text: str) -> int:
    """JavaScript `string.length`: UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def _bound(text: str, max_chars: int) -> str:
    notice = "\n… [truncated]"
    if len(text) <= max_chars:
        return text
    return notice[:max_chars] if max_chars <= len(notice) else text[: max_chars - len(notice)] + notice


def dsh_render(status: str, rounds: int, report: dict[str, Any], max_chars: int) -> str:
    n = f"{rounds} round{'' if rounds == 1 else 's'}"
    head = {
        "complete": f"Ralph worker reported completion after {n}.",
        "blocked": f"Ralph worker reported a blocker after {n}.",
        "budget-limited": f"Ralph reached its {n} limit; the worker reported work remaining.",
    }[status]
    return _bound(f"{head}\nFinal report:\n{json.dumps(report, indent=2, ensure_ascii=False)}", max_chars)


def ralph_tool(make_child: ChildFactory, emit: Emit, max_rounds: int = 5, max_handoff_chars: int = 16_384,
               max_result_chars: int = 16_384) -> Any:
    """DSH `ralph`: deployment ceiling `max_rounds` (the week2 overlay sets 5, like dsh/patches/ralph-official.yml)."""

    @tool("ralph", description=RALPH_DESCRIPTION)
    def ralph(objective: str, config: RunnableConfig, maxRounds: float | None = None) -> str:  # noqa: N803 - DSH schema (number)
        """objective: The immutable completion objective for every fresh Ralph round.
        maxRounds: Optional positive safe-integer round cap, bounded by the deployment ceiling."""
        # DSH does not enforce a recursion ban (README "Known Limitations"); the round prompt only asks.
        objective = objective.strip()
        if not objective:
            raise ToolException("Ralph objective must be a non-empty string")
        cap = max_rounds if maxRounds is None else maxRounds
        if isinstance(cap, bool) or not float(cap).is_integer() or cap < 1:
            raise ToolException("Ralph maxRounds must be a positive safe integer")
        cap = int(cap)
        if cap > max_rounds:
            raise ToolException(f"Ralph maxRounds {cap} exceeds the deployment ceiling {max_rounds}")
        previous: dict[str, Any] | None = None
        for round_no in range(1, cap + 1):
            prompt = dsh_round_prompt(objective, round_no, cap, previous)
            try:
                raw = _run_child(make_child, DSH_REPORT_SCHEMA, prompt, config)
            except Exception as exc:  # an ordinary child failure ends the run (no retry)
                emit({"round": round_no, "decision": "round-failed", "error": repr(exc)[:300]})
                handoff = "No previous handoff was available." if previous is None else \
                    "Last successful handoff:\n" + json.dumps(previous, indent=2, ensure_ascii=False)
                raise ToolException(_bound(f"Ralph round {round_no} child failed before producing a structured report.\n{handoff}",
                                           max_result_chars)) from exc
            if raw is None:  # no structured_output call: the workflow's agent() returned null
                emit({"round": round_no, "decision": "round-failed", "error": "no structured report"})
                handoff = "No previous handoff was available." if previous is None else \
                    "Last successful handoff:\n" + json.dumps(previous, indent=2, ensure_ascii=False)
                raise ToolException(_bound(f"Ralph round {round_no} child failed before producing a structured report.\n{handoff}",
                                           max_result_chars))
            try:
                report = validate_dsh_report(raw, max_handoff_chars)
            except ValueError as exc:  # thrown inside the fixed script: the whole workflow stops with an error
                emit({"round": round_no, "decision": "error", "error": str(exc)[:300]})
                raise ToolException(f"Ralph workflow failed: {exc}") from exc
            decision = "complete" if report["status"] == "complete" else "blocked" if report["status"] == "blocked" else "continue"
            emit({"round": round_no, "worker_status": report["status"], "summary": report["summary"],
                  "handoff_chars": len(json.dumps(report, separators=(",", ":"))), "decision": decision})
            if decision != "continue":
                return dsh_render(decision, round_no, report, max_result_chars)
            previous = report
        emit({"round": cap, "decision": "budget-limited"})
        return dsh_render("budget-limited", cap, previous or {}, max_result_chars)

    ralph.handle_tool_error = True
    return ralph


class RalphGuidance(AgentMiddleware):
    """The `tool:ralph` system prompt section (DSH appends it to every parent request)."""

    def __init__(self, text: str) -> None:
        self.text = text

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        system = request.system_message
        base = _text(system) if system is not None else ""
        return handler(request.override(system_message=SystemMessage(f"{base}\n\n{self.text}" if base else self.text)))


# ── verified: dsh/bundles/verified-ralph (the Creator-built Custom RALPH), ported line by line ──
# Strings, schema, normalization, progress format and result text match index.js. The loop
# decides with the deployment's verify command, never with the worker's own "complete".

VERIFIED_DESCRIPTION = (
    "Run a foreground verified Ralph loop toward one immutable objective. Each round starts one fresh child through the "
    "configured subagent provider; only the objective, the previous verifier result, and the previous worker report cross "
    "rounds, and the workspace plus the progress file are the durable memory. The plugin appends every round to the "
    "progress file itself. When a verify command is configured it runs after every worker round: exit 0 ends the loop as "
    "verified, so a worker \"complete\" is never trusted on its own. Without one, a worker \"complete\" ends as "
    "self-reported. A worker \"blocked\" ends as blocked, and the round ceiling ends as budget-limited. Use it when a "
    "deployment wants fresh-agent iteration whose completion is machine-checked."
)
VERIFIED_REPORT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "status": {
            "type": "string",
            "enum": ["continue", "complete", "blocked"],
            "description": "continue while useful in-scope work remains; complete only when the objective is met; blocked "
                           "only when no meaningful progress is possible without human input or an external state change.",
        },
        "summary": {"type": "string", "description": "A short factual account of what this round did and found."},
        "nextSteps": {"type": "array", "items": {"type": "string"},
                      "description": "Concrete remaining work in order; empty when status is complete or blocked."},
        "blocker": {"type": "string", "description": "The concrete blocker; empty unless status is blocked."},
    },
    "required": ["status", "summary", "nextSteps", "blocker"],
}
VERIFIED_PROGRESS_HEADER = "# Verified RALPH progress log\n\n"


def read_verified_report(value: Any) -> dict[str, Any] | None:
    """index.js `readReport`: normalize (trim, drop empty steps) or return None."""
    if not isinstance(value, dict) or value.get("status") not in ("continue", "complete", "blocked"):
        return None
    summary, steps, blocker = value.get("summary"), value.get("nextSteps"), value.get("blocker")
    if not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(steps, list) or any(not isinstance(x, str) for x in steps) or not isinstance(blocker, str):
        return None
    return {"status": value["status"], "summary": summary.strip(),
            "nextSteps": [x.strip() for x in steps if x.strip()], "blocker": blocker.strip()}


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def verified_round_prompt(objective: str, round_no: int, max_rounds: int, progress_file: str,
                          previous_report: dict[str, Any] | None, previous_verifier: dict[str, Any] | None,
                          max_feedback_chars: int) -> str:
    """index.js `buildRoundPrompt`."""
    parts = [
        "You are the worker for one round of a Ralph loop toward one immutable objective. You start with no parent "
        "conversation and no earlier session. Do not call the verified_ralph tool from this round; you are already its worker.",
        f"Immutable objective:\n{objective}",
        f"Round {round_no} of {max_rounds}.",
        f"The shared workspace and the progress file at {progress_file} are the durable memory. Inspect them first, keep all "
        "existing work, and make concrete in-scope progress. Verify what you change.",
    ]
    if previous_verifier is None:
        parts.append("Previous round verifier result: none — this is the first round.")
    else:
        note = " (timed out)" if previous_verifier["timedOut"] else ""
        parts.append(f"Previous round verifier result: exit code {previous_verifier['exitCode']}{note}.\n"
                     f"Last {max_feedback_chars} characters of its output:\n{previous_verifier['tail']}")
    parts.append("Previous worker report: none — this is the first round." if previous_report is None
                 else f"Previous worker report:\n{json.dumps(previous_report, indent=2, ensure_ascii=False)}")
    parts.append(
        'Report the outcome by calling structured_output exactly once: status "continue" while useful in-scope work '
        'remains, "complete" only when the objective is met, or "blocked" only when no meaningful progress is possible '
        "without human input or an external state change. Keep summary factual, list concrete nextSteps, and leave blocker "
        "empty unless blocked.")
    return "\n\n".join(parts)


def run_verifier(command: str, cwd: Any, timeout_ms: int) -> dict[str, Any]:
    """index.js `runVerifier`: shell, caller cwd, combined output, process-group kill on timeout. Never raises."""
    import os
    import signal as signals

    try:
        proc = subprocess.Popen(command, shell=True, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, start_new_session=True, env=os.environ.copy())
    except OSError as exc:
        return {"exitCode": "spawn-error", "passed": False, "timedOut": False, "output": str(exc)}
    try:
        out, _ = proc.communicate(timeout=timeout_ms / 1000)
        timed_out = False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signals.SIGKILL)
        except ProcessLookupError:
            pass
        out, _ = proc.communicate()
        timed_out = True
    output = (out or b"").decode("utf-8", "replace")
    if timed_out:
        code = "timeout"
    elif proc.returncode is not None and proc.returncode >= 0:
        code = str(proc.returncode)
    else:
        code = f"signal:{signals.Signals(-proc.returncode).name}" if proc.returncode else "no-exit-code"
    return {"exitCode": code, "passed": code == "0", "timedOut": timed_out, "output": output}


def verified_progress_chunk(round_no: int, report: dict[str, Any], verifier: dict[str, Any] | None, max_feedback_chars: int) -> str:
    """index.js `progressChunk`."""
    lines = [
        f"## Round {round_no}",
        f"- Worker status: {report['status']}",
        f"- Worker summary: {_one_line(report['summary'])}",
        f"- Worker next steps: {'(none)' if not report['nextSteps'] else '; '.join(_one_line(x) for x in report['nextSteps'])}",
        f"- Worker blocker: {'(none)' if not report['blocker'] else _one_line(report['blocker'])}",
    ]
    if verifier is None:
        lines.append("- Verifier: not run")
    else:
        lines.append(f"- Verifier: {'passed' if verifier['passed'] else 'failed'} (exit code {verifier['exitCode']}"
                     f"{', timed out' if verifier['timedOut'] else ''})")
        if verifier["output"]:
            lines += ["", f"Verifier output tail (last up to {max_feedback_chars} characters):", "```",
                      verifier["output"][-max_feedback_chars:].rstrip(), "```"]
    return "\n".join(lines) + "\n\n"


def verified_render(result: dict[str, Any]) -> str:
    """index.js `renderMessage`."""
    n = result["roundsStarted"]
    lines = [f"verified_ralph ended as {result['status']} after {n} round{'' if n == 1 else 's'}."]
    if not result["verifierRounds"]:
        lines.append("Verifier: not configured; no round was machine-checked.")
    else:
        checks = ", ".join(f"round {v['round']} {'pass' if v['passed'] else 'fail'} (exit {v['exitCode']})" for v in result["verifierRounds"])
        lines.append(f"Verifier: {checks}.")
    if result["failure"]:
        lines.append(f"Failure: {result['failure']}")
    lines.append(f"Progress file: {result['progressFile']}")
    lines.append("Last worker report: none." if result["lastWorkerReport"] is None
                 else f"Last worker report:\n{json.dumps(result['lastWorkerReport'], indent=2, ensure_ascii=False)}")
    if result["lastVerifierOutputTail"]:
        lines.append(f"Last verifier output tail:\n{result['lastVerifierOutputTail']}")
    return "\n".join(lines)


def verified_ralph_tool(make_child: ChildFactory, emit: Emit, workdir: Any, verify_command: str, max_rounds: int = 5,
                        verify_timeout_ms: int = 120_000, progress_file: str = ".ralph/progress.md", max_feedback_chars: int = 4000) -> Any:
    """index.js `apply` + `execute` (config defaults as DEFAULTS; the week2 preset sets maxRounds 5 and verifyCommand)."""
    import os

    @tool("verified_ralph", description=VERIFIED_DESCRIPTION)
    def verified_ralph(objective: str, config: RunnableConfig, maxRounds: int | None = None) -> str:  # noqa: N803 - plugin schema
        """objective: The immutable completion objective every round works toward.
        maxRounds: Optional positive round cap. Defaults to the deployment cap, which is also the maximum accepted value."""
        if not isinstance(objective, str) or not objective.strip():
            raise ToolException("verified_ralph objective must be a non-empty string")
        objective = objective.strip()
        cap = max_rounds
        if maxRounds is not None:
            if isinstance(maxRounds, bool) or not isinstance(maxRounds, int) or maxRounds < 1:
                raise ToolException("verified_ralph maxRounds must be a positive safe integer")
            if maxRounds > max_rounds:
                raise ToolException(f"verified_ralph maxRounds {maxRounds} exceeds the deployment ceiling {max_rounds}")
            cap = maxRounds
        cwd = str(workdir)
        progress = progress_file if os.path.isabs(progress_file) else os.path.join(cwd, progress_file)
        verifier_rounds: list[dict[str, Any]] = []
        last_tail, failure, status, settled = "", "", "budget-limited", False
        last_report: dict[str, Any] | None = None
        previous_report: dict[str, Any] | None = None
        previous_verifier: dict[str, Any] | None = None
        rounds = 0
        for round_no in range(1, cap + 1):
            rounds = round_no
            prompt = verified_round_prompt(objective, round_no, cap, progress, previous_report, previous_verifier, max_feedback_chars)
            report: dict[str, Any] | None = None
            last_failure = ""
            for attempt in (1, 2):
                try:
                    raw = _run_child(make_child, VERIFIED_REPORT_SCHEMA, prompt, config,
                                     label=f"verified_ralph round {round_no}/{cap} attempt {attempt}")
                except Exception as exc:  # the child stopped without completing (index.js: stopReason !== completed)
                    last_failure = f'child stopped with "error": {exc}'
                    emit({"round": round_no, "attempt": attempt, "error": repr(exc)[:300]})
                    continue
                report = read_verified_report(raw)
                if report is None:
                    last_failure = "child returned no valid structured report"
                    emit({"round": round_no, "attempt": attempt, "error": last_failure})
                else:
                    break
            if report is None:
                status, failure, settled = "round-failed", last_failure or "child failed without a report", True
                emit({"round": round_no, "decision": "round-failed", "error": failure[:300]})
                break
            last_report = report
            verifier = None
            if verify_command:
                verifier = run_verifier(verify_command, cwd, verify_timeout_ms)
                last_tail = verifier["output"][-max_feedback_chars:]
                verifier_rounds.append({"round": round_no, "exitCode": verifier["exitCode"],
                                        "passed": verifier["passed"], "timedOut": verifier["timedOut"]})
            os.makedirs(os.path.dirname(progress), exist_ok=True)
            prefix = "" if os.path.exists(progress) else VERIFIED_PROGRESS_HEADER
            with open(progress, "a", encoding="utf-8") as fh:
                fh.write(prefix + verified_progress_chunk(round_no, report, verifier, max_feedback_chars))
            if verifier is not None and verifier["passed"]:
                status, settled = "verified", True
            elif report["status"] == "blocked":
                status, settled = "blocked", True
            elif verifier is None and report["status"] == "complete":
                status, settled = "self-reported", True
            emit({"round": round_no, "worker_status": report["status"], "summary": report["summary"],
                  "verify_exit": None if verifier is None else (int(verifier["exitCode"]) if verifier["exitCode"].lstrip("-").isdigit() else verifier["exitCode"]),
                  "verify_tail": None if verifier is None else verifier["output"][-300:],
                  "decision": status if settled else "continue"})
            if settled:
                break
            previous_report = report
            previous_verifier = None if verifier is None else {
                "exitCode": verifier["exitCode"], "timedOut": verifier["timedOut"], "tail": verifier["output"][-max_feedback_chars:]}
        if not settled:
            status = "budget-limited"
            emit({"round": rounds, "decision": "budget-limited"})
        return verified_render({"status": status, "roundsStarted": rounds, "verifierRounds": verifier_rounds,
                                "lastVerifierOutputTail": last_tail, "lastWorkerReport": last_report,
                                "progressFile": progress, "failure": failure})

    verified_ralph.handle_tool_error = True
    return verified_ralph


# ── judge: same thread, a separate model call decides whether to go on ───────
# Our design: the judge answers done / reason / next, nothing else. No confidence threshold (there is
# no principled value for one) and no stop on tool errors (failing tests are part of the work); the
# loop ends when the judge says done, its reply is unreadable, or the round cap is reached. Feedback
# is capped at 4000 characters, the same budget the verified loops give a verifier's output.

JUDGE_PROMPT = """You check whether an assistant has fully met the user's objective in its workspace.
Reply with JSON only: {"done": true|false, "reason": "<one sentence>", "next": "<next message>"}.
"done" is true only when the whole objective is met. When it is false, "next" is the message the user sends next:
the most important concrete thing still missing or wrong, written to the assistant. When "done" is true, "next" is empty."""
FEEDBACK_CHARS = 4000


class JudgeState(AgentState):
    judge_rounds: NotRequired[int]


class JudgeContinuation(AgentMiddleware):
    """After each turn, a separate call to the same model judges the objective; if not done, its `next`
    becomes the next user message in the same thread (jump back to the model)."""

    state_schema = JudgeState

    def __init__(self, model: Any, emit: Emit, max_rounds: int = 5) -> None:
        self.model = model
        self.emit = emit
        self.max_rounds = max_rounds

    @hook_config(can_jump_to=["model"])
    def after_agent(self, state: JudgeState, runtime: Any) -> dict[str, Any] | None:
        round_no = int(state.get("judge_rounds") or 0) + 1  # the turn that just ended
        messages = state.get("messages") or []
        objective = next((_text(m) for m in messages if isinstance(m, HumanMessage)), "")
        answer = next((_text(m) for m in reversed(messages) if isinstance(m, AIMessage) and _text(m).strip()), "")
        recent = "\n".join(f"{m.type}: {_text(m)[:600]}" for m in messages[-16:])
        prompt = f"Objective:\n{objective}\n\nAssistant's latest answer:\n{answer}\n\nRecent turns:\n{recent}"
        try:
            reply = self.model.invoke([SystemMessage(JUDGE_PROMPT), HumanMessage(prompt)],
                                      config={"run_name": "ralph_judge", "tags": ["ralph_judge"], "metadata": {"ralph_judge": True}})
            text = _text(reply).strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            decision = json.loads(text)
            done = bool(decision["done"])
        except Exception as exc:  # noqa: BLE001 - an unreadable judge ends the loop
            self.emit({"round": round_no, "decision": "stop-judge-error", "error": repr(exc)[:300]})
            return None
        nxt = str(decision.get("next") or "").strip()[:FEEDBACK_CHARS]
        if done or not nxt:
            self.emit({"round": round_no, "judge": {"done": done, "reason": decision.get("reason")}, "decision": "complete"})
            return None
        if round_no >= self.max_rounds:
            self.emit({"round": round_no, "judge": {"done": False, "reason": decision.get("reason")}, "decision": "budget-limited"})
            return None
        self.emit({"round": round_no, "judge": {"done": False, "reason": decision.get("reason")},
                   "handoff_chars": len(nxt), "decision": "continue"})
        return {"messages": [HumanMessage(nxt)], "judge_rounds": round_no, "jump_to": "model"}


# ── check: same thread, the deployment's verify command decides ──────────────
# The same-session counterpart of verified_ralph: identical verifier, cap and feedback size, but the
# rounds share one growing conversation instead of starting fresh children.

class CheckState(AgentState):
    check_rounds: NotRequired[int]


def check_feedback(verifier: dict[str, Any], round_no: int, max_rounds: int) -> str:
    note = " (timed out)" if verifier["timedOut"] else ""
    return (f"The deployment check for this objective still fails: exit code {verifier['exitCode']}{note} after round "
            f"{round_no} of {max_rounds}.\nLast {FEEDBACK_CHARS} characters of its output:\n{verifier['output'][-FEEDBACK_CHARS:]}\n\n"
            "Continue in this session: fix what the check reports, keep existing work, verify your changes, then end your turn.")


class CheckContinuation(AgentMiddleware):
    """After each turn, run the verify command in the workspace: exit 0 ends the loop; otherwise its output
    becomes the next user message (same thread) until the round cap."""

    state_schema = CheckState

    def __init__(self, emit: Emit, workdir: Any, verify_command: str, max_rounds: int = 5, timeout_ms: int = 120_000) -> None:
        self.emit = emit
        self.workdir = workdir
        self.verify_command = verify_command
        self.max_rounds = max_rounds
        self.timeout_ms = timeout_ms

    @hook_config(can_jump_to=["model"])
    def after_agent(self, state: CheckState, runtime: Any) -> dict[str, Any] | None:
        round_no = int(state.get("check_rounds") or 0) + 1
        verifier = run_verifier(self.verify_command, str(self.workdir), self.timeout_ms)
        code = verifier["exitCode"]
        exit_code = int(code) if code.lstrip("-").isdigit() else code
        if verifier["passed"]:
            self.emit({"round": round_no, "verify_exit": exit_code, "decision": "verified"})
            return None
        if round_no >= self.max_rounds:
            self.emit({"round": round_no, "verify_exit": exit_code, "verify_tail": verifier["output"][-300:], "decision": "budget-limited"})
            return None
        self.emit({"round": round_no, "verify_exit": exit_code, "verify_tail": verifier["output"][-300:], "decision": "continue"})
        return {"messages": [HumanMessage(check_feedback(verifier, round_no, self.max_rounds))],
                "check_rounds": round_no, "jump_to": "model"}


# ── reset: same thread, the worker hands off and the context is wiped ────────

HANDOFF_DESCRIPTION = (
    "End the current round of the Ralph loop. Call this once, as your last action of the round, with what you did and "
    "what remains. status continue starts a new round with an empty context that sees only the objective and this "
    "handoff; complete or blocked ends the loop."
)
RESET_GUIDANCE = (
    "You work in rounds of a Ralph loop. The workspace is your durable memory: each new round starts with an empty "
    "conversation that holds only the objective and the previous round's handoff. End every round by calling "
    "ralph_handoff."
)


class ResetState(AgentState):
    ralph_round: NotRequired[int]
    ralph_objective: NotRequired[str]
    ralph_handoff: NotRequired[dict[str, Any] | None]


@tool("ralph_handoff", description=HANDOFF_DESCRIPTION)
def ralph_handoff(status: str, summary: str, nextSteps: list[str], blocker: str, runtime: ToolRuntime) -> Command:  # noqa: N803
    """status: continue, complete or blocked.
    summary: What this round did, verified against the workspace.
    nextSteps: What the next round should do (empty unless continue).
    blocker: Why no progress is possible (empty unless blocked)."""
    if status not in ("continue", "complete", "blocked"):
        raise ValueError("status must be continue, complete or blocked")
    handoff = {"status": status, "summary": summary, "nextSteps": nextSteps, "blocker": blocker}
    return Command(update={"ralph_handoff": handoff,
                           "messages": [ToolMessage("Handoff recorded. Finish this round now.", tool_call_id=runtime.tool_call_id)]})


class ResetHandoff(AgentMiddleware):
    """When a turn ends with a `continue` handoff, remove every message and start the next round from the
    objective plus the handoff note, on the same thread (one checkpoint history, no new agent)."""

    state_schema = ResetState
    tools = [ralph_handoff]

    def __init__(self, emit: Emit, max_rounds: int = 5) -> None:
        self.emit = emit
        self.max_rounds = max_rounds

    def before_agent(self, state: ResetState, runtime: Any) -> dict[str, Any] | None:
        if state.get("ralph_objective"):
            return None
        first = next((_text(m) for m in state.get("messages") or [] if isinstance(m, HumanMessage)), "")
        return {"ralph_objective": first, "ralph_round": 1, "ralph_handoff": None}

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        base = _text(request.system_message) if request.system_message is not None else ""
        return handler(request.override(system_message=SystemMessage(f"{base}\n\n{RESET_GUIDANCE}" if base else RESET_GUIDANCE)))

    @hook_config(can_jump_to=["model"])
    def after_agent(self, state: ResetState, runtime: Any) -> dict[str, Any] | None:
        round_no = int(state.get("ralph_round") or 1)
        handoff = state.get("ralph_handoff")
        if not handoff:
            self.emit({"round": round_no, "decision": "stop-no-handoff"})
            return None
        decision = handoff["status"] if handoff["status"] != "continue" else ("continue" if round_no < self.max_rounds else "budget-limited")
        self.emit({"round": round_no, "worker_status": handoff["status"], "summary": handoff["summary"],
                   "handoff_chars": len(json.dumps(handoff, ensure_ascii=False)), "decision": decision})
        if decision != "continue":
            return None
        note = (f"{state.get('ralph_objective', '')}\n\n---\nRalph round {round_no + 1} of {self.max_rounds}. Your context was reset; "
                f"the workspace holds all earlier work. Handoff from the previous round:\n{json.dumps(handoff, ensure_ascii=False)}")
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), HumanMessage(note)],
                "ralph_round": round_no + 1, "ralph_handoff": None, "jump_to": "model"}


def emitter(sink: list[dict[str, Any]], mechanism: str) -> Emit:
    return _emit_to(sink, mechanism)
