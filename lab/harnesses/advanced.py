"""Study steps 3 (context management) and 6 (delegation, human-in-the-loop).

Context harnesses share `minimal`'s prompt and bash tool so the only variable is how
old context is handled. Triggers are deliberately low so the strategies actually fire
on the `context` tasks; raise them to study production-like settings.

| harness       | strategy                                        | DSH counterpart            |
|---------------|-------------------------------------------------|----------------------------|
| minimal       | none (baseline)                                 | minimal (no compaction)    |
| ctx-prune     | cut each oversized tool result (head + tail)    | tool-result-pruner         |
| ctx-edit      | replace old tool results with a placeholder     | (none)                     |
| ctx-summarize | summarize old messages with the model           | compaction-basic           |
| delegate      | standard + named subagents via `task`           | subagent / workflow        |
| hitl          | standard + approval before shell and file writes| approval policy, plan mode |
"""

from deepagents import create_deep_agent
from langchain.agents import create_agent
from langchain.agents.middleware import ContextEditingMiddleware, SummarizationMiddleware
from langchain.agents.middleware.context_editing import ClearToolUsesEdit

from lab.harnesses import BuildContext, harness
from lab.harnesses.common import approvals, collaboration, fetch_url, interrupts, persistent_bash
from lab.harnesses.minimal import PROMPT as MINIMAL_PROMPT
from lab.harnesses.standard import backend, prompt
from lab.middleware import ToolResultPruner

CONTEXT_TRIGGER_TOKENS = 6000
# Note for ctx-summarize: SummarizationMiddleware keeps the last 6 messages verbatim and,
# by default, feeds only ~4,000 tokens of the older history to the summarizer
# (`trim_tokens_to_summarize`). With 100KB logs that means large results that are still
# recent stay in context, and much of what gets summarized is truncated first. That is
# part of what the experiment measures; tune `keep` / `trim_tokens_to_summarize` to compare.


def _bash_agent(ctx: BuildContext, *extra):
    return create_agent(
        ctx.model,
        system_prompt=MINIMAL_PROMPT,
        middleware=[persistent_bash(ctx.workdir), *extra, *approvals(ctx)],
        checkpointer=ctx.checkpointer,
    )


@harness("ctx-prune", "3: minimal + ToolResultPruner (keep head 4KB / tail 1KB of results over 8KB)")
def build_ctx_prune(ctx: BuildContext):
    return _bash_agent(ctx, ToolResultPruner())


@harness("ctx-edit", f"3: minimal + ContextEditing (clear old tool results past {CONTEXT_TRIGGER_TOKENS} tokens, keep 2)")
def build_ctx_edit(ctx: BuildContext):
    return _bash_agent(ctx, ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=CONTEXT_TRIGGER_TOKENS, keep=2)]))


@harness("ctx-summarize", f"3: minimal + Summarization (summarize past {CONTEXT_TRIGGER_TOKENS} tokens, keep 6 messages)")
def build_ctx_summarize(ctx: BuildContext):
    return _bash_agent(
        ctx, SummarizationMiddleware(ctx.model, trigger=("tokens", CONTEXT_TRIGGER_TOKENS), keep=("messages", 6))
    )


SUBAGENTS = [
    {
        "name": "researcher",
        "description": "Looks up external or live information on the web and returns the facts with their source URLs and timestamps.",
        "system_prompt": "You research one question using fetch_url and report concise facts with source URL and the time the source reports. Do not write files.",
        # `tools` replaces only the custom tools: deepagents still gives every subagent its
        # filesystem/todo middleware, so "do not write files" is a prompt rule, not enforced.
        "tools": [fetch_url],
    },
    {
        "name": "coder",
        "description": "Writes, runs and verifies code or files in the working directory and reports what it ran and the output.",
        "system_prompt": "You implement and verify one well-scoped coding task. Run what you write and report the actual output.",
    },
]


@harness("delegate", "6: standard + researcher/coder subagents; prompt asks to delegate independent parts")
def build_delegate(ctx: BuildContext):
    return create_deep_agent(
        ctx.model,
        tools=[fetch_url],
        system_prompt=prompt(ctx) + "\n\nDelegate independent sub-tasks to the researcher and coder subagents with the task tool, then combine their results.",
        backend=backend(ctx),
        subagents=SUBAGENTS,
        middleware=collaboration(ctx),
        interrupt_on=interrupts(ctx),
        checkpointer=ctx.checkpointer,
    )


HITL_TOOLS = {"execute": True, "write_file": True, "edit_file": True}


@harness("hitl", "6: standard + human approval before execute/write_file/edit_file (batch: LAB_HITL policy)")
def build_hitl(ctx: BuildContext):
    return create_deep_agent(
        ctx.model,
        tools=[fetch_url],
        system_prompt=prompt(ctx),
        backend=backend(ctx),
        middleware=collaboration(ctx),
        interrupt_on=interrupts(ctx, HITL_TOOLS),
        checkpointer=ctx.checkpointer,
    )
