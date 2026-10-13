"""Harness A-D from the All-About-Harness README experiment plan.

    Harness A  Prompt Only
    Harness B  Prompt + Tools
    Harness C  Prompt + Tools + Skill
    Harness D  Custom Harness

Plus `hooks`, which wraps `minimal` with HookLogger to show hook order.
"""

from deepagents import create_deep_agent
from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware, ToolCallLimitMiddleware

from lab import SKILLS_DIR
from lab.harnesses import BuildContext, harness
from lab.harnesses.common import approvals, collaboration, fetch_url, interrupts, persistent_bash
from lab.harnesses.minimal import PROMPT as MINIMAL_PROMPT
from lab.harnesses.standard import backend, prompt
from lab.middleware import HookLogger, RepeatToolCallGuard, ToolResultPruner


@harness("prompt-only", "A: system prompt only, no tools")
def build_prompt_only(ctx: BuildContext):
    return create_agent(ctx.model, system_prompt=MINIMAL_PROMPT, middleware=approvals(ctx), checkpointer=ctx.checkpointer)


@harness("tools", "B: minimal prompt + bash + fetch_url, no framework middleware")
def build_tools(ctx: BuildContext):
    return create_agent(
        ctx.model,
        tools=[fetch_url],
        system_prompt=MINIMAL_PROMPT,
        middleware=[persistent_bash(ctx.workdir), *approvals(ctx)],
        checkpointer=ctx.checkpointer,
    )


@harness("tools-skills", "C: standard + skills/ via deepagents SkillsMiddleware (progressive disclosure)")
def build_tools_skills(ctx: BuildContext):
    return create_deep_agent(
        ctx.model,
        tools=[fetch_url],
        system_prompt=prompt(ctx),
        backend=backend(ctx),
        skills=[str(SKILLS_DIR)],
        middleware=collaboration(ctx),
        interrupt_on=interrupts(ctx),
        checkpointer=ctx.checkpointer,
    )


@harness("custom", "D: standard + hand-written guards + call limit + model retry")
def build_custom(ctx: BuildContext):
    return create_deep_agent(
        ctx.model,
        tools=[fetch_url],
        system_prompt=prompt(ctx),
        backend=backend(ctx),
        middleware=[
            ModelRetryMiddleware(max_retries=2),
            ToolCallLimitMiddleware(run_limit=40),
            RepeatToolCallGuard(threshold=3),
            ToolResultPruner(),
            *collaboration(ctx),
        ],
        interrupt_on=interrupts(ctx),
        checkpointer=ctx.checkpointer,
    )


@harness("hooks", "minimal + HookLogger outer/inner, to observe middleware hook order")
def build_hooks(ctx: BuildContext):
    return create_agent(
        ctx.model,
        system_prompt=MINIMAL_PROMPT,
        middleware=[HookLogger("outer", ctx.hooks), persistent_bash(ctx.workdir), HookLogger("inner", ctx.hooks), *approvals(ctx)],
        checkpointer=ctx.checkpointer,
    )
