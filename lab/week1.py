"""Week 1 assignment write-up: `result.md` in the format of All-About-Harness workspace/week1/README.md.

    uv run lab run -T tasks/week1-assignment.yaml -e dsh,lab -H minimal,standard -n 3 -l week1 --judge
    uv run lab week1 runs/<batch> --id <GitHub-ID>

Numbers are medians over repeats. The submission uses the DSH engine when the batch has
it (the study compares DSH presets), and lists the lab engine as a reference (ADR-0011).
"Why Minimal is better" is drafted from the measurements; edit it before submitting.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from lab.runner import batch_tasks

EXPERIMENT = "seoul-weather"


def _median(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0


def _one_line(text: str, limit: int = 160) -> str:
    flat = " ".join((text or "").split()).replace("|", "\\|")  # keep markdown table cells intact
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Median numbers and pass counts for the repeats of one task × engine × harness."""
    ok = [r for r in rows if r.get("status") == "ok"]
    numbers = ok or rows  # medians over runs that finished; a crash with 0 tokens is not "cheaper"
    checks = [r.get("check") for r in rows if r.get("check") is not None]
    quality = [r["quality"] for r in rows if isinstance(r.get("quality"), int)]
    tools: list[str] = sorted({t for r in rows for t in r.get("tools_used") or []})
    by_total = sorted(numbers, key=lambda r: r.get("total_tokens") or 0)
    rep = by_total[len(by_total) // 2]  # representative answer: the run with the median token count
    return {
        "n": len(rows),
        "ok": len(ok),
        "passed": sum(1 for c in checks if c),
        "checked": len(checks),
        "quality": round(statistics.mean(quality), 2) if quality else None,
        "input": _median([r.get("input_billed") or 0 for r in numbers]),
        "output": _median([r.get("output") or 0 for r in numbers]),
        "total": _median([r.get("total_tokens") or 0 for r in numbers]),
        "wall_s": round(_median([(r.get("turn_ms") if r.get("turn_ms") is not None else r.get("wall_ms")) or 0 for r in numbers]) / 1000, 1),
        "process_s": round(_median([r.get("wall_ms") or 0 for r in numbers]) / 1000, 1),
        "tool_calls": _median([r.get("tool_calls") or 0 for r in numbers]),
        "tools": tools,
        "answer": _one_line(rep.get("final") or ""),
        "model": rep.get("model"),
    }


def _rate(a: dict[str, Any]) -> float | None:
    return a["passed"] / a["checked"] if a["checked"] else None


def minimal_advantage(m: dict[str, Any], s: dict[str, Any]) -> tuple[bool, tuple, str]:
    """Whether Minimal did better, a sort key, and a drafted reason (Korean, for the submission)."""
    mr, sr = _rate(m), _rate(s)
    mq, sq = m["quality"], s["quality"]
    not_worse = (m["ok"] >= s["ok"] and m["ok"] == m["n"]  # every Minimal run finished
                 and (mr is None or sr is None or mr >= sr) and (mq is None or sq is None or mq >= sq))
    saving = 1 - (m["total"] / s["total"]) if s["total"] else 0
    faster = s["wall_s"] - m["wall_s"]
    better_answer = (mr is not None and sr is not None and mr > sr) or (mq is not None and sq is not None and mq > sq)
    wins = not_worse and (better_answer or saving > 0.2 or faster > 1)
    parts = []
    if mr is not None and sr is not None:
        parts.append(f"정답률 Minimal {m['passed']}/{m['checked']}, Standard {s['passed']}/{s['checked']}")
    if mq is not None and sq is not None:
        parts.append(f"품질 점수(LLM-judge, 5점 만점) Minimal {mq}, Standard {sq}")
    parts.append(f"전체 토큰 {saving:.0%} 적음 ({int(m['total']):,} vs {int(s['total']):,})" if saving > 0 else
                 f"전체 토큰은 Minimal이 더 많음 ({int(m['total']):,} vs {int(s['total']):,})")
    parts.append(f"실행 시간 {faster:.1f}초 빠름" if faster > 0 else f"실행 시간은 {(-faster):.1f}초 느림")
    if s["tool_calls"] > m["tool_calls"]:
        parts.append(f"Standard는 도구를 {s['tool_calls']:g}번 불렀음({', '.join(s['tools']) or '-'})")
    key = (better_answer, saving, faster)
    return wins, key, "; ".join(parts) + "."


def build(batch_dir: Path, github_id: str) -> str:
    summaries = [json.loads(line) for line in (batch_dir / "summary.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    tasks = batch_tasks(batch_dir)
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in summaries:
        groups[(r["task"], r["engine"], r["harness"])].append(r)
    engines = sorted({r["engine"] for r in summaries})
    if not engines:
        raise SystemExit(f"{batch_dir} has no runs")
    primary = "dsh" if "dsh" in engines else engines[0]
    agg = {k: aggregate(v) for k, v in groups.items()}
    model = next((a["model"] for a in agg.values() if a["model"]), "?")
    try:
        started: datetime | None = datetime.strptime(batch_dir.name[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        started = None
    repeats = max((a["n"] for a in agg.values()), default=1)

    def pair(task: str, engine: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        m, s = agg.get((task, engine, "minimal")), agg.get((task, engine, "standard"))
        return (m, s) if m and s else None

    def best_pair(task: str) -> tuple[str, tuple[dict[str, Any], dict[str, Any]]] | None:
        """The primary engine's pair, or another engine's when the primary has none for this task."""
        for e in [primary, *[x for x in engines if x != primary]]:
            p = pair(task, e)
            if p:
                return e, p
        return None

    def row_table(m: dict[str, Any], s: dict[str, Any]) -> list[str]:
        def rate(a: dict[str, Any]) -> str:
            return f"{a['passed']}/{a['checked']}" if a["checked"] else "—"
        return [
            "| 항목 | Minimal mode | Standard mode |",
            "|---|---|---|",
            f"| 답변 요약 | {m['answer'] or '(빈 답변)'} | {s['answer'] or '(빈 답변)'} |",
            f"| 사용 도구 | {', '.join(m['tools']) or '없음'} | {', '.join(s['tools']) or '없음'} |",
            f"| 도구 호출 수 | {m['tool_calls']:g} | {s['tool_calls']:g} |",
            f"| 입력 토큰 | {int(m['input']):,} | {int(s['input']):,} |",
            f"| 출력 토큰 | {int(m['output']):,} | {int(s['output']):,} |",
            f"| 전체 토큰 | {int(m['total']):,} | {int(s['total']):,} |",
            f"| 실행 시간 | {m['wall_s']}초 | {s['wall_s']}초 |",
            f"| 정답 확인 | {rate(m)} | {rate(s)} |",
            f"| 품질 점수 (LLM-judge) | {m['quality'] if m['quality'] is not None else '—'} | {s['quality'] if s['quality'] is not None else '—'} |",
        ]

    out = [
        f"# Week 1 — Skill은 많을수록 좋을까? ({github_id})",
        "",
        f"- 실행 시각: {started.strftime('%Y-%m-%d %H:%M') if started else batch_dir.name} (KST)",
        f"- 모델: `{model}` (Minimal과 Standard 모두 같은 모델, 같은 설정)",
        f"- 실행 환경: DeepSeek Harness `{'headless' if primary == 'dsh' else 'lab 엔진'}` · 질문마다 새 세션 · 각 {repeats}회 실행, 표의 숫자는 중앙값",
        "- 토큰: 입력은 캐시 포함 청구 입력(uncached + cached), 전체 = 입력 + 출력",
        "- 실행 시간: 에이전트가 턴을 시작해서 끝낼 때까지(DSH Web의 \"Ran for\"). headless 프로세스의 부팅·종료 시간은 뺐어요",
        "",
        "## 1. 실험 질문: 오늘 서울 날씨는 어땠어?",
        "",
    ]
    found = best_pair(EXPERIMENT)
    if found:
        exp_engine, (m, s) = found
        if exp_engine != primary:
            out += [f"> 이 질문은 {exp_engine} 엔진 결과예요.", ""]
        out += row_table(m, s)
        out += [
            "",
            f"- 실제 날씨를 확인했는가: Minimal {'예' if m['tools'] else '아니오'} ({', '.join(m['tools']) or '도구 없음'}), "
            f"Standard {'예' if s['tools'] else '아니오'} ({', '.join(s['tools']) or '도구 없음'})",
            f"- 더 많은 기능이 비용을 늘렸는가: 전체 토큰 {int(s['total']):,} vs {int(m['total']):,}, 실행 시간 {s['wall_s']}초 vs {m['wall_s']}초",
            "",
        ]
    else:
        out += ["(이 batch에 실험 질문 결과가 없어요)", ""]

    candidates = []
    for tid in tasks:
        if tid == EXPERIMENT:
            continue
        found = best_pair(tid)
        if not found:
            continue
        engine, p = found
        wins, key, reason = minimal_advantage(*p)
        if engine != primary:
            reason += f" ({engine} 엔진 결과)"
        candidates.append((wins, key, tid, reason, p))
    winners = sorted([c for c in candidates if c[0]], key=lambda c: c[1], reverse=True)[:3]

    out += ["## 2. Standard mode보다 Minimal mode가 더 잘 답한 질문 3개", ""]
    if len(winners) < 3:
        out += [f"> 후보 {len(candidates)}개 중 Minimal이 낫다고 볼 수 있는 질문이 {len(winners)}개뿐이에요. 후보를 더 추가해서 다시 돌려 보세요.", ""]
    for i, (_, _, tid, reason, (m, s)) in enumerate(winners, 1):
        out += [f"### 질문 {i}. {tasks[tid].prompt}", ""]
        out += row_table(m, s)
        out += ["", f"**Minimal이 더 좋다고 본 이유** (측정값에서 뽑은 초안, 직접 확인 후 고쳐 쓰기): {reason}", ""]

    out += ["## 3. 전체 후보 결과", "", "| 질문 | Minimal 전체 토큰 | Standard 전체 토큰 | Minimal 시간 | Standard 시간 | Minimal 정답 | Standard 정답 | Minimal이 나음 |", "|---|---:|---:|---:|---:|---:|---:|:---:|"]
    for wins, _, tid, _, (m, s) in candidates:
        rate = lambda a: f"{a['passed']}/{a['checked']}" if a["checked"] else "—"  # noqa: E731
        out.append(f"| {tid} | {int(m['total']):,} | {int(s['total']):,} | {m['wall_s']}초 | {s['wall_s']}초 | {rate(m)} | {rate(s)} | {'✓' if wins else ''} |")
    others = [e for e in engines if e != primary]
    for e in others:
        out += ["", f"### 참고: {e} 엔진 (LangChain/deepagents로 같은 구성을 재현)", "", "| 질문 | Minimal 전체 토큰 | Standard 전체 토큰 | Minimal 시간 | Standard 시간 |", "|---|---:|---:|---:|---:|"]
        for tid in tasks:
            p = pair(tid, e)
            if p:
                m, s = p
                out.append(f"| {tid} | {int(m['total']):,} | {int(s['total']):,} | {m['wall_s']}초 | {s['wall_s']}초 |")
    out += [
        "",
        "## 4. 정리",
        "",
        "- (직접 작성) 단순한 질문에서도 많은 Skill과 도구가 유리했는지, 필요한 기능만 둔 구성이 더 효율적이었는지.",
        "",
        "---",
        "측정: harness-lab `lab run` + `lab week1`. API key, credential, 세션 로그는 포함하지 않았어요.",
        "",
    ]
    return "\n".join(out)


def write(batch_dir: Path, github_id: str, out: Path | None = None) -> Path:
    path = out or batch_dir / "week1-result.md"
    path.write_text(build(batch_dir, github_id), encoding="utf-8")
    return path
