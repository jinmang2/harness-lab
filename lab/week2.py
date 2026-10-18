"""Week 2 assignment write-up: Custom RALPH vs the official `tool-ralph`, plus the lab loop variants.

    LAB_RUNS_DIR=$TMPDIR/hl-week2 uv run lab run -T tasks/week2.yaml -e dsh -H ralph-official,ralph-custom -n 3 -l week2-dsh
    uv run lab week2 <batch> [<batch> ...] --id <GitHub-ID>

Runs go outside the repository (`LAB_RUNS_DIR`) so a worker cannot find the reference solution or
another run's workspace by walking up from its cwd; `outside` still counts every tool call that
names a path outside the run's workspace (ADR-0015). Rounds come from the loop itself: DSH child
session logs (one per round attempt) and their `structured_output` reports, or the lab trace's
`round` events. The acceptance suite is re-run on each final workspace.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from lab import ROOT

CHECKS = ROOT / "tasks" / "checks"
# Grading picks the suite from the task id, not the workspace: a worker may edit SPEC.md.
SUITES = {"durations": CHECKS / "week2_acceptance.py", "sizes": CHECKS / "week2_sizes_acceptance.py"}
LOOP_TOOLS = ("ralph", "verified_ralph")
# Endings where the worker or judge declared the objective done (reset: no handoff means done).
DONE = ("worker complete", "complete", "self-reported", "stop-no-handoff")
# The lab `round` events a harness's own loop writes; others (a worker calling goal tools) are ignored.
MECHANISM = {"ralph-fresh": "fresh", "ralph-verified": "verified", "ralph-judge": "judge", "ralph-check": "check",
             "ralph-reset": "reset", "goal": "goal"}
_PATH = re.compile(r"(?:/Users|/private|/var|/tmp|/home|/etc|/opt)[^\s\"'\\;|&)<>`]*")

LABELS = {
    ("dsh-web", "ralph-official"): "DSH Web 공식 `tool-ralph` (standard + ralph preset)",
    ("dsh-web", "ralph-custom"): "DSH Web Custom `verified_ralph` (Verified RALPH preset)",
    ("dsh-web", "goal"): "DSH Web goal (standard preset, `/goal`)",
    ("dsh", "ralph-official"): "DSH 공식 `tool-ralph`",
    ("dsh", "ralph-custom"): "DSH Custom `verified_ralph`",
    ("lab", "ralph-fresh"): "lab fresh (공식 재현)",
    ("lab", "ralph-verified"): "lab verified (Custom 재현)",
    ("lab", "goal"): "lab goal (DSH goal 재현)",
    ("lab", "ralph-judge"): "lab judge (같은 대화 + judge)",
    ("lab", "ralph-check"): "lab check (같은 대화 + 검증 명령)",
    ("lab", "ralph-reset"): "lab reset (대화 초기화 + handoff)",
}
ORDER = list(LABELS)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _calls(run_dir: Path) -> list[tuple[str, str, str]]:
    """(source, tool name, raw arguments) for every tool call of the run, children included."""
    logs = sorted(run_dir.glob("dsh-session*.jsonl"))
    if logs:
        return [(p.name, e["data"]["name"], e["data"].get("arguments") or "")
                for p in logs for e in _jsonl(p) if e.get("type") == "tool/call"]
    return [("trace", e["name"], json.dumps(e.get("args"), ensure_ascii=False)) for e in _jsonl(run_dir / "trace.jsonl") if e.get("kind") == "tool"]


def _workspaces(run_dir: Path) -> tuple[str, ...]:
    """The run's workspace as the agent saw it (the header `cwd`, maybe an isolated temp dir) and as archived."""
    header = next(iter(_jsonl(run_dir / "trace.jsonl")), {})
    seen = [str(header.get("cwd") or ""), str(run_dir / "workspace")]
    out = set()
    for path in filter(None, seen):
        out |= {path, os.path.realpath(path), path.removeprefix("/private")}
    return tuple(out)


def _empty_parent(run_dir: Path) -> set[str]:
    """An isolated workspace's temp parent holds nothing else; listing it reaches nothing."""
    header = next(iter(_jsonl(run_dir / "trace.jsonl")), {})
    cwd = str(header.get("cwd") or "")
    if not cwd or cwd.startswith(str(run_dir.parent)):
        return set()
    parent = os.path.dirname(cwd)
    return {_norm(parent), _norm(os.path.realpath(parent))}


def _norm(path: str) -> str:
    return path.removeprefix("/private").rstrip("/")


def outside_access(run_dir: Path) -> list[str]:
    """Paths a tool call named outside the run's workspace (its own `/tmp` scratch files excepted)."""
    workspaces = _workspaces(run_dir)
    skip = _empty_parent(run_dir)
    hits = []
    for _, _, args in _calls(run_dir):
        for raw in _PATH.findall(args.replace("\\n", " ")):
            if raw.startswith(workspaces) or os.path.realpath(raw).startswith(workspaces) or _norm(raw) in skip:
                continue
            if re.match(r"^(/private)?/tmp/[^/]+\.(py|txt|json|md)$", raw):
                continue
            hits.append(raw)
    return hits


# What a worker must not see: grading suites, reference solutions, other runs.
ANSWERS = tuple(str(ROOT / d) for d in ("tasks", "tests", "runs"))


def answer_access(run_dir: Path, paths: list[str]) -> list[str]:
    """The outside paths that reach answers: inside `ANSWERS`, or another run's isolated workspace.

    Other outside paths (the DSH runtime the system prompt names, the unlistable isolation root,
    `/etc` in a code comment) are reported but do not disqualify the run.
    """
    header = next(iter(_jsonl(run_dir / "trace.jsonl")), {})
    cwd = _norm(os.path.realpath(str(header.get("cwd") or "")))
    iso_root = os.path.dirname(os.path.dirname(cwd)) if os.path.basename(os.path.dirname(os.path.dirname(cwd))) == "lab-ws" else ""
    own = os.path.dirname(cwd)
    hits = []
    for raw in paths:
        path = _norm(os.path.realpath(raw))
        if any(path == a or path.startswith(a + "/") for a in ANSWERS):
            hits.append(raw)
        elif iso_root and path.startswith(iso_root + "/") and not (path == own or path.startswith(own + "/")):
            hits.append(raw)
    return hits


def acceptance(workspace: Path, task_id: str = "durations") -> dict[str, Any]:
    suite = SUITES[task_id.split("-")[0]]
    proc = subprocess.run([sys.executable, str(suite), str(workspace)], capture_output=True, text=True, timeout=120)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"passed": 0, "total": 0, "failed": [{"test": "acceptance", "error": proc.stderr[-300:]}]}


def _one_line(text: str, limit: int = 140) -> str:
    flat = " ".join((text or "").split()).replace("|", "\\|")
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def _dsh_goal_rounds(main_log: Path) -> list[dict[str, Any]]:
    """DSH goal: one entry per goal-sourced `<goal_round>` message; the last carries the goal's final phase."""
    out: list[dict[str, Any]] = []
    phase, reason = None, ""
    for e in _jsonl(main_log):
        data = e.get("data") or {}
        if e.get("type") == "user/message" and (data.get("source") or {}).get("kind") == "goal":
            out.append({"round": data["source"].get("round"), "status": "", "summary": "", "decision": "continue", "verify_exit": None})
        elif e.get("type") == "goal/change":
            goal = data.get("goal") or {}
            phase, reason = goal.get("phase"), goal.get("blockedReason") or reason
    if out and phase and phase != "active":
        out[-1]["decision"] = phase
        out[-1]["summary"] = reason
    return out


def _dsh_round_no(child_log: Path) -> int | None:
    """`Round 3 of 5.` from the child's first prompt; retries of one round share the number."""
    for e in _jsonl(child_log):
        if e.get("type") == "agent/inbox/spliced":
            for item in e["data"].get("inserted", []):
                for part in item.get("content", []):
                    m = re.search(r"\bRound (\d+) of \d+", part.get("text", ""))
                    if m:
                        return int(m.group(1))
    return None


def rounds(run_dir: Path, engine: str, harness: str = "") -> list[dict[str, Any]]:
    """One entry per round attempt: worker status and summary, plus the loop's decision when it records one."""
    if engine == "lab":
        out = []
        own = MECHANISM.get(harness)
        for e in _jsonl(run_dir / "trace.jsonl"):
            if e.get("kind") != "round" or (own and e.get("mechanism") != own):
                continue
            report = e.get("report") or {}
            out.append({"round": e.get("round"), "status": e.get("worker_status") or report.get("status") or "",
                        "summary": e.get("summary") or report.get("summary") or (e.get("judge") or {}).get("reason") or e.get("error") or "",
                        "decision": e.get("decision") or "", "verify_exit": e.get("verify_exit")})
        return out
    goal_rounds = _dsh_goal_rounds(run_dir / "dsh-session.jsonl")
    if goal_rounds:
        return goal_rounds
    out = []
    for i, path in enumerate(sorted(run_dir.glob("dsh-session.*.jsonl"), key=lambda p: int(p.name.split(".")[1])), 1):
        report: dict[str, Any] = {}
        for e in _jsonl(path):
            if e.get("type") == "tool/call" and e["data"]["name"] == "structured_output":
                try:
                    report = json.loads(e["data"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    report = {}
        out.append({"round": _dsh_round_no(path) or i, "status": report.get("status", "(보고 없음)"), "summary": report.get("summary", ""),
                    "decision": "", "verify_exit": None})
    return out


def loop_results(run_dir: Path) -> list[str]:
    """Every loop tool result, in order. A failed loop returns to the parent model, which may call the tool again."""
    return [e.get("result_preview") or e.get("error") or "" for e in _jsonl(run_dir / "trace.jsonl")
            if e.get("kind") == "tool" and e.get("name") in LOOP_TOOLS]


def loop_result(run_dir: Path) -> str:
    """The last loop tool's result text (first line is the stop reason)."""
    results = loop_results(run_dir)
    return results[-1] if results else ""


def _verifier_exits(loop: str) -> dict[int, int]:
    """`Verifier: round 1 fail (exit 1), round 2 pass (exit 0).` -> {1: 1, 2: 0} (DSH custom result text)."""
    return {int(n): int(code) for n, code in re.findall(r"round (\d+) (?:pass|fail) \(exit (-?\d+)", loop)}


def stop_reason(run: dict[str, Any]) -> str:
    """A short stop label: the loop's own word, or the error class when the run itself failed."""
    first = run["loop"].splitlines()[0] if run["loop"] else ""
    for word in ("verified", "blocked", "self-reported", "budget-limited", "round-failed"):
        if f"as {word}" in first or f"finished: {word}" in first:
            return word
    if "reported completion" in first:
        return "worker complete"
    if "limit; the worker reported work remaining" in first:
        return "budget-limited"
    if run.get("status") != "ok":
        return "error: " + (re.match(r"\w+", run.get("error") or "") or re.match(r"", "")).group(0)
    stops = [x["decision"] for x in run["rounds"] if x.get("decision")]
    return stops[-1] if stops else "—"


def false_completions(run: dict[str, Any]) -> int:
    """Rounds whose worker said `complete` while the objective was not met.

    With a verifier in the loop each round's exit code tells; otherwise only the last claim can be
    checked, against the acceptance suite on the final workspace.
    """
    claims = [x for x in run["rounds"] if x.get("status") == "complete"]
    if any(x.get("verify_exit") is not None for x in run["rounds"]):
        return sum(1 for x in claims if x.get("verify_exit") not in (0, None))
    full = run["acc"]["total"] and run["acc"]["passed"] == run["acc"]["total"]
    ended_done = stop_reason(run) in DONE  # incl. a judge's "done" and reset's "no handoff"
    return 1 if (claims or ended_done) and not full else 0


def ended_unmet(run: dict[str, Any]) -> int:
    """1 when the loop ended as done (worker, judge or verifier) but the acceptance suite says it is not."""
    full = run["acc"]["total"] and run["acc"]["passed"] == run["acc"]["total"]
    return 1 if stop_reason(run) in (*DONE, "verified") and not full else 0


def backlog_checked(workspace: Path) -> str:
    path = workspace / "BACKLOG.md"
    if not path.is_file():
        return "—"
    items = [line for line in path.read_text(encoding="utf-8").splitlines() if re.match(r"^- \[[ xX]\]", line)]
    return f"{sum(1 for line in items if line[3] in 'xX')}/{len(items)}"


def collect(batch_dirs: list[Path], exclude: list[str] | None = None) -> list[dict[str, Any]]:
    """Every run of the batches except `exclude` patterns (fnmatch on `<batch>/<run_id>`)."""
    runs = []
    for batch in batch_dirs:
        for row in _jsonl(batch / "summary.jsonl"):
            if any(fnmatch.fnmatch(f"{batch.name}/{row['run_id']}", pat) for pat in exclude or []):
                continue
            run_dir = batch / row["run_id"]
            workspace = run_dir / "workspace"
            acc = acceptance(workspace, row["task"])
            loop = loop_result(run_dir)
            rs = rounds(run_dir, row["engine"], row["harness"])
            for n, code in _verifier_exits(loop).items():
                for x in rs:
                    if x["round"] == n and x["verify_exit"] is None:
                        x["verify_exit"] = code
            runs.append({
                **row, "run_dir": run_dir, "acc": acc, "rounds": rs,
                "loop": loop, "loop_calls": len(loop_results(run_dir)), "outside": (outside := outside_access(run_dir)), "leak": answer_access(run_dir, outside), "backlog": backlog_checked(workspace),
                "progress": (workspace / ".ralph" / "progress.md").is_file(),
            })
    return runs


def round_count(run: dict[str, Any]) -> int:
    """Rounds started over every loop call: a loop's highest round number (a stop event repeats the
    last one; retries share one), summed when the parent called the loop again (numbering restarts)."""
    total, best, prev = 0, 0, 0
    for x in run["rounds"]:
        if x.get("round") is None:
            continue
        n = int(x["round"])
        if n < prev:
            total, best = total + best, 0
        best, prev = max(best, n), n
    return total + best


def _rounds_label(run: dict[str, Any]) -> str:
    calls = run.get("loop_calls", 0)
    return f"{round_count(run)}" + (f" (루프 {calls}번)" if calls > 1 else "")


def _median(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0


def build(batch_dirs: list[Path], github_id: str, exclude: list[str] | None = None) -> str:
    runs = collect(batch_dirs, exclude)
    if not runs:
        raise SystemExit("no runs in the given batches")
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for r in runs:
        groups[(r["task"], r["engine"], r["harness"])].append(r)
    model = next((r["model"] for r in runs if r.get("model")), "?")
    tasks = sorted({r["task"] for r in runs})

    out = [
        f"# Week 2 — Build Your Own RALPH ({github_id})",
        "",
        f"- 모델: `{model}` (모든 하네스 같은 모델, 같은 설정)",
        "- 같은 작업 지시문, 같은 초기 workspace(태스크 fixture 복사본), 최대 Round 5",
        "- 채점: workspace 밖에 있는 수락 테스트 13개(SPEC 규칙마다 1개)를 최종 workspace에 다시 돌린 결과",
        "- 토큰: 게이트웨이가 녹화한 모든 모델 호출의 합(Round child 포함), 입력은 캐시 포함",
        "- workspace 밖 접근: 도구 호출 인자에 workspace 밖 경로가 나온 횟수. 그중 채점 자료(수락 테스트, 정답 코드, 다른 실행)에 닿은 실행은 오염으로 봐요",
        *([f"- 제외한 실행: {', '.join(f'`{x}`' for x in exclude)}"] if exclude else []),
        "",
        "## 실행 요약",
        "",
        "숫자는 오염되지 않은 실행만의 중앙값이에요. 채점 자료에 닿은 실행은 `오염`에 세고 중앙값에서 뺐어요.",
        "",
        "| 태스크 | 하네스 | 실행(오염) | 수락 테스트 | Round | 종료 | 거짓 완료 보고 (그대로 끝남) | 전체 토큰 | 도구 호출 | 시간 |",
        "|---|---|---:|---|---:|---|---:|---:|---:|---:|",
    ]
    for task in tasks:
        for engine, harness in ORDER:
            rs = groups.get((task, engine, harness))
            if not rs:
                continue
            clean = [r for r in rs if not r["leak"]] or rs
            acc = ", ".join(f"{r['acc']['passed']}/{r['acc']['total']}" + ("*" if r["leak"] else "†" if r["outside"] else "") for r in rs)
            stops = ", ".join(stop_reason(r) for r in clean)
            out.append(
                f"| {task} | {LABELS[(engine, harness)]} | {len(rs)} ({len([r for r in rs if r['leak']])}) | {acc} | "
                f"{', '.join(_rounds_label(r) for r in clean)} | {stops} | {sum(false_completions(r) for r in clean)} ({sum(ended_unmet(r) for r in clean)}) | "
                f"{int(_median([r.get('total_tokens') or 0 for r in clean])):,} | {_median([r.get('tool_calls') or 0 for r in clean]):g} | "
                f"{_median([(r.get('turn_ms') or r.get('wall_ms') or 0) / 1000 for r in clean]):.0f}초 |"
            )
    out += ["", "`*` = 채점 자료에 닿은 실행(오염, 중앙값에서 제외). `†` = workspace 밖을 건드렸지만 채점 자료와 무관한 실행(DSH 런타임 소스, 목록을 볼 수 없는 격리 폴더 등). Round와 종료는 오염되지 않은 실행마다 하나씩 적었어요.",
            "`(루프 N번)` = Round가 실패해 루프가 끝난 뒤 모델이 루프 도구를 다시 부른 경우. Round는 모든 호출의 합이고, 종료는 마지막 호출 기준이에요.",
            "거짓 완료 보고 = worker나 judge가 완료라고 했지만 그 시점 수락 테스트가 13/13이 아니었던 횟수. 괄호는 그 보고로 루프가 그대로 끝나 버린 횟수예요."]

    out += ["", "## Round별 기록", ""]
    for task in tasks:
        for engine, harness in ORDER:
            for r in groups.get((task, engine, harness), []):
                out += [f"### {task} · {LABELS[(engine, harness)]} · #{r['repeat']}" + (" (오염: 결과에서 제외)" if r["leak"] else ""), ""]
                out.append(f"- 종료: {stop_reason(r)} · Round {_rounds_label(r)} · 거짓 완료 보고 {false_completions(r)}")
                if r["backlog"] != "—":
                    out.append(f"- BACKLOG 체크: {r['backlog']}")
                out.append(f"- 수락 테스트: {r['acc']['passed']}/{r['acc']['total']}" +
                           (f" (실패: {', '.join(f['test'] for f in r['acc'].get('failed', []))})" if r["acc"].get("failed") else ""))
                if r["leak"]:
                    out.append(f"- 채점 자료 접근 {len(r['leak'])}회: {', '.join(sorted(set(_one_line(p, 80) for p in r['leak']))[:4])}")
                if r["outside"]:
                    out.append(f"- workspace 밖 접근 {len(r['outside'])}회: {', '.join(sorted(set(_one_line(p, 80) for p in r['outside']))[:4])}")
                if r["rounds"]:
                    out += ["", "| Round | worker 보고 | 루프 판단 | 검증 exit | 요약 |", "|---:|---|---|---:|---|"]
                    for x in r["rounds"]:
                        vx = "" if x["verify_exit"] is None else str(x["verify_exit"])
                        out.append(f"| {x['round']} | {x['status']} | {x['decision']} | {vx} | {_one_line(x['summary'])} |")
                if r["loop"]:
                    out += ["", "```", r["loop"][:900], "```"]
                out.append("")
    out += ["---", "측정: harness-lab `lab run` + `lab week2`. API key, credential, 세션 로그 원문은 포함하지 않았어요.", ""]
    return "\n".join(out)


def write(batch_dirs: list[Path], github_id: str, out: Path | None = None, exclude: list[str] | None = None) -> Path:
    path = out or batch_dirs[0] / "week2-result.md"
    path.write_text(build(batch_dirs, github_id, exclude), encoding="utf-8")
    return path
