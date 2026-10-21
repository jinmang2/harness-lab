"""Proxy gateway: an upstream reset before any content reached the client is retried transparently."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lab import gateway

START = (b'event: message_start\ndata: {"type": "message_start", "message": {"usage": {"input_tokens": 5}}}\n\n'
         b'event: content_block_start\ndata: {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}}\n\n')
CONTENT = (b'event: content_block_delta\ndata: {"type": "content_block_delta", "delta": {"text": "hi"}}\n\n'
           b'event: message_delta\ndata: {"type": "message_delta", "usage": {"output_tokens": 1}}\n\n'
           b'event: message_stop\ndata: {"type": "message_stop"}\n\n')


def _upstream(script: list[str]) -> ThreadingHTTPServer:
    """Each request pops one behaviour: "reset-early" (start, then RST), "reset-late" (start + one content event, RST), "ok"."""

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            how = script.pop(0)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(START)
            if how == "ok":
                self.wfile.write(CONTENT)
                return
            if how == "reset-late":
                self.wfile.write(CONTENT.split(b"\n\n")[0] + b"\n\n")
            self.wfile.flush()
            if how == "reset-late":
                time.sleep(0.2)  # let the gateway read the content first: an RST can drop unread bytes
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, b"\x01\x00\x00\x00\x00\x00\x00\x00")
            self.connection.close()  # SO_LINGER 0: RST, like the observed `Connection reset by peer`

    server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _call(script: list[str], tmp_path, monkeypatch, buffer: bool = False) -> tuple[bytes, dict]:
    monkeypatch.setattr(gateway, "CALLS_FILE", tmp_path / "calls.jsonl")
    monkeypatch.setattr(gateway, "GATEWAY_DIR", tmp_path)
    up = _upstream(script)
    gw = gateway.serve("proxy", port=0, upstream=f"http://127.0.0.1:{up.server_address[1]}", save_bodies=False,
                       buffer_streams=buffer)
    threading.Thread(target=gw.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{gw.server_address[1]}/v1/messages", method="POST",
                                     data=json.dumps({"model": "m", "stream": True, "messages": []}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            data = urllib.request.urlopen(req, timeout=10).read()
        except Exception as exc:  # noqa: BLE001 - a truncated stream is a result here
            data = getattr(exc, "partial", b"")
    finally:
        gw.shutdown()
        up.shutdown()
    entry = json.loads((tmp_path / "calls.jsonl").read_text().splitlines()[-1])
    return data, entry


def test_an_early_reset_is_retried_and_the_client_sees_one_clean_stream(tmp_path, monkeypatch):
    data, entry = _call(["reset-early", "ok"], tmp_path, monkeypatch)
    assert data.count(b"event: message_start") == 1 and data.count(b"event: content_block_start") == 1 and data.endswith(b'data: {"type": "message_stop"}\n\n')
    assert entry["upstream_retries"] == 1 and entry["usage"]["output_tokens"] == 1 and not entry.get("error")


def test_a_reset_after_content_is_not_retried(tmp_path, monkeypatch):
    data, entry = _call(["reset-late", "ok"], tmp_path, monkeypatch)
    assert b"message_stop" not in data and "upstream_retries" not in entry and entry["last_event"] == "content_block_delta"
    assert "Reset" in entry["error"] or "Broken" in entry["error"] or "closed" in entry["error"].lower()


@pytest.mark.parametrize("script", [["reset-early"] * 4])
def test_retries_are_bounded(script, tmp_path, monkeypatch):
    data, entry = _call(script, tmp_path, monkeypatch)
    assert entry["upstream_retries"] == gateway.UPSTREAM_RETRIES and entry.get("error")


def test_buffered_streams_retry_a_reset_after_content_and_send_one_clean_stream(tmp_path, monkeypatch):
    data, entry = _call(["reset-late", "ok"], tmp_path, monkeypatch, buffer=True)
    assert data.count(b"event: message_start") == 1 and data.count(b"content_block_delta") == 2  # event + type, once
    assert data.endswith(b'data: {"type": "message_stop"}\n\n') and entry["upstream_retries"] == 1


def test_buffered_streams_send_keepalive_comments_while_holding(tmp_path, monkeypatch):
    monkeypatch.setattr(gateway, "KEEPALIVE_S", 0.05)
    import time as _t

    class Slow:
        def __init__(self):
            self.lines = [START, b""]

        def readline(self):
            _t.sleep(0.2)
            return self.lines.pop(0)

    out = []

    class W:
        def write(self, b):
            out.append(b)

        def writelines(self, bs):
            out.extend(bs)

        def flush(self):
            pass

    h = gateway._Handler.__new__(gateway._Handler)
    h.wfile, h.buffer_streams = W(), True
    assert h._relay_stream(Slow(), {}, retryable=True) is True
    assert any(b.startswith(b": lab-gateway keep-alive") for b in out) and out[-1] == START
