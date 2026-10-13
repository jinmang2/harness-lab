"""Local UI on 127.0.0.1: index.html plus a JSON API over runs/.

`lab view` is read-only. `lab ui` (alias `lab play`) also enables the interactive
parts: chat sessions, batch runs, settings and the gateway. Those are POST endpoints
guarded by a loopback Host check and a custom `X-Lab` header.
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from lab import RUNS_DIR, TASKS_DIR
from lab.gateway import body_path
from lab.viewer.jobs import JobRegistry, run_argv
from lab.viewer.play import PlayRegistry

STATIC = Path(__file__).with_name("static")  # built by `cd ui && npm run build` (React, DSH Web design)
_TYPES = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml",
          ".png": "image/png", ".woff2": "font/woff2", ".json": "application/json", ".ico": "image/x-icon"}
_NAME = re.compile(r"^(?!\.{1,2}$)[\w.\-]+$")


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _batches() -> list[dict[str, Any]]:
    out = []
    if RUNS_DIR.is_dir():
        for d in sorted(RUNS_DIR.iterdir(), reverse=True):
            if d.is_dir() and (d / "summary.jsonl").is_file():
                runs = _jsonl(d / "summary.jsonl")
                out.append({
                    "name": d.name,
                    "runs": len(runs),
                    "tasks": sorted({r["task"] for r in runs}),
                    "harnesses": sorted({f"{r['engine']}/{r['harness']}" for r in runs}),
                })
    return out


def _run(batch: str, run: str) -> dict[str, Any]:
    run_dir = RUNS_DIR / batch / run
    workspace = run_dir / "workspace"
    files = []
    if workspace.is_dir():
        for p in sorted(workspace.rglob("*")):
            if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts:
                files.append({"path": str(p.relative_to(workspace)), "bytes": p.stat().st_size})
    return {
        "events": _jsonl(run_dir / "trace.jsonl"),
        "wire": _jsonl(run_dir / "wire.jsonl"),
        "files": files[:200],
        "stderr": (run_dir / "stderr.txt").read_text(encoding="utf-8")[-5000:] if (run_dir / "stderr.txt").is_file() else "",
    }


def _export(batch: str, run: str) -> bytes | None:
    run_dir = RUNS_DIR / batch / run
    if not run_dir.is_dir():
        return None
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(run_dir.rglob("*")):
            if path.is_file() and not path.is_symlink() and ".git" not in path.parts and path.stat().st_size < 20_000_000:
                zf.write(path, f"{run}/{path.relative_to(run_dir)}")
    return buf.getvalue()


def _tasks() -> list[dict[str, Any]]:
    from lab.runner import load_tasks

    out = []
    for path in sorted(TASKS_DIR.glob("*.yaml")):
        out.append({"file": path.stem, "tasks": [{"id": t.id, "prompt": t.prompt[:300]} for t in load_tasks(path)]})
    return out


class _Handler(BaseHTTPRequestHandler):
    play: PlayRegistry | None = None  # set when started with `lab ui`
    jobs: JobRegistry | None = None

    def log_message(self, fmt: str, *args: Any) -> None:
        pass

    def _host_ok(self) -> bool:
        # Loopback only: refuse other Host names so a web page cannot reach this via DNS rebinding.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            self._json({"error": "forbidden host"}, 403)
            return False
        return True

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: Any, status: int = 200) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if not self._host_ok():
            return
        parts =[p for p in self.path.split("?")[0].split("/") if p]
        if not parts:
            index = STATIC / "index.html"
            if not index.is_file():
                self._send(500, b"UI not built: cd ui && npm install && npm run build", "text/plain; charset=utf-8")
                return
            self._send(200, index.read_bytes(), "text/html; charset=utf-8")
            return
        if parts[0] == "assets" and len(parts) == 2 and _NAME.match(parts[1]):
            asset = STATIC / "assets" / parts[1]
            if asset.is_file():
                self._send(200, asset.read_bytes(), _TYPES.get(asset.suffix, "application/octet-stream"))
            else:
                self._json({"error": "not found"}, 404)
            return
        if parts[0] != "api" or not all(_NAME.match(p) for p in parts):
            self._json({"error": "not found"}, 404)
            return
        match parts[1:]:
            case ["batches"]:
                self._json(_batches())
            case ["batch", batch]:
                self._json(_jsonl(RUNS_DIR / batch / "summary.jsonl"))
            case ["run", batch, run]:
                self._json(_run(batch, run))
            case ["file", batch, run, *rel] if rel:
                workspace = (RUNS_DIR / batch / run / "workspace").resolve()
                path = workspace.joinpath(*rel).resolve()  # also follows agent-made symlinks
                if path.is_relative_to(workspace) and path.is_file() and path.stat().st_size < 500_000:
                    self._send(200, path.read_bytes(), "text/plain; charset=utf-8")
                else:
                    self._json({"error": "not found"}, 404)
            case ["config"]:
                from lab import dsh

                from lab.model import EFFORTS, MODELS, model_name

                self._json({"play": self.play is not None, "dsh_installed": dsh.bin_path().exists(), "dsh_version": dsh.DSH_VERSION,
                            "models": MODELS, "efforts": EFFORTS, "default_model": model_name(),
                            "default_effort": "off" if os.environ.get("LAB_THINKING") == "disabled" else os.environ.get("LAB_REASONING_EFFORT", "high")})
            case ["harnesses"]:
                from lab import dsh
                from lab.harnesses import REGISTRY

                self._json([{"engine": "lab", "name": h.name, "description": h.description} for h in REGISTRY.values()]
                           + [{"engine": "dsh", "name": n, "description": "headless + " + " + ".join(f)} for n, f in dsh.HARNESSES.items()])
            case ["anatomy", "lab", name]:
                from lab.anatomy import anatomy
                from lab.harnesses import REGISTRY

                if name not in REGISTRY:
                    self._json({"error": "unknown harness"}, 404)
                    return
                try:
                    self._json(anatomy(name))
                except Exception as exc:
                    self._json({"error": repr(exc)}, 500)
            case ["anatomy", "dsh", name]:
                from lab.anatomy import dsh_anatomy

                try:
                    self._json(dsh_anatomy(name))
                except ValueError as exc:
                    self._json({"error": str(exc)}, 404)
            case ["tasks"]:
                self._json(_tasks())
            case ["export", batch, run]:
                data = _export(batch, run)
                if data is None:
                    self._json({"error": "not found"}, 404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{run}.zip"')
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            case ["settings"] if self.play:
                from lab import settings

                self._json(settings.describe())
            case ["jobs"] if self.jobs:
                self._json([j.describe(tail=0) for j in reversed(list(self.jobs.jobs.values()))])
            case ["jobs", jid] if self.jobs:
                try:
                    self._json(self.jobs.get(jid).describe())
                except KeyError as exc:
                    self._json({"error": str(exc)}, 404)
            case ["play", "sessions"] if self.play:
                self._json(sorted((s.describe() for s in list(self.play.sessions.values())), key=lambda d: -d.get("updated", 0)))
            case ["play", sid, "files"] if self.play:
                from lab.viewer import workspaces

                try:
                    self._json(workspaces.files(self.play.get(sid).workdir))
                except KeyError as exc:
                    self._json({"error": str(exc)}, 404)
            case ["play", sid, "file"] if self.play:
                from lab.viewer import workspaces

                rel = (parse_qs(urlsplit(self.path).query).get("path") or [""])[0]
                try:
                    data = workspaces.read(self.play.get(sid).workdir, rel) if rel else None
                except KeyError:
                    data = None
                if data is None:
                    self._json({"error": "not found"}, 404)
                else:
                    self._send(200, data, "text/plain; charset=utf-8")
            case ["workspaces"] if self.play:
                from lab.viewer import workspaces

                self._json(workspaces.list_all())
            case ["play", sid, "events"] if self.play:
                query = parse_qs(urlsplit(self.path).query)
                try:
                    after = max(int((query.get("after") or ["0"])[0]), 0)
                except ValueError:
                    self._json({"error": "after must be an integer"}, 400)
                    return
                try:
                    session = self.play.get(sid)
                except KeyError as exc:
                    self._json({"error": str(exc)}, 404)
                    return
                self._json({**session.describe(), "items": session.events_after(after)})
            case ["body", call_id]:
                path = body_path(call_id)
                if path.is_file():
                    self._send(200, path.read_bytes(), "application/json; charset=utf-8")
                else:
                    self._json({"error": "body not saved"}, 404)
            case _:
                self._json({"error": "not found"}, 404)


    def do_POST(self) -> None:
        """Interactive actions. Requires `lab ui`, a loopback Host and the X-Lab header.

        Browsers cannot add a custom header to a cross-site request without a CORS
        preflight, which this server never approves, so other web pages cannot drive it.
        """
        if not self._host_ok():
            return
        if self.play is None:
            self._json({"error": "read-only viewer; start `lab ui` to chat, run and change settings"}, 403)
            return
        if self.headers.get("X-Lab") != "1":
            self._json({"error": "missing X-Lab header"}, 403)
            return
        parts = [p for p in urlsplit(self.path).path.split("/") if p]
        if not all(_NAME.match(p) for p in parts):
            self._json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= 1_000_000:
                raise ValueError
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:  # bad length or invalid JSON (JSONDecodeError is a ValueError)
            self._json({"error": "invalid request body"}, 400)
            return
        if not isinstance(body, dict):
            self._json({"error": "body must be a JSON object"}, 400)
            return
        try:
            match parts:
                case ["api", "play", "start"]:
                    from lab.viewer import workspaces

                    session = self.play.start(str(body.get("harness") or "minimal"), str(body.get("engine") or "lab"),
                                              body.get("model") or None, body.get("effort") or None,
                                              str(body.get("approval") or "auto"), workspaces.resolve(body.get("workspace")),
                                              plan=bool(body.get("plan")))
                    self._json(session.describe())
                case ["api", "workspaces", "add"]:
                    from lab.viewer import workspaces

                    self._json(workspaces.add(str(body.get("path") or "")))
                case ["api", "workspaces", "remove"]:
                    from lab.viewer import workspaces

                    workspaces.remove(str(body.get("path") or ""))
                    self._json({"ok": True})
                case ["api", "play", sid, "cancel"]:
                    self.play.get(sid).cancel()
                    self._json({"ok": True})
                case ["api", "play", sid, "rename"]:
                    self.play.get(sid).rename(str(body.get("title") or ""))
                    self._json({"ok": True})
                case ["api", "settings"]:
                    from lab import settings

                    self._json(settings.update(body))
                case ["api", "settings", "models"]:
                    from lab import settings

                    self._json(settings.discover_models())
                case ["api", "gateway", "start"]:
                    from lab.viewer import gateway_control

                    mode = body.get("mode")
                    if mode not in ("mock", "proxy"):
                        raise ValueError("mode must be mock or proxy")
                    self._json(gateway_control.start(mode))
                case ["api", "gateway", "stop"]:
                    from lab.viewer import gateway_control

                    self._json(gateway_control.stop())
                case ["api", "jobs", "run"]:
                    self._json(self.jobs.start("run", run_argv(body)).describe())
                case ["api", "jobs", "judge"]:
                    batch = str(body.get("batch") or "")
                    if not _NAME.match(batch) or not (RUNS_DIR / batch / "summary.jsonl").is_file():
                        raise ValueError("unknown batch")
                    self._json(self.jobs.start("judge", ["judge", str(RUNS_DIR / batch)] + (["--force"] if body.get("force") else []), batch).describe())
                case ["api", "jobs", jid, "stop"]:
                    self.jobs.get(jid).stop()
                    self._json({"ok": True})
                case ["api", "play", sid, "send"]:
                    self.play.get(sid).send(str(body.get("text") or "").strip() or "hi")
                    self._json({"ok": True})
                case ["api", "play", sid, "resume"]:
                    self.play.get(sid).resume(str(body.get("decision") or "approve"), body.get("message"))
                    self._json({"ok": True})
                case ["api", "play", sid, "answer"]:
                    self.play.get(sid).answer(body)
                    self._json({"ok": True})
                case ["api", "play", sid, "plan"]:  # `/plan [message]` and `/plan off`
                    session = self.play.get(sid)
                    text = session.set_plan(bool(body.get("active")))
                    message = str(body.get("message") or "").strip()
                    if message and body.get("active"):
                        session.send(message)
                    self._json({"ok": True, "text": text})
                case _:
                    self._json({"error": "not found"}, 404)
        except (KeyError, ValueError, TypeError) as exc:
            self._json({"error": str(exc)}, 409)
        except SystemExit as exc:  # unknown harness / missing key from the model factory
            self._json({"error": str(exc)}, 400)


def serve(port: int = 8765, play: bool = False) -> ThreadingHTTPServer:
    handler = type("Handler", (_Handler,), {"play": PlayRegistry() if play else None, "jobs": JobRegistry() if play else None})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)
