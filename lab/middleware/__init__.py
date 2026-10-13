"""Hand-written middleware, one per study topic.

Each mirrors a DeepSeek Harness plugin so the two can be compared directly:

- `HookLogger`         : records when every hook fires (study: agent loop anatomy)
- `RepeatToolCallGuard`: dsh-guard `repeat-tool-reminder`
- `ToolResultPruner`   : dsh-compaction `tool-result-pruner`
"""

from lab.middleware.guards import RepeatToolCallGuard, ToolResultPruner
from lab.middleware.hook_logger import HookLogger

__all__ = ["HookLogger", "RepeatToolCallGuard", "ToolResultPruner"]
