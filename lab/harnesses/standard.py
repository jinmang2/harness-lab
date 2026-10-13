"""`standard`: the deepagents default stack, the closest match to DSH standard.

| DSH standard row            | here                                              |
|-----------------------------|---------------------------------------------------|
| persona + agent-instructions| system_prompt (+ deepagents base prompt)          |
| tool-bash, tool-fs, fs-search| LocalShellBackend -> execute, ls/read/write/edit/glob/grep |
| tool-todo                   | TodoListMiddleware (write_todos)                  |
| tool-subagent               | SubAgentMiddleware (task)                         |
| compaction-basic            | SummarizationMiddleware                           |
| tool-web (fetch)            | fetch_url                                         |
| tool-skill                  | not here; see `tools-skills`                      |
| plan mode, goal, workflow   | no equivalent (DSH-only)                          |
"""

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend

from lab.harnesses import BuildContext, harness
from lab.harnesses.common import fetch_url, interrupts, shell_env


def prompt(ctx: BuildContext) -> str:
    return f"You are a coding agent powered by the {ctx.model_name} model.\n\nYour working directory is {ctx.workdir}."


def backend(ctx: BuildContext) -> LocalShellBackend:
    return LocalShellBackend(root_dir=ctx.workdir, virtual_mode=False, timeout=300, env=shell_env())


@harness("standard", "deepagents default stack (todo, fs, shell, subagent, summarization) + fetch_url")
def build(ctx: BuildContext):
    return create_deep_agent(
        ctx.model, tools=[fetch_url], system_prompt=prompt(ctx), backend=backend(ctx),
        interrupt_on=interrupts(ctx), checkpointer=ctx.checkpointer,
    )
