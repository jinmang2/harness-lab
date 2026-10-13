"""`minimal`: DeepSeek Harness's minimal preset, rebuilt with plain LangChain.

DSH minimal (packages/preset/agent-presets/presets/minimal/agent.cordis.yml):
- persona `complete: true`  -> the one-line prompt IS the whole system prompt
- includeRuntimeContext: false
- one persistent bash tool, no compaction

`create_agent` (not `create_deep_agent`) adds no middleware of its own, so the
only things the model sees are this prompt and the `bash` schema.
"""

from langchain.agents import create_agent

from lab.harnesses import BuildContext, harness
from lab.harnesses.common import approvals, persistent_bash

PROMPT = "You are a helpful software engineer assistant."


@harness("minimal", "DSH minimal: one-line prompt + one persistent bash tool, nothing else")
def build(ctx: BuildContext):
    return create_agent(
        ctx.model, system_prompt=PROMPT, middleware=[persistent_bash(ctx.workdir), *approvals(ctx)], checkpointer=ctx.checkpointer
    )
