"""Markdown comparison tables from a batch's summary.jsonl (week-report format)."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

ROWS: list[tuple[str, str]] = [
    ("status", "작업 성공 여부"),
    ("check", "자동 검증(check)"),
    ("quality", "출력 품질 (judge 1-5)"),
    ("selection", "Tool 선택 정확도"),
    ("required", "필요한 Tool 사용"),
    ("off_target", "범주 밖 Tool"),
    ("tool_errors", "Tool 에러"),
    ("recovered", "에러 후 복구"),
    ("interrupts", "승인 요청 (HITL)"),
    ("turn_ms", "실행 시간 (ms)"),
    ("wall_ms", "프로세스 포함 (ms)"),
    ("tools_used", "사용한 Tool"),
    ("tool_calls", "Tool 호출 횟수"),
    ("tool_sequence", "실행 순서"),
    ("llm_calls", "모델 호출 횟수"),
    ("first_input", "첫 요청 입력 Token (고정 오버헤드)"),
    ("first_tools", "첫 요청 Tool 개수"),
    ("input_uncached", "입력 Token (uncached)"),
    ("cache_read", "입력 Token (cached)"),
    ("output", "출력 Token"),
    ("reasoning", "  └ reasoning"),
    ("total_tokens", "총 Token"),
]


def load_summaries(batch_dir: Path) -> list[dict[str, Any]]:
    path = batch_dir / "summary.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _cell(runs: list[dict[str, Any]], key: str) -> str:
    def value(run: dict[str, Any]) -> Any:
        selection = run.get("tool_selection") or {}
        if key == "selection":
            return selection.get("accuracy")
        if key == "required":
            return selection.get("required_met") if selection else None
        if key == "off_target":
            return selection.get("off_target") if selection else None
        if key == "recovered":
            return (run.get("recovery") or {}).get("recovered")
        if key == "first_input":
            return (run.get("first_request") or {}).get("input_billed")
        if key == "first_tools":
            return (run.get("first_request") or {}).get("tool_count")
        return run.get(key)

    values = [value(r) for r in runs]
    if key == "status":
        ok = sum(1 for v in values if v == "ok")
        return f"{ok}/{len(values)} 성공"
    if key == "check":
        known = [v for v in values if v is not None]
        return "—" if not known else f"{sum(1 for v in known if v)}/{len(known)} 통과"
    if key in ("required", "recovered"):
        known = [v for v in values if v is not None]
        return "—" if not known else f"{sum(1 for v in known if v)}/{len(known)}"
    if key == "off_target":
        names = sorted({n for v in values for n in (v or [])})
        return ", ".join(f"`{n}`" for n in names) if names else ("—" if all(v is None for v in values) else "없음")
    if key == "selection":
        numbers = [v for v in values if isinstance(v, (int, float))]
        return "—" if not numbers else f"{mean(numbers):.0%}"
    if key == "quality":
        numbers = [v for v in values if isinstance(v, (int, float))]
        return "—" if not numbers else f"{mean(numbers):.1f}" + (f" (n={len(numbers)})" if len(numbers) > 1 else "")
    if key == "tools_used":
        merged: dict[str, int] = defaultdict(int)
        for v in values:
            for name, count in (v or {}).items():
                merged[name] += count
        return ", ".join(f"`{n}`×{c}" for n, c in sorted(merged.items())) or "없음"
    if key == "tool_sequence":
        seq = values[0] or []
        text = " → ".join(f"`{n}`" for n in seq[:8]) + (" …" if len(seq) > 8 else "")
        return text or "즉시 응답"
    numbers = [v for v in values if isinstance(v, (int, float))]
    if not numbers:
        return "—"
    avg = mean(numbers)
    return f"{avg:,.0f}" if len(numbers) == 1 else f"{avg:,.0f} (n={len(numbers)})"


def render(summaries: list[dict[str, Any]]) -> str:
    by_task: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for s in summaries:
        by_task[s["task"]][f"{s['engine']}/{s['harness']}"].append(s)

    lines = ["# Harness comparison", ""]
    if summaries:
        lines += [f"- batch: `{summaries[0].get('batch')}`", f"- model: `{summaries[0].get('model')}`", ""]
    lines += [
        "토큰은 서로 겹치지 않게 나눴어요: `uncached + cached = 청구된 입력`. "
        "\"첫 요청 입력\"은 도구를 쓰기 전 첫 호출의 입력이라, 하네스의 고정 오버헤드(시스템 프롬프트 + 도구 스키마)를 보여 줘요.",
        "Tool 선택 정확도는 도구를 범주(shell, web, read, write, …)로 묶어 태스크의 `tools.allowed`와 비교한 값이에요. "
        "출력 품질은 `lab judge`를 실행해야 채워져요.",
        "",
    ]
    for task, groups in by_task.items():
        cols = sorted(groups)
        lines += [f"## {task}", "", "| 비교 항목 | " + " | ".join(cols) + " |", "|---|" + "---:|" * len(cols)]
        for key, label in ROWS:
            lines.append(f"| {label} | " + " | ".join(_cell(groups[c], key) for c in cols) + " |")
        errors = [(c, r.get("error")) for c in cols for r in groups[c] if r.get("error")]
        if errors:
            lines += ["", "**Errors**", ""] + [f"- `{c}`: {str(e)[:300]}" for c, e in errors]
        lines += ["", "<details><summary>최종 답변</summary>", ""]
        for c in cols:
            final = (groups[c][0].get("final") or "").strip()
            lines += [f"### {c}", "", final[:3000] or "_(empty)_", ""]
        lines += ["</details>", ""]
    return "\n".join(lines)


def write_report(batch_dir: Path) -> Path:
    path = batch_dir / "report.md"
    path.write_text(render(load_summaries(batch_dir)), encoding="utf-8")
    return path
