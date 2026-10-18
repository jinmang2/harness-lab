"""Local model gateway on 127.0.0.1 for both engines.

Point `DEEPSEEK_BASE_URL` at it and both the lab engine and DeepSeek Harness send
their model requests here. It speaks the two wire formats in use: OpenAI-compatible
`/chat/completions` (lab engine, DSH 0.1.x) and Anthropic-compatible `/v1/messages`
(DSH 0.2.x, whose official route is DeepSeek's `/anthropic` root). Every call is appended to `runs/gateway/calls.jsonl`
(and the full request body to `runs/gateway/bodies/<id>.json`), so the two engines
are measured by the same, provider-reported numbers and you can read exactly what
each harness put in front of the model.

Modes:
- `proxy`: forward to the real API (`LAB_UPSTREAM`, default https://api.deepseek.com;
  Messages requests go to its `/anthropic` root), streaming bytes through unchanged.
- `mock` : answer locally with no key and no cost. If tools are offered and the last
  message is from the user, it calls one tool (prefers bash/shell/execute with
  `echo MOCK_OK`); otherwise it replies `MOCK_DONE`. For wiring tests, not for results.

Credential headers (Authorization, x-api-key) are never logged.
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


def _is_messages(path: str) -> bool:
    return path.split("?")[0].rstrip("/").endswith("/messages")


def _describe(body: dict[str, Any]) -> dict[str, Any]:
    messages = body.get("messages") or []
    tools = body.get("tools") or []
    system: list[Any] = [m.get("content") for m in messages if m.get("role") == "system"]
    if body.get("system"):  # Messages: top-level system (string or blocks)
        system.append(body["system"])
    return {
        "model": body.get("model"),
        "stream": bool(body.get("stream")),
        "thinking": (body.get("thinking") or {}).get("type"),
        "messages": len(messages),
        "system_chars": sum(len(c) if isinstance(c, str) else len(json.dumps(c, ensure_ascii=False)) for c in system),
        "tools": [t.get("function", {}).get("name") or t.get("name") for t in tools],
        "tool_schema_chars": len(json.dumps(tools, ensure_ascii=False)) if tools else 0,
        "request_bytes": len(json.dumps(body, ensure_ascii=False).encode()),
    }


def usage_to_tokens(usage: dict[str, Any] | None) -> dict[str, int]:
    """Provider usage -> disjoint token fields (see lab.trace).

    Messages usage is already disjoint (`input_tokens` excludes cache reads and writes);
    chat/completions `prompt_tokens` includes the cache hits.
    """
    usage = usage or {}
    if "input_tokens" in usage:
        return {
            "input_uncached": int(usage.get("input_tokens") or 0),
            "cache_read": int(usage.get("cache_read_input_tokens") or 0),
            "cache_write": int(usage.get("cache_creation_input_tokens") or 0),
            "output": int(usage.get("output_tokens") or 0),
            "reasoning": 0,  # Messages reports thinking inside output_tokens
        }
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


_RALPH_REPORT = {"status", "summary", "evidence", "nextSteps", "blocker"}


def _mock_args(schema: dict[str, Any]) -> dict[str, Any]:
    params = schema.get("parameters") or schema.get("input_schema") or {}
    props = params.get("properties") or {}
    if _RALPH_REPORT - {"evidence"} <= set(props):  # a Ralph round report: a valid completion, so loops end in one round
        report = {"status": "complete", "summary": "mock round", "evidence": ["MOCK_OK"], "nextSteps": [], "blocker": ""}
        return {k: v for k, v in report.items() if k in props}
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


# `[mock:ask]`, `[mock:ask2]`, `[mock:plan]`, `[mock:slow]`, `[mock:goal]` (and goal rounds) script calls, to exercise the
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
    if "[mock:slow]" in text and names & {"bash", "execute"}:
        name = "bash" if "bash" in names else "execute"
        return [{"name": name, "arguments": json.dumps({"command": "sleep 2; echo SLOW_DONE"})}]
    if "[mock:goal]" in text and "create_goal" in names:
        return [{"name": "create_goal", "arguments": json.dumps({"objective": "Write DONE.md", "max_goal_rounds": 5})}]
    if "[mock:ask2]" in text and "ask_user_question" in names:
        return [{"name": "ask_user_question", "arguments": json.dumps(_SCRIPTS["[mock:ask]"][1])}] * 2
    for marker, (name, args) in _SCRIPTS.items():
        if marker in text and name in names:
            return [{"name": name, "arguments": json.dumps(args)}]
    return None


def _goal_round_call(messages: list[dict[str, Any]], names: set[Any]) -> list[dict[str, Any]] | None:
    """In a goal round: read the goal, then mark it complete (once)."""
    users = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if not users or "update_goal" not in names:
        return None
    last = users[-1]
    if "<goal_round>" not in str(messages[last].get("content")):
        return None
    if "[mock:stay]" in str(messages[last].get("content")):  # a goal that keeps running: slow work, never completes
        if messages[-1].get("role") == "user" and names & {"bash", "execute"}:
            return [{"name": "bash" if "bash" in names else "execute", "arguments": json.dumps({"command": "sleep 2; echo WORKING"})}]
        return None
    after = messages[last + 1:]
    if any(c.get("function", {}).get("name") == "update_goal" for m in after for c in m.get("tool_calls") or []):
        return None
    seen = [m for m in after if m.get("role") == "tool" and '"goal":{"id"' in str(m.get("content"))]
    if not seen:
        return [{"name": "get_goal", "arguments": "{}"}]
    g = json.loads(seen[-1]["content"])["goal"]
    return [{"name": "update_goal", "arguments": json.dumps({"goal_id": g["id"], "revision": g["revision"], "action": "complete"})}]


_LOOP_STARTERS = {"[mock:ralph]": "ralph", "[mock:vralph]": "verified_ralph"}
_ROUND_ENDERS = ("structured_output", "ralph_handoff")  # a round's last call: report or handoff


def _ralph_calls(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Ralph loops: start the loop tool on a marker; end a round with its report/handoff after one tool result."""
    names = {t.get("name") for t in tools}
    last = messages[-1] if messages else {}
    called = {c.get("function", {}).get("name") for m in messages for c in m.get("tool_calls") or []}
    if last.get("role") == "user":
        for marker, name in _LOOP_STARTERS.items():
            if marker in str(last.get("content")) and name in names and name not in called:
                return [{"name": name, "arguments": json.dumps({"objective": "Write DONE.md", "maxRounds": 2})}]
    if last.get("role") == "tool":
        for name in _ROUND_ENDERS:
            if name in names and name not in called:
                schema = next(t for t in tools if t.get("name") == name)
                return [{"name": name, "arguments": json.dumps(_mock_args(schema))}]
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
    elif "fully met the user's objective" in system_text:  # ralph-judge: the objective is met
        message["content"] = json.dumps({"done": True, "reason": "mock", "next": ""})
        finish = "stop"
    elif tools and (scripted := _ralph_calls(messages, tools)) is not None:
        message["tool_calls"] = [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function", "function": f} for f in scripted]
        finish = "tool_calls"
    elif tools and (scripted := _goal_round_call(messages, {t.get("name") for t in tools})) is not None:
        message["tool_calls"] = [{"id": f"call_{uuid.uuid4().hex[:12]}", "type": "function", "function": f} for f in scripted]
        finish = "tool_calls"
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


def _block_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict):
            out.append(str(b.get("text") or "") if b.get("type") == "text" else _block_text(b.get("content")) if b.get("type") == "tool_result" else "")
    return " ".join(out)


def _messages_goal_call(messages: list[dict[str, Any]], names: set[Any]) -> tuple[str, dict[str, Any]] | None:
    """Messages twin of the chat goal scripts: `[mock:goal]` creates a goal; a `<goal_round>` reads it, then completes it."""
    def tool_uses(ms: list[dict[str, Any]]) -> list[str]:
        return [b.get("name") for m in ms if m.get("role") == "assistant" and isinstance(m.get("content"), list)
                for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"]

    prompts = [i for i, m in enumerate(messages) if m.get("role") == "user" and not any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in (m.get("content") if isinstance(m.get("content"), list) else []))]
    if not prompts:
        return None
    last = prompts[-1]
    text, after = _block_text(messages[last].get("content")), messages[last + 1:]
    if "<goal_round>" in text and "update_goal" in names:
        if "update_goal" in tool_uses(after):
            return None
        seen = [_block_text(m.get("content")) for m in after if m.get("role") == "user" and '"goal":{"id"' in _block_text(m.get("content"))]
        if not seen:
            return ("get_goal", {})
        raw = seen[-1]
        g = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])["goal"]
        return ("update_goal", {"goal_id": g["id"], "revision": g["revision"], "action": "complete"})
    if any("[mock:goal]" in _block_text(messages[i].get("content")) for i in prompts) and "create_goal" in names \
            and "create_goal" not in tool_uses(messages):
        return ("create_goal", {"objective": "Write DONE.md", "max_goal_rounds": 5})
    return None


def mock_messages_reply(body: dict[str, Any]) -> dict[str, Any]:
    """The Messages twin of `mock_reply`: one tool call per user turn, then text.

    A child that must answer through `structured_output` calls it after its first tool
    result, so a fresh-agent loop can run end to end without a key.
    """
    messages = body.get("messages") or []
    tools = body.get("tools") or []
    names = {t.get("name") for t in tools}
    last = messages[-1] if messages else {"role": "user", "content": ""}
    blocks = last.get("content") if isinstance(last.get("content"), list) else [{"type": "text", "text": last.get("content") or ""}]
    after_tool = any(isinstance(b, dict) and b.get("type") == "tool_result" for b in blocks)
    text = " ".join(str(b.get("text") or "") for b in blocks if isinstance(b, dict))
    called = {b.get("name") for m in messages if m.get("role") == "assistant" and isinstance(m.get("content"), list)
              for b in m["content"] if isinstance(b, dict) and b.get("type") == "tool_use"}
    prompt_tokens = len(json.dumps(messages, ensure_ascii=False)) // 4 + len(json.dumps(tools)) // 4 + len(str(body.get("system") or "")) // 4

    def use(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:12]}", "name": name, "input": args}

    content: list[dict[str, Any]]
    goal_call = _messages_goal_call(messages, names)
    if goal_call is not None:
        content = [use(*goal_call)]
    elif "[mock:ralph]" in text and "ralph" in names and "ralph" not in called:
        content = [use("ralph", {"objective": "Write DONE.md", "maxRounds": 2})]
    elif "[mock:vralph]" in text and "verified_ralph" in names and "verified_ralph" not in called:
        content = [use("verified_ralph", {"objective": "Write DONE.md", "maxRounds": 2})]
    elif after_tool and "structured_output" in names and "structured_output" not in called:
        content = [use("structured_output", _mock_args(next(t for t in tools if t.get("name") == "structured_output")))]
    elif tools and not after_tool:
        chosen = next((t for name in _PREFERRED_TOOLS for t in tools if t.get("name") == name), tools[0])
        content = [use(chosen["name"], _mock_args(chosen))]
    else:
        content = [{"type": "text", "text": "MOCK_DONE"}]
    stop = "tool_use" if content[0]["type"] == "tool_use" else "end_turn"
    usage = {"input_tokens": prompt_tokens, "output_tokens": 12, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return {"content": content, "stop": stop, "usage": usage}


def _mock_messages_events(reply: dict[str, Any], model: str) -> list[tuple[str, dict[str, Any]]]:
    message = {"id": f"msg_{uuid.uuid4().hex[:12]}", "type": "message", "role": "assistant", "model": model,
               "content": [], "stop_reason": None, "usage": {**reply["usage"], "output_tokens": 0}}
    events: list[tuple[str, dict[str, Any]]] = [("message_start", {"type": "message_start", "message": message})]
    for i, block in enumerate(reply["content"]):
        if block["type"] == "text":
            events.append(("content_block_start", {"type": "content_block_start", "index": i, "content_block": {"type": "text", "text": ""}}))
            events.append(("content_block_delta", {"type": "content_block_delta", "index": i, "delta": {"type": "text_delta", "text": block["text"]}}))
        else:
            start = {k: block[k] for k in ("type", "id", "name")} | {"input": {}}
            events.append(("content_block_start", {"type": "content_block_start", "index": i, "content_block": start}))
            events.append(("content_block_delta", {"type": "content_block_delta", "index": i,
                                                   "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}}))
        events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
    events.append(("message_delta", {"type": "message_delta", "delta": {"stop_reason": reply["stop"], "stop_sequence": None},
                                     "usage": {"output_tokens": reply["usage"]["output_tokens"]}}))
    events.append(("message_stop", {"type": "message_stop"}))
    return events


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
            messages_api = _is_messages(self.path)
            if not messages_api and not self.path.rstrip("/").endswith("/chat/completions"):
                self._json(404, {"error": f"unsupported path {self.path}"})
                entry["status"] = 404
            elif self.mode == "mock":
                (self._serve_mock_messages if messages_api else self._serve_mock)(body, entry)
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

    def _serve_mock_messages(self, body: dict[str, Any], entry: dict[str, Any]) -> None:
        reply = mock_messages_reply(body)
        model = body.get("model") or "mock"
        entry.update(status=200, usage=reply["usage"], t_first_byte=_now_ms())
        if not body.get("stream"):
            self._json(200, {"id": f"msg_{uuid.uuid4().hex[:12]}", "type": "message", "role": "assistant", "model": model,
                             "content": reply["content"], "stop_reason": reply["stop"], "usage": reply["usage"]})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for name, data in _mock_messages_events(reply, model):
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode())
        self.wfile.flush()
        self.close_connection = True

    def _serve_proxy(self, raw: bytes, body: dict[str, Any], entry: dict[str, Any]) -> None:
        target = urlsplit(self.upstream)
        root = target.path.rstrip("/")
        if _is_messages(self.path) and not root.endswith("/anthropic"):
            root += "/anthropic"  # DeepSeek serves Messages under its /anthropic root
        path = root + self.path
        conn_cls = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
        conn = conn_cls(target.netloc, timeout=600)
        try:
            forwarded = ("authorization", "x-api-key", "anthropic-version", "anthropic-beta", "content-type", "accept", "user-agent")
            headers = {k: v for k, v in self.headers.items() if k.lower() in forwarded}
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
                    kind = chunk.get("type")
                    if kind == "message_start":  # Messages: input usage first, final output in message_delta
                        entry["usage"] = dict((chunk.get("message") or {}).get("usage") or {})
                    elif kind == "message_delta":
                        entry["usage"] = {**(entry.get("usage") or {}), **(chunk.get("usage") or {})}
                    elif chunk.get("usage"):
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
