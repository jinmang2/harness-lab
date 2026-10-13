"""Evaluation metrics from the All-About-Harness README that need more than counting.

- Tool Selection Accuracy: tools are grouped into categories so harnesses with different
  tool names (bash / execute, fetch_url / web_fetch) are judged on the same terms.
  A task declares `tools: {allowed: [categories], required: bool}`.
    accuracy = calls in allowed (+ neutral planning) categories / all calls
    no calls -> 1.0 if not required, 0.0 if required
- Failure / Recovery: tool errors during the run, and whether the run still ended well.
- Output Quality: LLM-as-judge against the task's `rubric` (`lab judge`). Optional,
  because it costs model calls; the judge model is LAB_JUDGE_MODEL_SPEC or the lab model.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

CATEGORIES: dict[str, set[str]] = {
    "shell": {"bash", "execute", "shell", "pwsh"},
    "web": {"fetch_url", "web_fetch", "web_search"},
    "read": {"read_file", "read", "ls", "glob", "grep", "read_image"},
    "write": {"write_file", "edit_file", "write", "edit"},
    "plan": {"write_todos", "todo_write", "exit_plan_mode"},
    "delegate": {"task", "subagent", "subagent_fork", "send_message", "list_agents"},
    "skill": {"skill"},
}
NEUTRAL = {"plan"}  # bookkeeping tools never count against selection


def category(tool: str) -> str:
    return next((c for c, names in CATEGORIES.items() if tool in names), "other")


def tool_selection(tool_sequence: list[str], spec: dict[str, Any] | None) -> dict[str, Any] | None:
    if not spec:
        return None
    allowed = set(spec.get("allowed") or []) | NEUTRAL
    required = bool(spec.get("required"))
    counted = [t for t in tool_sequence if category(t) not in NEUTRAL]
    if not counted:
        return {"accuracy": 0.0 if required else 1.0, "required_met": not required, "off_target": []}
    hits = [t for t in counted if category(t) in allowed]
    return {
        "accuracy": round(len(hits) / len(counted), 3),
        "required_met": bool(hits) or not required,
        "off_target": sorted({t for t in counted if category(t) not in allowed}),
    }


def recovery(summary: dict[str, Any]) -> dict[str, Any]:
    errors = int(summary.get("tool_errors") or 0)
    ended_well = summary.get("status") == "ok" and summary.get("check") is not False
    return {"tool_errors": errors, "recovered": (ended_well if errors else None)}


# ── LLM-as-judge ─────────────────────────────────────────────────────────────

JUDGE_MARKER = "harness-lab-judge"
JUDGE_SYSTEM = f"""You are a strict grader ({JUDGE_MARKER}). Grade an AI agent's final answer to a task.
Score each rubric criterion from 1 (fails) to 5 (fully meets). Judge only what is shown; do not reward length.
Reply with JSON only: {{"scores": {{"<criterion>": <1-5>, ...}}, "overall": <1-5>, "reason": "<one or two sentences>"}}"""


def _workspace_excerpt(workdir: Path, limit: int = 6000) -> str:
    parts, used = [], 0
    for path in sorted(workdir.rglob("*")):
        if not path.is_file() or path.stat().st_size > 20_000 or any(p.startswith(".") for p in path.relative_to(workdir).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        chunk = f"--- {path.relative_to(workdir)} ---\n{text[:2000]}\n"
        if used + len(chunk) > limit:
            break
        parts.append(chunk)
        used += len(chunk)
    return "".join(parts) or "(no files)"


def _parse_json(text: str) -> dict[str, Any]:
    """First JSON object in the reply (tolerates prose or code fences around it)."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            value, _ = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError(f"judge returned no JSON object: {text[:200]!r}")


def judge_run(prompt: str, final: str, rubric: list[str], workdir: Path) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    if os.environ.get("LAB_JUDGE_MODEL_SPEC"):
        from langchain.chat_models import init_chat_model

        model = init_chat_model(os.environ["LAB_JUDGE_MODEL_SPEC"])
    else:
        from lab.model import make_model

        model = make_model()
    user = (
        f"## Task\n{prompt}\n\n## Rubric\n" + "\n".join(f"- {c}" for c in rubric)
        + f"\n\n## Agent final answer\n{final or '(empty)'}\n\n## Files in the agent's workspace\n{_workspace_excerpt(workdir)}"
    )
    reply = model.invoke([SystemMessage(JUDGE_SYSTEM), HumanMessage(user)])
    content = reply.content
    if not isinstance(content, str):  # content blocks (thinking models): keep the text parts only
        content = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content
                          if not isinstance(b, dict) or b.get("type") in (None, "text"))
    result = _parse_json(content)
    overall = result.get("overall")
    if not (isinstance(overall, int) and 1 <= overall <= 5):
        raise ValueError(f"judge overall must be an integer 1-5, got {overall!r}")
    scores = {str(k): v for k, v in (result.get("scores") or {}).items() if isinstance(v, int) and 1 <= v <= 5}
    usage = getattr(reply, "usage_metadata", None) or {}
    return {
        "scores": scores,
        "overall": overall,
        "reason": str(result.get("reason") or "")[:1000],
        "judge_tokens": int(usage.get("total_tokens") or 0),
    }


def judge_batch(batch_dir: Path, tasks_by_id: dict[str, Any], force: bool = False) -> int:
    """Judge every run whose task has a rubric; store judge.json and update summary.jsonl."""
    from lab.report import write_report

    summary_path = batch_dir / "summary.jsonl"
    summaries = [json.loads(line) for line in summary_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    judged = 0
    for summary in summaries:
        task = tasks_by_id.get(summary["task"])
        if task is None or not task.rubric:
            continue
        run_dir = batch_dir / summary["run_id"]
        out = run_dir / "judge.json"
        if out.exists() and not force:
            result = json.loads(out.read_text(encoding="utf-8"))
        else:
            try:
                result = judge_run(task.prompt, summary.get("final") or "", task.rubric, run_dir / "workspace")
            except Exception as exc:  # one bad judgement must not stop the batch
                result = {"error": repr(exc)}
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            judged += 1
            print(f"judged {summary['run_id']}: {result.get('overall', result.get('error'))}", flush=True)
        summary["quality"] = result.get("overall")
        summary["quality_detail"] = result
    summary_path.write_text("".join(json.dumps(s, ensure_ascii=False) + "\n" for s in summaries), encoding="utf-8")
    write_report(batch_dir)
    return judged
