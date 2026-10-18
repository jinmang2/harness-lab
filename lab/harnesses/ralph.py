"""week2 Ralph harnesses: `standard` plus one loop mechanism each (see lab/middleware/ralph.py, ADR-0015).

| harness        | mechanism                                           | DSH counterpart                 |
|----------------|-----------------------------------------------------|---------------------------------|
| ralph-fresh    | `ralph` tool, fresh child per round, worker report  | dsh `ralph-official`            |
| ralph-verified | `verified_ralph` tool, fresh child, verifier command| dsh `ralph-custom` (Creator)    |
| goal           | same thread, `<goal_round>` per round, model marks done | dsh `goal` (Web host)        |
| ralph-judge    | same thread, separate judge call injects next turn  | none                            |
| ralph-check    | same thread, verify command after each turn, output is the next turn | none          |
| ralph-reset    | same thread, handoff tool wipes context per round   | none                            |

Children are the `standard` composition plus a `structured_output` capture tool (DSH driver), built
fresh for every round on a new thread; they share the parent's workspace and trace callbacks.
"""

from __future__ import annotations

import os
from typing import Any

from deepagents import create_deep_agent

from lab import ROOT
from lab.harnesses import BuildContext, harness
from lab.harnesses.common import collaboration, fetch_url, interrupts
from lab.harnesses.standard import backend, prompt
from lab.middleware.ralph import (
    RALPH_GUIDANCE,
    CheckContinuation,
    JudgeContinuation,
    RalphGuidance,
    ResetHandoff,
    StructuredOutput,
    emitter,
    ralph_tool,
    verified_ralph_tool,
)

MAX_ROUNDS = 5
# Deployment-owned verifier, like the DSH preset's `verifyCommand`.
def verify_command() -> str:
    return os.environ.get("LAB_RALPH_VERIFY") or f"python3 {ROOT / 'tasks' / 'checks' / 'week2_verify.py'} ."


def _standard(ctx: BuildContext, tools: list[Any], middleware: list[Any], **kwargs: Any) -> Any:
    return create_deep_agent(
        ctx.model, tools=[fetch_url, *tools], system_prompt=prompt(ctx), backend=backend(ctx),
        middleware=[*collaboration(ctx), *middleware], interrupt_on=interrupts(ctx), checkpointer=ctx.checkpointer, **kwargs,
    )


def _child_factory(ctx: BuildContext, child_tools: list[Any], child_middleware: list[Any]) -> Any:
    """A DSH spawn child: the parent's composition (its loop tool and prompt section included) plus structured_output."""
    child_ctx = BuildContext(model=ctx.model, model_name=ctx.model_name, workdir=ctx.workdir, hooks=ctx.hooks)

    def make(kit: StructuredOutput) -> Any:
        return create_deep_agent(
            child_ctx.model, tools=[fetch_url, *child_tools, kit.tool], system_prompt=prompt(child_ctx), backend=backend(child_ctx),
            middleware=[*collaboration(child_ctx), *child_middleware, kit.middleware],
        )

    return make


@harness("ralph-fresh", "standard + DSH `ralph` rebuilt: fresh child per round, worker-reported completion")
def build_fresh(ctx: BuildContext):
    emit = emitter(ctx.hooks, "fresh")
    tools: list[Any] = []  # DSH children get the full roster, the ralph tool included (only the prompt forbids recursion)
    guidance = RalphGuidance(RALPH_GUIDANCE)
    tools.append(ralph_tool(_child_factory(ctx, tools, [guidance]), emit, max_rounds=MAX_ROUNDS))
    return _standard(ctx, tools, [guidance])


@harness("ralph-verified", "standard + `verified_ralph` (dsh/bundles/verified-ralph ported): a verifier command decides completion")
def build_verified(ctx: BuildContext):
    emit = emitter(ctx.hooks, "verified")
    tools: list[Any] = []  # the preset mounts verified_ralph for every agent of the session, children included
    tools.append(verified_ralph_tool(_child_factory(ctx, tools, []), emit, ctx.workdir, verify_command(), max_rounds=MAX_ROUNDS))
    return _standard(ctx, tools, [])


@harness("goal", "standard + DSH goal: same session, the driver sends `<goal_round>` while the goal is active (cap 5)",
         goal_rounds=MAX_ROUNDS)
def build_goal(ctx: BuildContext):
    return _standard(ctx, [], [])


@harness("ralph-judge", "standard + same-thread continuation: a separate judge call writes the next user turn")
def build_judge(ctx: BuildContext):
    return _standard(ctx, [], [JudgeContinuation(ctx.model, emitter(ctx.hooks, "judge"), max_rounds=MAX_ROUNDS)])


@harness("ralph-check", "standard + same-thread continuation: the verify command checks after each turn, its output is the next turn")
def build_check(ctx: BuildContext):
    return _standard(ctx, [], [CheckContinuation(emitter(ctx.hooks, "check"), ctx.workdir, verify_command(), max_rounds=MAX_ROUNDS)])


@harness("ralph-reset", "standard + handoff tool: same thread, context wiped to objective + handoff each round")
def build_reset(ctx: BuildContext):
    return _standard(ctx, [], [ResetHandoff(emitter(ctx.hooks, "reset"), max_rounds=MAX_ROUNDS)])
