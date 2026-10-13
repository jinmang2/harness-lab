"""Session goals, modeled on DeepSeek Harness (MIT): `goal`, `tool-goal`, `goal-round-driver`, `command-goal`.

Tool names, schemas, descriptions, result JSON, errors, the `tool:goal` prompt
section, the `<goal_round>` continuation prompt and the wrap-up notices are
copied verbatim. The goal lives in graph state (`goal`), so the checkpointer
keeps it; the chat session (lab/viewer/play.py) drives the rounds the way DSH's
round driver does: when a turn ends idle and the goal is active and armed, it
sends the next `<goal_round>` message.

Differences from DSH, all because this lab has one process and one agent:
activation is stored with the goal instead of process memory (forks disarm it),
and there is no subagent authority check because subagents never get these tools.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal, NotRequired

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langchain.tools import ToolRuntime
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command

DEFAULT_MAX_GOAL_ROUNDS = 256  # goal plugin default
BLOCKED_AFTER = 3  # tool-goal blockedAfterConsecutiveRounds default

GUIDANCE = (
    "Use goal tools for one long-running completion objective in the current session. "
    "create_goal may infer goal intent from a direct human request in any language; do not "
    "create a goal for routine single-turn work. Call get_goal before update_goal and copy its "
    "exact goal_id and revision. After session resume or fork, an active goal is disarmed: when "
    "a human asks to continue or resume in any wording or language, use update_goal action "
    "resume to rearm it. Mark complete only when the objective is actually achieved. Mark "
    f"blocked only after the same blocking condition persists for at least {BLOCKED_AFTER} "
    "consecutive goal rounds, and report that concrete condition in blocked_reason; difficulty, uncertainty, "
    "or useful remaining work is not blocked."
)
CREATE_DESCRIPTION = (
    "Create one persisted same-session completion goal when the current direct human request "
    "is a long-running objective that should continue across autonomous goal rounds. You may "
    'infer that intent without requiring the user to say "create a goal". Do not use this for '
    "trivial single-turn work. Execution rejects non-human and subagent authority."
)
GET_DESCRIPTION = (
    "Read the current same-session goal, including its exact id/revision, objective, phase, completed "
    "continuation rounds, round limit, blocker reason when present, and whether another continuation is armed. "
    "Call this before updating a goal."
)
UPDATE_DESCRIPTION = (
    "Update the exact current goal revision. edit, pause, and resume require a direct "
    "top-level human request. During an automatic continuation of the current goal, complete "
    "and blocked are also allowed. blocked is rejected before the configured minimum round count; the model remains "
    "responsible for judging that the same condition persisted across those rounds and must explain it in blocked_reason."
)
_GROUNDING = (
    "Report only what earlier rounds and tool results in this session actually establish; "
    "when a detail is not in the session, say so instead of inventing it. "
)
USAGE = "Usage: /goal [<objective>|clear|edit <objective>|pause|resume]"


class GoalError(Exception):
    def __init__(self, message: str, code: str) -> None:
        super().__init__(message)
        self.code = code


class GoalState(AgentState):
    goal: NotRequired[dict[str, Any] | None]
    # Who opened this turn: "user", or "goal" for a round the driver sent ({id, revision, round}).
    goal_source: NotRequired[dict[str, Any] | None]
    # A wrap-up notice deferred until the tool batch is done (DSH exec.deferContext).
    goal_context: NotRequired[str | None]


# ── domain (packages/goal/goal) ─────────────────────────────────────────────

def _now() -> int:
    return int(time.time() * 1000)


def _objective(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoalError("goal objective must be a non-empty string", "GOAL_INVALID_OBJECTIVE")
    return value.strip()


def _cap(value: Any) -> int:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1 or value > 2**53 - 1:
        raise GoalError("maxGoalRounds must be a positive safe integer", "GOAL_INVALID_MAX_ROUNDS")
    return value


def _expect(goal: dict[str, Any] | None, ref: tuple[str, int]) -> dict[str, Any]:
    if goal is None:
        raise GoalError("no current goal", "GOAL_NOT_FOUND")
    if (goal["id"], goal["revision"]) != ref:
        raise GoalError(f'stale goal ref "{ref[0]}" revision {ref[1]}; current is "{goal["id"]}" revision {goal["revision"]}',
                        "GOAL_STALE_REVISION")
    return goal


def _transition_error(goal: dict[str, Any], operation: str, allowed: list[str]) -> GoalError:
    return GoalError(f'cannot {operation} goal "{goal["id"]}" in phase "{goal["phase"]}"; allowed from {", ".join(allowed)}',
                     "GOAL_INVALID_TRANSITION")


def _next(goal: dict[str, Any], **changes: Any) -> dict[str, Any]:
    out = {**goal, **changes, "revision": goal["revision"] + 1, "updatedAt": max(_now(), goal["updatedAt"] + 1)}
    if out["phase"] != "blocked":
        out.pop("blockedReason", None)
    return out


def create(goal: dict[str, Any] | None, objective: Any, max_goal_rounds: Any = None) -> dict[str, Any]:
    if goal is not None and goal["phase"] != "complete":
        raise GoalError(f'goal "{goal["id"]}" already exists with phase "{goal["phase"]}"', "GOAL_ALREADY_EXISTS")
    now = _now()
    return {"id": f"goal-{uuid.uuid4()}", "revision": 1, "objective": _objective(objective), "phase": "active",
            "maxGoalRounds": _cap(DEFAULT_MAX_GOAL_ROUNDS if max_goal_rounds is None else max_goal_rounds),
            "roundsStarted": 0, "activation": "armed", "createdAt": now, "updatedAt": now}


def edit(goal: dict[str, Any] | None, ref: tuple[str, int], objective: Any = None, max_goal_rounds: Any = None) -> dict[str, Any]:
    current = _expect(goal, ref)
    if objective is None and max_goal_rounds is None:
        raise GoalError("goal edit requires objective and/or maxGoalRounds", "GOAL_INVALID_EDIT")
    changes: dict[str, Any] = {}
    if objective is not None:
        changes["objective"] = _objective(objective)
    if max_goal_rounds is not None:
        changes["maxGoalRounds"] = _cap(max_goal_rounds)
    return _next(current, **changes)


def pause(goal: dict[str, Any] | None, ref: tuple[str, int]) -> dict[str, Any]:
    current = _expect(goal, ref)
    if current["phase"] != "active":
        raise _transition_error(current, "pause", ["active"])
    return _next(current, phase="paused", activation="disarmed")


def resume(goal: dict[str, Any] | None, ref: tuple[str, int]) -> dict[str, Any]:
    current = _expect(goal, ref)
    if current["phase"] not in ("active", "paused", "blocked"):
        raise _transition_error(current, "resume", ["active", "paused", "blocked"])
    if current["phase"] == "active" and current["activation"] == "armed":
        raise GoalError(f'goal "{current["id"]}" is already active and armed', "GOAL_INVALID_TRANSITION")
    if current["roundsStarted"] >= current["maxGoalRounds"]:
        raise GoalError(f'goal "{current["id"]}" exhausted {current["maxGoalRounds"]} goal rounds; increase maxGoalRounds before resuming',
                        "GOAL_INVALID_TRANSITION")
    return _next(current, phase="active", activation="armed")


def complete(goal: dict[str, Any] | None, ref: tuple[str, int]) -> dict[str, Any]:
    current = _expect(goal, ref)
    if current["phase"] not in ("active", "paused", "blocked"):
        raise _transition_error(current, "complete", ["active", "paused", "blocked"])
    return _next(current, phase="complete", activation="disarmed")


def block(goal: dict[str, Any] | None, ref: tuple[str, int], code: str, message: str) -> dict[str, Any]:
    current = _expect(goal, ref)
    if current["phase"] != "active":
        raise _transition_error(current, "block", ["active"])
    return _next(current, phase="blocked", activation="disarmed", blockedReason={"code": code, "message": message.strip()})


def disarm(goal: dict[str, Any] | None) -> dict[str, Any] | None:
    """Activation is not a revision change in DSH; only the armed flag flips."""
    return None if goal is None else {**goal, "activation": "disarmed"}


def tool_value(goal: dict[str, Any] | None) -> str:
    if goal is None:
        return json.dumps({"goal": None}, separators=(",", ":"))
    g = {k: goal[k] for k in ("id", "revision", "objective", "phase", "roundsStarted", "maxGoalRounds")}
    if goal.get("blockedReason"):
        g["blockedReason"] = goal["blockedReason"]
    return json.dumps({"goal": g, "activation": goal["activation"]}, ensure_ascii=False, separators=(",", ":"))


def round_prompt(goal: dict[str, Any], round_no: int) -> str:
    """goal-round-driver/src/prompt.ts"""
    return (
        "<goal_round>\n"
        f"Objective: {json.dumps(goal['objective'], ensure_ascii=False)}\n"
        f"Round: {round_no}/{goal['maxGoalRounds']}\n\n"
        "Continue working toward the objective in this same session. Treat the current workspace, tool results, "
        "and durable session state as authoritative; inspect them instead of assuming earlier narration is still current. "
        "Make concrete progress and verify the result. Before claiming completion, gather evidence that the whole "
        "objective is achieved, read the current goal, and mark it complete. If work remains, leave the goal active "
        "for the next round. Follow the configured goal-tool policy before reporting a blocker.\n"
        "</goal_round>"
    )


def wrapup(objective: str, blocked_reason: str | None = None) -> str:
    """tool-goal/src/wrapup.ts"""
    heading = f"Objective: {json.dumps(objective, ensure_ascii=False)}\n"
    if blocked_reason is None:
        return ("<goal_complete>\n" + heading
                + "The goal is marked complete and this autonomous run is ending. Write the closing "
                "message to the user now: state the outcome, summarize what was done and how it was "
                "verified, and point to the concrete results (files, commits, or other artifacts). "
                + _GROUNDING
                + "Note anything the user should review or do next. Address the user directly. Do not "
                "call any more tools in this run; further work waits for the user's next instruction.\n"
                "</goal_complete>")
    return ("<goal_blocked>\n" + heading + f"Blocked: {json.dumps(blocked_reason, ensure_ascii=False)}\n"
            + "The goal is marked blocked and this autonomous run is ending. Write the closing "
            "message to the user now: state what has been completed so far, describe the concrete "
            "blocking condition and what you tried, and say exactly what you need from the user to "
            "continue. " + _GROUNDING
            + "Address the user directly. Do not call any more tools in this run; further work "
            "waits for the user's next instruction.\n"
            "</goal_blocked>")


# ── /goal command (command-goal) ─────────────────────────────────────────────

def _hint(goal: dict[str, Any]) -> str:
    if goal["phase"] == "active":
        return ("/goal edit <objective>, /goal pause, /goal clear" if goal["activation"] == "armed"
                else "/goal edit <objective>, /goal resume, /goal clear")
    if goal["phase"] in ("paused", "blocked"):
        return "/goal edit <objective>, /goal resume, /goal clear"
    return "/goal <objective>, /goal clear"


def render(title: str, goal: dict[str, Any]) -> str:
    reason = goal.get("blockedReason") if goal["phase"] == "blocked" else None
    lines = [title, f"Status: {goal['phase']}"]
    if reason:
        lines.append(f"Blocker: {reason['code']}: {reason['message']}")
    lines += [f"Objective: {goal['objective']}", f"Rounds: {goal['roundsStarted']}/{goal['maxGoalRounds']}",
              f"Activation: {goal['activation']}", "", f"Commands: {_hint(goal)}"]
    return "\n".join(lines)


def command(goal: dict[str, Any] | None, raw: str) -> tuple[Literal["success", "error"], str, dict[str, Any] | None, bool]:
    """Run `/goal <raw>`. Returns (kind, text, new goal state, whether the goal changed)."""
    text = raw.strip()
    control = text.lower()
    ref = (goal["id"], goal["revision"]) if goal else None
    try:
        if text == "":
            return ("success", f"No goal is currently set.\n{USAGE}" if goal is None else render("Goal", goal), goal, False)
        if control == "edit":
            return "error", f"Goal editing requires a replacement objective.\n{USAGE}", goal, False
        if control == "clear":
            if goal is None:
                return "success", "No goal to clear.", goal, False
            return "success", "Goal cleared.", None, True
        if control in ("pause", "resume"):
            if goal is None:
                return "error", f"No goal is currently set; /goal {control} requires one. {USAGE}", goal, False
            new = pause(goal, ref) if control == "pause" else resume(goal, ref)  # type: ignore[arg-type]
            return "success", render("Goal paused" if control == "pause" else "Goal resumed", new), new, True
        if control.startswith("edit") and text[4:5].isspace():
            objective = text[4:].strip()
            if goal is None:
                return "error", f"No goal is currently set; /goal edit requires one. {USAGE}", goal, False
            if goal["phase"] == "complete":
                new = create(goal, objective)
                return "success", render("Goal created", new), new, True
            new = edit(goal, ref, objective=objective)  # type: ignore[arg-type]
            return "success", render("Goal updated", new), new, True
        if goal is not None and goal["phase"] != "complete":
            return ("error", f"A goal is already {goal['phase']}. Use /goal edit <objective> to change it or "
                             "/goal clear before replacing it.", goal, False)
        new = create(goal, text)
        return "success", render("Goal created", new), new, True
    except GoalError:
        return "error", "The goal command is not valid for the current state. Run /goal to view available commands.", goal, False


# ── model-facing tools (tool-goal) ──────────────────────────────────────────

def _err(runtime: ToolRuntime, name: str, text: str) -> ToolMessage:
    return ToolMessage(text, tool_call_id=runtime.tool_call_id, name=name, status="error")


def _ok(runtime: ToolRuntime, name: str, goal: dict[str, Any] | None, **extra: Any) -> Command:
    return Command(update={"goal": goal, **extra,
                           "messages": [ToolMessage(tool_value(goal), tool_call_id=runtime.tool_call_id, name=name)]})


def _direct_human(state: dict[str, Any]) -> bool:
    return (state.get("goal_source") or {}).get("kind", "user") == "user"


def _goal_round(state: dict[str, Any], goal: dict[str, Any] | None) -> bool:
    src = state.get("goal_source") or {}
    return (goal is not None and src.get("kind") == "goal" and src.get("goalId") == goal["id"]
            and src.get("revision") == goal["revision"] and src.get("round") == goal["roundsStarted"])


def make_tools() -> list[Any]:
    @tool("get_goal", description=GET_DESCRIPTION)
    def get_goal(runtime: ToolRuntime) -> Any:
        return tool_value(runtime.state.get("goal"))

    @tool("create_goal", description=CREATE_DESCRIPTION)
    def create_goal(
        objective: Annotated[str, "The concrete completion objective inferred from the direct human request."],
        runtime: ToolRuntime,
        max_goal_rounds: Annotated[float | None, "Optional positive safe-integer limit on automatic continuation rounds."] = None,
    ) -> Any:
        if not _direct_human(runtime.state):
            return _err(runtime, "create_goal", "this goal operation requires a direct human turn on a top-level agent")
        try:
            return _ok(runtime, "create_goal", create(runtime.state.get("goal"), objective, max_goal_rounds))
        except GoalError as exc:
            return _err(runtime, "create_goal", str(exc))

    @tool("update_goal", description=UPDATE_DESCRIPTION)
    def update_goal(
        goal_id: Annotated[str, "Exact id returned by get_goal."],
        revision: Annotated[float, "Exact positive revision returned by get_goal."],
        action: Annotated[Literal["edit", "pause", "resume", "complete", "blocked"], "edit | pause | resume | complete | blocked"],
        runtime: ToolRuntime,
        objective: Annotated[str | None, "Replacement objective; valid only with action edit."] = None,
        max_goal_rounds: Annotated[float | None, "Replacement cap; valid only with action edit."] = None,
        blocked_reason: Annotated[str | None, "Concrete blocking condition; required only with action blocked."] = None,
    ) -> Any:
        name = "update_goal"
        state = runtime.state
        goal = state.get("goal")
        if not goal_id or goal_id != goal_id.strip() or not float(revision).is_integer() or revision < 1:
            return _err(runtime, name, "goal_id must be non-empty and revision must be a positive safe integer")
        ref = (goal_id, int(revision))
        has_objective = bool(objective)
        has_cap = max_goal_rounds not in (None, 0)
        try:
            if action == "edit":
                if not _direct_human(state):
                    return _err(runtime, name, "this goal operation requires a direct human turn on a top-level agent")
                if blocked_reason:
                    return _err(runtime, name, "blocked_reason is valid only with action blocked")
                return _ok(runtime, name, edit(goal, ref, objective if has_objective else None, max_goal_rounds if has_cap else None))
            if action in ("pause", "resume"):
                if not _direct_human(state):
                    return _err(runtime, name, "this goal operation requires a direct human turn on a top-level agent")
                if has_objective or has_cap or blocked_reason:
                    return _err(runtime, name, "objective and max_goal_rounds are valid only with action edit; "
                                               "blocked_reason is valid only with action blocked")
                if (action == "resume" and goal is not None and (goal["id"], goal["revision"]) == ref
                        and goal["phase"] == "paused"):
                    return _err(runtime, name, "the model cannot resume a paused goal; the user must resume it")
                return _ok(runtime, name, pause(goal, ref) if action == "pause" else resume(goal, ref))
            in_round = _goal_round(state, goal)
            if not _direct_human(state) and not in_round:
                return _err(runtime, name, "complete and blocked require a direct human turn or the current goal round")
            if has_objective or has_cap:
                return _err(runtime, name, "objective and max_goal_rounds are valid only with action edit")
            if action == "complete" and blocked_reason:
                return _err(runtime, name, "blocked_reason is valid only with action blocked")
            if action == "blocked" and not (blocked_reason or "").strip():
                return _err(runtime, name, "blocked_reason is required with action blocked")
            if action == "blocked" and in_round and not _direct_human(state) and goal["roundsStarted"] < BLOCKED_AFTER:  # type: ignore[index]
                return _err(runtime, name, f"blocked requires at least {BLOCKED_AFTER} consecutive goal rounds; "
                                           f"current round is {goal['roundsStarted']}")  # type: ignore[index]
            new = complete(goal, ref) if action == "complete" else block(goal, ref, "model-reported", blocked_reason or "")
            extra = {}
            if in_round and not _direct_human(state):
                extra["goal_context"] = wrapup(new["objective"], None if action == "complete" else blocked_reason)
            return _ok(runtime, name, new, **extra)
        except GoalError as exc:
            return _err(runtime, name, str(exc))

    return [get_goal, create_goal, update_goal]


class GoalMiddleware(AgentMiddleware):
    """Goal tools, the static `tool:goal` prompt section, and deferred wrap-up notices."""

    state_schema = GoalState

    def __init__(self) -> None:
        super().__init__()
        self.tools = make_tools()

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        notice = state.get("goal_context")
        if not notice:
            return None
        return {"goal_context": None, "messages": [HumanMessage(notice, additional_kwargs={"lab_source": "goal-notice"})]}

    def _with_section(self, request: Any) -> Any:
        base = request.system_message
        text = base.text if base is not None else ""
        return request.override(system_message=SystemMessage(f"{text}\n\n{GUIDANCE}" if text else GUIDANCE))

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return handler(self._with_section(request))

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return await handler(self._with_section(request))
