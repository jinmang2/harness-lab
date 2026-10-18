"""`lab` command line.

    lab list                                   harnesses and tasks
    lab run -H minimal,standard [-e lab,dsh]   run a batch
    lab gateway --mode mock|proxy              local model gateway (127.0.0.1:8790)
    lab ui                                     local UI (127.0.0.1:8765): chat, runs, harness anatomy, settings
    lab view                                   the same UI, read-only (runs and anatomy only)
    lab judge runs/<batch>                     Output Quality via LLM-judge (task rubrics)
    lab week1 runs/<batch> --id <GitHub-ID>    week 1 assignment result.md from a week1-assignment batch
    lab week2 <batch>... --id <GitHub-ID>      week 2 RALPH comparison from tasks/week2.yaml batches
    lab report runs/<batch>                    rebuild report.md
    lab dsh-install [--version V]              install pinned DeepSeek Harness (npm, no build)
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
from pathlib import Path

from lab import RUNS_DIR, TASKS_DIR, load_dotenv


def _cmd_list(args: argparse.Namespace) -> None:
    from lab import dsh
    from lab.harnesses import REGISTRY
    from lab.runner import load_tasks

    print("lab harnesses:")
    for h in REGISTRY.values():
        print(f"  {h.name:<14} {h.description}")
    print("\ndsh harnesses (headless + patches):")
    for name, patches in dsh.HARNESSES.items():
        print(f"  {name:<14} {' + '.join(patches)}  (dsh {dsh.version_of(name)})")
    from lab import dsh_web

    print("\ndsh-web harnesses (Web host, preset per session):")
    for name, (patches, preset) in dsh_web.HARNESSES.items():
        print(f"  {name:<14} preset {preset} + {' + '.join(patches)}  (dsh {dsh_web.VERSION})")
    print("\ntasks:")
    for path in sorted(TASKS_DIR.glob("*.yaml")):
        for t in load_tasks(path):
            print(f"  {path.stem}:{t.id}")


def _cmd_run(args: argparse.Namespace) -> None:
    from lab.runner import load_tasks, run_batch

    harnesses = [h.strip() for h in args.harness.split(",") if h.strip()]
    engines = [e.strip() for e in args.engine.split(",") if e.strip()]
    combos = [(e, h) for e in engines for h in harnesses]
    from lab import dsh, dsh_web

    known = {"dsh": dsh.HARNESSES, "dsh-web": dsh_web.HARNESSES}
    for engine, table in known.items():
        if engine in engines:
            unsupported = [h for h in harnesses if h not in table]
            combos = [(e, h) for e, h in combos if not (e == engine and h in unsupported)]
            if unsupported:
                print(f"note: {engine} engine has no {', '.join(unsupported)}; skipping those there")
    tasks = load_tasks(Path(args.tasks), args.task or None)
    batch_dir = run_batch(
        tasks, combos, repeat=args.repeat, label=args.label, judge=args.judge, tasks_file=Path(args.tasks).resolve()
    )
    print(f"\nreport: {batch_dir / 'report.md'}\nview:   uv run lab view  ->  http://127.0.0.1:8765/#{batch_dir.name}")


def _cmd_gateway(args: argparse.Namespace) -> None:
    from lab.gateway import CALLS_FILE, serve

    server = serve(args.mode, args.port, args.upstream, save_bodies=not args.no_bodies)
    print(f"gateway ({args.mode}) on http://127.0.0.1:{args.port}  ->  set DEEPSEEK_BASE_URL=http://127.0.0.1:{args.port}")
    print(f"recording calls to {CALLS_FILE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def _cmd_judge(args: argparse.Namespace) -> None:
    from lab.evaluate import judge_batch
    from lab.runner import batch_tasks

    batch_dir = Path(args.batch)
    n = judge_batch(batch_dir, batch_tasks(batch_dir), force=args.force)
    print(f"judged {n} run(s); report: {batch_dir / 'report.md'}")


def _cmd_view(args: argparse.Namespace) -> None:
    from lab.viewer.server import serve

    play = getattr(args, "play", False)
    server = serve(args.port, play=play)
    mode = "lab ui (runs agents with local shell access)" if play else "read-only viewer (use `lab ui` to chat and run)"
    print(f"{mode} on http://127.0.0.1:{args.port}  (reads {RUNS_DIR})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


def _cmd_week1(args: argparse.Namespace) -> None:
    from lab.week1 import write

    path = write(Path(args.batch), args.id, Path(args.out) if args.out else None)
    print(f"week1 result: {path}  (edit the drafted reasons, then copy to workspace/week1/{args.id}/result.md)")


def _cmd_dsh_web_setup(args: argparse.Namespace) -> None:
    from lab import dsh_web

    dsh_web.setup()


def _cmd_week2(args: argparse.Namespace) -> None:
    from lab.week2 import write

    path = write([Path(b) for b in args.batch], args.id, Path(args.out) if args.out else None, args.exclude)
    print(f"week2 result: {path}  (add the design notes, then copy to workspace/week2/{args.id}/)")


def _cmd_report(args: argparse.Namespace) -> None:
    from lab.report import write_report

    print(write_report(Path(args.batch)))


def _cmd_dsh_install(args: argparse.Namespace) -> None:
    from lab import dsh

    dsh.install(args.version)


def main(argv: list[str] | None = None) -> None:
    # `lab ui` stops jobs with SIGTERM; turn it into SystemExit so cleanup (DSH process group) runs.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    load_dotenv()
    parser = argparse.ArgumentParser(prog="lab", description="Same model, different harness.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(func=_cmd_list)

    run = sub.add_parser("run", help="run tasks x harnesses x engines")
    run.add_argument("-H", "--harness", default="minimal,standard", help="comma-separated harness names")
    run.add_argument("-e", "--engine", default="lab", help="lab, dsh (headless), dsh-web (Web host), comma-separated")
    run.add_argument("-T", "--tasks", default=str(TASKS_DIR / "week1.yaml"), help="task file")
    run.add_argument("-t", "--task", action="append", help="only this task id (repeatable)")
    run.add_argument("-n", "--repeat", type=int, default=1)
    run.add_argument("-l", "--label", help="suffix for the batch directory name")
    run.add_argument("--judge", action="store_true", help="run `lab judge` on the batch afterwards (extra model calls)")
    run.set_defaults(func=_cmd_run)

    gw = sub.add_parser("gateway", help="local model gateway for both engines")
    gw.add_argument("--mode", choices=["mock", "proxy"], default="mock")
    gw.add_argument("--port", type=int, default=8790)
    gw.add_argument("--upstream", default=os.environ.get("LAB_UPSTREAM", "https://api.deepseek.com"))
    gw.add_argument("--no-bodies", action="store_true", help="do not save full request bodies")
    gw.set_defaults(func=_cmd_gateway)

    for name, aliases, help_text, interactive in (
        ("ui", ["play"], "local UI: chat with harnesses, run batches, inspect harnesses, settings and API keys", True),
        ("view", [], "the same UI, read-only", False),
    ):
        p = sub.add_parser(name, aliases=aliases, help=help_text)
        p.add_argument("--port", type=int, default=8765)
        p.set_defaults(func=_cmd_view, play=interactive)

    jd = sub.add_parser("judge", help="LLM-judge Output Quality for a batch (uses each task's rubric)")
    jd.add_argument("batch")
    jd.add_argument("--force", action="store_true", help="re-judge runs that already have judge.json")
    jd.set_defaults(func=_cmd_judge)

    wk = sub.add_parser("week1", help="write the week 1 assignment result.md from a batch of tasks/week1-assignment.yaml")
    wk.add_argument("batch")
    wk.add_argument("--id", required=True, help="your GitHub ID (title of the write-up)")
    wk.add_argument("--out", help="output path (default: runs/<batch>/week1-result.md)")
    wk.set_defaults(func=_cmd_week1)

    dws = sub.add_parser("dsh-web-setup", help="create the isolated DSH Web profile for the dsh-web engine and link dsh/bundles")
    dws.set_defaults(func=_cmd_dsh_web_setup)

    w2 = sub.add_parser("week2", help="write the week 2 RALPH comparison from one or more batches of tasks/week2.yaml")
    w2.add_argument("batch", nargs="+")
    w2.add_argument("--id", required=True, help="your GitHub ID (title of the write-up)")
    w2.add_argument("--out", help="output path (default: <first batch>/week2-result.md)")
    w2.add_argument("--exclude", action="append", default=[], help="skip runs matching <batch>/<run_id> (fnmatch, repeatable)")
    w2.set_defaults(func=_cmd_week2)

    rep = sub.add_parser("report", help="rebuild report.md for a batch")
    rep.add_argument("batch")
    rep.set_defaults(func=_cmd_report)

    di = sub.add_parser("dsh-install", help="install pinned DeepSeek Harness from npm")
    di.add_argument("--version", help="DSH version (default: the study pin; week2 harnesses use 0.2.0-rc.2)")
    di.set_defaults(func=_cmd_dsh_install)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
