"""Start/stop the recording gateway from the UI and point new sessions and runs at it.

While it runs, this process's DEEPSEEK_BASE_URL is the gateway (both engines read it),
and the previous value becomes the proxy upstream. Stopping restores it. `.env` is not
touched, so this only lasts as long as `lab ui`.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from lab.model import DEFAULT_BASE_URL

PORT = 8790
LOCK = threading.RLock()  # also held by settings.update while it changes the same variables
_lock = LOCK
_state: dict[str, Any] = {}


def running() -> bool:
    with _lock:
        return bool(_state)


def status() -> dict[str, Any]:
    with _lock:
        if not _state:
            return {"running": False}
        return {"running": True, "mode": _state["mode"], "url": _state["url"], "upstream": _state["upstream"]}


def start(mode: str, port: int = PORT) -> dict[str, Any]:
    from lab.gateway import serve

    with _lock:
        if _state:
            raise ValueError(f"gateway already running ({_state['mode']})")
        upstream = os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL
        try:
            server = serve(mode, port, upstream)
        except OSError as exc:
            raise ValueError(f"port {port} is busy ({exc.strerror}); stop the other gateway first") from None
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_address[1]}"
        _state.update(mode=mode, url=url, upstream=upstream, server=server,
                      saved={k: os.environ.get(k) for k in ("DEEPSEEK_BASE_URL", "DEEPSEEK_API_KEY")})
        os.environ["DEEPSEEK_BASE_URL"] = url
        if mode == "mock" and not os.environ.get("DEEPSEEK_API_KEY"):
            os.environ["DEEPSEEK_API_KEY"] = "mock"  # the mock never checks it; process-only
    return status()


def stop() -> dict[str, Any]:
    with _lock:
        if not _state:
            return {"running": False}
        _state["server"].shutdown()
        _state["server"].server_close()
        for key, value in _state["saved"].items():
            if key == "DEEPSEEK_API_KEY" and os.environ.get(key) != "mock":
                continue  # the user saved a real key meanwhile
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _state.clear()
    return {"running": False}
