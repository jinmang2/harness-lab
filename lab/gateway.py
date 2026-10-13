"""Local OpenAI-compatible gateway on 127.0.0.1 for both engines.

Point `DEEPSEEK_BASE_URL` at it and both the lab engine and DeepSeek Harness send
their model requests here. Every call is appended to `runs/gateway/calls.jsonl`
(and the full request body to `runs/gateway/bodies/<id>.json`), so the two engines
are measured by the same, provider-reported numbers and you can read exactly what
each harness put in front of the model.

Modes:
- `proxy`: forward to the real API (`LAB_UPSTREAM`, default https://api.deepseek.com),
  streaming bytes through unchanged.
- `mock` : answer locally with no key and no cost. If tools are offered and the last
  message is from the user, it calls one tool (prefers bash/shell/execute with
  `echo MOCK_OK`); otherwise it replies `MOCK_DONE`. For wiring tests, not for results.

The Authorization header is never logged.
"""

from __future__ import annotations

import http.client
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from lab import RUNS_DIR

GATEWAY_DIR = RUNS_DIR / "gateway"
CALLS_FILE = GATEWAY_DIR / "calls.jsonl"
_write_lock = threading.Lock()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _record(entry: dict[str, Any], body: dict[str, Any], save_body: bool) -> None:
    GATEWAY_DIR.mkdir(parents=True, exist_ok=True)
    with _write_lock:
        with CALLS_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if save_body:
            bodies = GATEWAY_DIR / "bodies"
            bodies.mkdir(exist_ok=True)
            (bodies / f"{entry['id']}.json").write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")


def _describe(body: dict[str, Any]) -> dict[str, Any]:
    messages = body.get("messages") or []
    tools = body.get("tools") or []
    system = [m for m in messages if m.get("role") == "system"]
    return {
        "model": body.get("model"),
        "stream": bool(body.get("stream")),
        "thinking": (body.get("thinking") or {}).get("type"),
        "messages": len(messages),
        "system_chars": sum(len(json.dumps(m.get("content"), ensure_ascii=False)) for m in system),
        "tools": [t.get("function", {}).get("name") for t in tools],
        "tool_schema_chars": len(json.dumps(tools, ensure_ascii=False)) if tools else 0,
        "request_bytes": len(json.dumps(body, ensure_ascii=False).encode()),
    }


def usage_to_tokens(usage: dict[str, Any] | None) -> dict[str, int]:
    """Provider usage -> disjoint token fields (see lab.trace)."""
    usage = usage or {}
    prompt = int(usage.get("prompt_tokens") or 0)
    cached = int(usage.get("prompt_cache_hit_tokens") or (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0)
    return {
        "input_uncached": max(prompt - cached, 0),
        "cache_read": cached,
        "cache_write": 0,
        "output": int(usage.get("completion_tokens") or 0),
        "reasoning": int((usage.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0),
    }


# ── mock model ───────────────────────────────────────────────────────────────

_PREFERRED_TOOLS = ("bash", "shell", "execute")


def _mock_args(schema: dict[str, Any]) -> dict[str, Any]:
    params = schema.get("parameters") or {}
    props = params.get("properties") or {}
    args: dict[str, Any] = {"command": "echo MOCK_OK"} if "command" in props else {}
    for key in params.get("required") or []:
        kind = (props.get(key) or {}).get("type")
        if key == "command":
            args[key] = "echo MOCK_OK"
        elif kind == "integer" or kind == "number":
            args[key] = 1
        elif kind == "boolean":
            args[key] = False
        elif kind == "array":
            args[key] = []
        elif kind == "object":
            args[key] = {}
        else:
            args[key] = "mock"
    return args


# `[mock:ask]` / `[mock:ask2]` / `[mock:plan]` in the user's message script calls, to exercise the
# question and plan-review UI without a real model.
_SCRIPTS = {
    "[mock:ask]": ("ask_user_question", {"questions": [{
        "id": "color", "header": "Pick one", "question": "Which color do you prefer?", "multi_select": False,
        "options": [{"label": "Blue (Recommended)", "description": "Calm and readable."}, {"label": "Green", "description": "Restful."}]}]}),
    "[mock:plan]": ("exit_plan_mode", {"plan": "# Add a --greeting flag\n\n- **Find the parser** in `cli.py`.\n- **Add** `--greeting` with default `Hello`."}),
}


def _scripted_calls(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """`[mock:ask2]` asks the same question twice in one step (two identical parallel calls)."""
    text = str(messages[-1].get("content") or "")
    names = {t.get("name") for t in tools}
    if "[mock:ask2]" in text and "ask_user_question" in names:
        return [{"name": "ask_user_question", "arguments": json.dumps(_SCRIPTS["[mock:ask]"][1])}] * 2
    for marker, (name, args) in _SCRIPTS.items():
        if marker in text and name in names:
            return [{"name": name, "arguments": json.dumps(args)}]
    return None


def mock_reply(body: dict[str, Any]) -> dict[str, Any]:
    messages = body.get("messages") or []
    tools = [t.get("function", {}) for t in body.get("tools") or []]
    last_role = messages[-1].get("role") if messages else "user"
    prompt_tokens = len(json.dumps(messages, ensure_ascii=False)) // 4 + len(json.dumps(tools)) // 4
    message: dict[str, Any] = {"role": "assistant", "content": ""}
    if (body.get("thinking") or {}).get("type") == "enabled":
        message["reasoning_content"] = "mock reasoning"
    system_text = " ".join(str(m.get("content")) for m in messages if m.get("role") == "system")
    if "harness-lab-judge" in system_text:
        message["content"] = json.dumps({"scores": {"mock": 3}, "overall": 3, "reason": "mock judge"})
        finish = "stop"
    elif tools and last_role == "user" and (scripted := _scripted_calls(messages, tools)) is not None:
        message["tool_calls"] = [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function", "function": f} for f in scripted]
        finish = "tool_calls"
    elif tools and last_role == "user":
        chosen = next((t for name in _PREFERRED_TOOLS for t in tools if t.get("name") == name), tools[0])
        message["tool_calls"] = [
            {
                "id": f"call_{uuid.uuid4().hex[:12]}",
                "type": "function",
                "function": {"name": chosen["name"], "arguments": json.dumps(_mock_args(chosen))},
            }
        ]
        finish = "tool_calls"
    else:
        message["content"] = "MOCK_DONE"
        finish = "stop"
    usage = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": 12,
        "total_tokens": prompt_tokens + 12,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": prompt_tokens,
        "prompt_tokens_details": {"cached_tokens": 0},
        "completion_tokens_details": {"reasoning_tokens": 2 if "reasoning_content" in message else 0},
    }
    return {"message": message, "finish": finish, "usage": usage}


def _mock_chunks(reply: dict[str, Any], model: str) -> list[dict[str, Any]]:
    base = {"id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion.chunk", "created": int(time.time()), "model": model}
    message = reply["message"]
    deltas: list[dict[str, Any]] = [{"role": "assistant", "content": ""}]
    if message.get("reasoning_content"):
        deltas.append({"reasoning_content": message["reasoning_content"]})
    if message.get("tool_calls"):
        deltas.append({"tool_calls": [{"index": i, **c} for i, c in enumerate(message["tool_calls"])]})
    if message.get("content"):
        deltas.append({"content": message["content"]})
    chunks = [{**base, "choices": [{"index": 0, "delta": d, "finish_reason": None}]} for d in deltas]
    chunks.append({**base, "choices": [{"index": 0, "delta": {}, "finish_reason": reply["finish"]}]})
    chunks.append({**base, "choices": [], "usage": reply["usage"]})
    return chunks


# ── HTTP handler ─────────────────────────────────────────────────────────────


class _Handler(BaseHTTPRequestHandler):
    server_version = "harness-lab-gateway/0.1"
    mode = "mock"
    upstream = "https://api.deepseek.com"
    save_bodies = True

    def log_message(self, fmt: str, *args: Any) -> None:  # keep the terminal quiet
        pass

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"object": "list", "data": [{"id": "mock", "object": "model"}]})
        else:
            self._json(200, {"ok": True, "mode": self.mode})

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return
        entry: dict[str, Any] = {
            "id": uuid.uuid4().hex[:16],
            "mode": self.mode,
            "path": self.path,
            "t_start": _now_ms(),
            **_describe(body),
        }
        try:
            if not self.path.rstrip("/").endswith("/chat/completions"):
                self._json(404, {"error": f"unsupported path {self.path}"})
                entry["status"] = 404
            elif self.mode == "mock":
                self._serve_mock(body, entry)
            else:
                try:
                    self._serve_proxy(raw, body, entry)
                except (OSError, http.client.HTTPException) as exc:
                    entry.setdefault("status", 502)
                    entry["error"] = repr(exc)
                    if not entry.get("headers_sent"):
                        try:
                            self._json(502, {"error": {"message": f"gateway upstream error: {exc!r}"}})
                        except OSError:
                            pass  # client already gone
        finally:
            entry["t_end"] = _now_ms()
            entry["latency_ms"] = entry["t_end"] - entry["t_start"]
            if entry.get("t_first_byte"):
                entry["ttft_ms"] = entry["t_first_byte"] - entry["t_start"]
            entry.update(usage_to_tokens(entry.get("usage")))
            _record(entry, body, self.save_bodies)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_mock(self, body: dict[str, Any], entry: dict[str, Any]) -> None:
        reply = mock_reply(body)
        model = body.get("model") or "mock"
        entry.update(status=200, usage=reply["usage"], t_first_byte=_now_ms())
        if not body.get("stream"):
            self._json(200, {
                "id": f"chatcmpl-{uuid.uuid4().hex[:12]}", "object": "chat.completion", "created": int(time.time()),
                "model": model, "usage": reply["usage"],
                "choices": [{"index": 0, "message": reply["message"], "finish_reason": reply["finish"]}],
            })
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for chunk in _mock_chunks(reply, model):
            self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self.close_connection = True

    def _serve_proxy(self, raw: bytes, body: dict[str, Any], entry: dict[str, Any]) -> None:
        target = urlsplit(self.upstream)
        path = target.path.rstrip("/") + self.path
        conn_cls = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
        conn = conn_cls(target.netloc, timeout=600)
        try:
            headers = {k: v for k, v in self.headers.items() if k.lower() in ("authorization", "content-type", "accept", "user-agent")}
            conn.request("POST", path, body=raw, headers=headers)
            upstream = conn.getresponse()
            entry["status"] = upstream.status
            is_sse = "text/event-stream" in (upstream.getheader("Content-Type") or "")
            self.send_response(upstream.status)
            for key, value in upstream.getheaders():
                if key.lower() in ("content-type", "cache-control"):
                    self.send_header(key, value)
            self.end_headers()
            entry["headers_sent"] = True
            self.close_connection = True
            if not is_sse:  # non-stream answer, or a JSON error for a stream request
                data = upstream.read()
                entry["t_first_byte"] = _now_ms()
                self.wfile.write(data)
                try:
                    entry["usage"] = json.loads(data).get("usage")
                except (json.JSONDecodeError, AttributeError):
                    pass
                if upstream.status >= 400:
                    entry["error_body"] = data[:2000].decode("utf-8", "replace")
                return
            while True:
                line = upstream.readline()
                if not line:
                    break
                self.wfile.write(line)
                self.wfile.flush()
                if line.startswith(b"data:"):  # SSE comments such as `: keep-alive` are not tokens
                    entry.setdefault("t_first_byte", _now_ms())
                if line.startswith(b"data: {"):
                    try:
                        chunk = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("usage"):
                        entry["usage"] = chunk["usage"]
        finally:
            conn.close()


def serve(mode: str = "mock", port: int = 8790, upstream: str = "https://api.deepseek.com", save_bodies: bool = True) -> ThreadingHTTPServer:
    if mode not in ("mock", "proxy"):
        raise SystemExit("mode must be mock or proxy")
    handler = type("Handler", (_Handler,), {"mode": mode, "upstream": upstream, "save_bodies": save_bodies})
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def calls_between(t0_ms: int, t1_ms: int) -> list[dict[str, Any]]:
    """Gateway calls that started inside one run's time window (runs are sequential)."""
    if not CALLS_FILE.is_file():
        return []
    out = []
    with CALLS_FILE.open(encoding="utf-8") as fh:
        for line in fh:
            entry = json.loads(line)
            if t0_ms <= entry.get("t_start", 0) <= t1_ms:
                out.append(entry)
    return out


def body_path(call_id: str) -> Path:
    return GATEWAY_DIR / "bodies" / f"{call_id}.json"
