"""Plan mode and `ask_user_question`, modeled on DeepSeek Harness (MIT).

DSH packages: `interaction/tool-ask-user`, `plan/plan-mode`. The tool names,
schemas, result texts and the plan-mode prompt section are copied verbatim so
the model sees the same words in both engines.

- `ask_user_question` pauses the graph with a LangGraph `interrupt`; the chat UI
  answers it. Without an interactive session (batch runs, like DSH headless) it
  fails the way DSH does when no answerer exists.
- Plan mode is graph state (`plan_mode`), so the checkpointer keeps it across
  turns. While it is on, the plan section is appended to the system prompt; the
  tool catalog does not change, as in DSH.
- `exit_plan_mode` asks for a plan review through the same interrupt; approval
  turns plan mode off.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Annotated, Any, NotRequired

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import AgentState
from langchain.tools import ToolRuntime
from langchain_core.messages import SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command, interrupt
from pydantic import BaseModel, ConfigDict, Field

# packages/bundle/base/cordis.patch.yml, plan-mode `section`
PLAN_SECTION = """You are in plan mode. Stay in plan mode until exit_plan_mode succeeds or the user switches the session mode. Imperative language to implement changes means plan the implementation, not execute it. A user's conversational agreement — including an answer confirming something you asked — approves nothing and does not end plan mode; fold the confirmed decision into the plan and submit it through exit_plan_mode.

Explore first. Use non-mutating reads, searches, static analysis, and checks to ground the plan in the actual repository. Do not edit or write files, change configuration, run formatters or code generation that rewrites tracked files, commit, or otherwise carry out the plan. Prefer existing functions and patterns over new machinery.

The tool catalog stays the same across modes for request-cache stability. These plan-mode rules override any later tool description or guidance that suggests using mutation tools; those tools remain listed only to keep the request shape stable. Do not use todo_write to track this planning phase: it tracks implementation after an approved plan, while the plan itself belongs in exit_plan_mode.

Resolve discoverable facts by inspection. Use ask_user_question only for user-owned choices or material ambiguity that inspection cannot answer. Do not ask the user where code lives or how current behavior works when you can find out.

Make the plan decision-complete: state the goal and success criteria; group implementation changes by subsystem; identify public API, schema, and data-flow changes; cover edge cases, failure modes, tests, acceptance criteria, and explicit assumptions. Keep it concise enough to review but detailed enough that another engineer can implement it without making design decisions.

When ready, call exit_plan_mode with the complete plan markdown, starting with a # title. Make exit_plan_mode the only and final tool call in that assistant response: it presents the plan for approval, and implementation begins only in a later step after approval. Do not paste the final plan as a plain reply or ask "should I proceed?" through prose or ask_user_question. If review rejects it, incorporate the feedback and present again. If the review channel is unavailable or aborted, stay in plan mode and ask the user to switch modes manually; do not proceed with implementation."""

ASK_DESCRIPTION = (
    "Ask the user a concise question when you need confirmation, a choice, or missing information before proceeding. "
    "Send one or more questions, each with a stable id that will be echoed in the answer."
)
EXIT_DESCRIPTION = (
    "Use only in plan mode. Present your plan for the user's review and, on approval, leave plan mode. "
    "Send the COMPLETE plan as markdown, starting with a # heading that names it. "
    "The user may approve (carry out the plan from your next step) or keep "
    "planning — their feedback comes back in the tool result; revise and present again."
)
APPROVED = "Plan approved — plan mode exited; carry out the plan starting with your next step."
REVIEW_ID = "plan-review"
APPROVE_LABEL = "Approve"
KEEP_PLANNING_LABEL = "Keep planning"
SWITCHED_ON = "The user switched this session to plan mode."
SWITCHED_OFF = "The user switched this session back to the default mode."


class PlanState(AgentState):
    plan_mode: NotRequired[bool]


class _Option(BaseModel):
    model_config = ConfigDict(extra="allow")
    label: str = Field(description="Short user-facing option label.")
    description: str | None = Field(None, description="One sentence explaining the tradeoff or impact.")


class _Question(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(description="Stable id for this question; echoed in the answer.")
    question: str = Field(description="The specific question to ask the user.")
    header: str | None = Field(None, description='Optional short heading for the question, such as "Confirm" or "Choose Mode".')
    options: list[_Option] | None = Field(
        None, description='Optional choices to show the user. If you recommend one, put it first and append "(Recommended)" to that label.')
    multi_select: bool | None = Field(None, description="Whether the user may select more than one option. Defaults to false.")


def _error(runtime: ToolRuntime, name: str, text: str) -> ToolMessage:
    return ToolMessage(text, tool_call_id=runtime.tool_call_id, name=name, status="error")


def _questions(raw: list[_Question]) -> list[dict[str, Any]]:
    out = []
    for q in raw:
        item: dict[str, Any] = {"id": q.id, "question": q.question}
        if q.header is not None:
            item["header"] = q.header
        if q.options is not None:
            item["options"] = [{"label": o.label, **({"description": o.description} if o.description else {})} for o in q.options]
        if q.multi_select is not None:
            item["multiSelect"] = q.multi_select
        out.append(item)
    return out


def _clean_answers(questions: list[dict[str, Any]], reply: Any) -> list[dict[str, Any]]:
    """The UI's reply, reduced to DSH's answer record: one entry per question, in order."""
    given = {a.get("id"): a for a in (reply.get("answers") or []) if isinstance(a, dict)}
    answers = []
    for q in questions:
        a = given.get(q["id"]) or {}
        selected = [s for s in (a.get("selected") or []) if isinstance(s, str)]
        entry: dict[str, Any] = {"id": q["id"], "selected": selected}
        if isinstance(a.get("custom"), str) and a["custom"].strip():
            entry["custom"] = a["custom"].strip()
        answers.append(entry)
    return answers


def _first_heading(plan: str) -> str | None:
    for line in plan.split("\n"):
        m = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
        if m:
            return m.group(1)
    return None


def make_tools(interactive: bool) -> list[Any]:
    @tool("ask_user_question", description=ASK_DESCRIPTION)
    def ask_user_question(
        questions: Annotated[list[_Question], "Questions to ask the user before continuing."],
        runtime: ToolRuntime,
    ) -> Any:
        if not questions:
            return _error(runtime, "ask_user_question", "ask_user_question requires at least one question")
        if not interactive:
            return _error(runtime, "ask_user_question", "no user-questions answerer accepted the request")
        asked = _questions(questions)
        reply = interrupt({"kind": "question", "questions": asked})
        if not isinstance(reply, dict) or reply.get("cancelled"):
            return _error(runtime, "ask_user_question", "the user cancelled ask_user_question")
        return json.dumps({"answers": _clean_answers(asked, reply)}, ensure_ascii=False, separators=(",", ":"))

    @tool("exit_plan_mode", description=EXIT_DESCRIPTION)
    def exit_plan_mode(
        plan: Annotated[str, "The complete plan, as markdown, starting with a # heading that names it."],
        runtime: ToolRuntime,
    ) -> Any:
        if not runtime.state.get("plan_mode"):
            return _error(runtime, "exit_plan_mode", "exit_plan_mode is only available in plan mode")
        if not re.match(r"^#\s+\S", plan.strip()):
            return _error(runtime, "exit_plan_mode", "exit_plan_mode requires a non-empty markdown plan starting with a # heading")
        if not interactive:
            return _error(runtime, "exit_plan_mode", "no user-questions channel is available to review the plan; "
                                   "ask the user to switch the session mode instead")
        review = {
            "id": REVIEW_ID, "header": "Plan review", "question": "Approve this plan and leave plan mode?", "detail": plan,
            "options": [
                {"label": APPROVE_LABEL, "description": "Leave plan mode; the plan is carried out from the next step."},
                {"label": KEEP_PLANNING_LABEL, "description": "Stay in plan mode; feedback goes back to the model."},
            ],
            "intent": {"kind": "plan-review", "approve": APPROVE_LABEL},
        }
        reply = interrupt({"kind": "plan-review", "questions": [review], "title": _first_heading(plan) or "Plan"})
        if not isinstance(reply, dict) or reply.get("cancelled"):
            return _error(runtime, "exit_plan_mode", "The user dismissed the plan review to speak instead; "
                                   "stay in plan mode, stop here, and wait for their message.")
        item = next((a for a in (reply.get("answers") or []) if isinstance(a, dict) and a.get("id") == REVIEW_ID), {})
        custom = item.get("custom") if isinstance(item.get("custom"), str) else None
        if item.get("selected") != [APPROVE_LABEL] or custom is not None:  # any custom answer means keep planning, as in DSH
            return _error(runtime, "exit_plan_mode", f"The user chose to keep planning; their feedback: {custom}" if custom
                          else "The user chose to keep planning; revise the plan and present it again.")
        return Command(update={"plan_mode": False, "messages": [ToolMessage(APPROVED, tool_call_id=runtime.tool_call_id, name="exit_plan_mode")]})

    return [ask_user_question, exit_plan_mode]


class CollaborationMiddleware(AgentMiddleware):
    """`ask_user_question` + `exit_plan_mode` tools and the plan-mode prompt section."""

    state_schema = PlanState

    def __init__(self, interactive: bool = False) -> None:
        super().__init__()
        self.tools = make_tools(interactive)

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        if request.state.get("plan_mode"):
            base = request.system_message
            text = base.text if base is not None else ""
            request = request.override(system_message=SystemMessage(f"{text}\n\n{PLAN_SECTION}" if text else PLAN_SECTION))
        return handler(request)

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        if request.state.get("plan_mode"):
            base = request.system_message
            text = base.text if base is not None else ""
            request = request.override(system_message=SystemMessage(f"{text}\n\n{PLAN_SECTION}" if text else PLAN_SECTION))
        return await handler(request)
