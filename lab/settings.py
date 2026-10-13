"""Settings for the local UI: API keys and model defaults, stored in `.env`.

Like DeepSeek Harness's credentials store, secrets are write-only: the UI only ever
gets `{configured, source}` back, never the value. `.env` is gitignored and written
with mode 600. Changes apply to this process immediately (new sessions and runs) and
to later `lab` commands through `.env`.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from lab import DOTENV_KEYS, ENV_FILE
from lab.model import CATALOG, DEFAULT_BASE_URL, DEFAULT_MODEL, EFFORTS

SECRETS = ("DEEPSEEK_API_KEY", "LANGSMITH_API_KEY", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
PLAIN = {
    "LAB_MODEL": DEFAULT_MODEL,
    "LAB_THINKING": "enabled",
    "LAB_REASONING_EFFORT": "high",
    "DEEPSEEK_BASE_URL": DEFAULT_BASE_URL,
    "LAB_MODEL_SPEC": "",
    "LAB_JUDGE_MODEL_SPEC": "",
    "LAB_HITL": "approve",
    "LANGSMITH_TRACING": "",
    "LANGFUSE_HOST": "",
}
CHOICES = {"LAB_THINKING": ["enabled", "disabled"], "LAB_REASONING_EFFORT": ["low", "high", "max"], "LAB_HITL": ["approve", "reject"]}


def _source(key: str) -> str | None:
    if not os.environ.get(key):
        return None
    return ".env" if key in DOTENV_KEYS else "env"


def describe() -> dict[str, Any]:
    from lab.viewer import gateway_control

    return {
        "secrets": {k: {"configured": bool(os.environ.get(k)), "source": _source(k)} for k in SECRETS},
        "values": {k: {"value": os.environ.get(k, ""), "default": d, "source": _source(k)} for k, d in PLAIN.items()},
        "choices": CHOICES,
        "models": CATALOG,
        "efforts": EFFORTS,
        "env_file": str(ENV_FILE),
        "gateway": gateway_control.status(),
    }


def _write_env(changes: dict[str, str | None]) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").split("\n") if ENV_FILE.is_file() else []
    while lines and not lines[-1]:
        lines.pop()
    done: set[str] = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else None
        if key in changes:
            if key not in done and changes[key]:
                out.append(f"{key}={changes[key]}")
            done.add(key)
            continue
        out.append(line)
    out += [f"{k}={v}" for k, v in changes.items() if k not in done and v]
    tmp = ENV_FILE.with_suffix(".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, ENV_FILE)


def update(changes: dict[str, Any]) -> dict[str, Any]:
    """Set (non-empty string) or unset (empty / null) keys; unknown keys are rejected."""
    clean: dict[str, str | None] = {}
    for key, value in changes.items():
        if key not in SECRETS and key not in PLAIN:
            raise ValueError(f"unknown setting {key!r}")
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        value = None if value is None else value.strip()
        if value and (value != "".join(value.splitlines()) or any(ord(c) < 32 or ord(c) == 127 for c in value)):
            raise ValueError(f"{key} must be one line of printable text")
        if value and key in CHOICES and value not in CHOICES[key]:
            raise ValueError(f"{key} must be one of {CHOICES[key]}")
        clean[key] = value or None
    from lab.viewer import gateway_control

    with gateway_control.LOCK:  # the gateway swaps DEEPSEEK_BASE_URL / the mock key under the same lock
        if "DEEPSEEK_BASE_URL" in clean and gateway_control.running():
            raise ValueError("stop the gateway before changing DEEPSEEK_BASE_URL")
        _write_env(clean)
        for key, value in clean.items():
            if value:
                os.environ[key] = value
                DOTENV_KEYS.add(key)
            else:
                os.environ.pop(key, None)
                DOTENV_KEYS.discard(key)
    return describe()


def discover_models(timeout: float = 10) -> dict[str, Any]:
    """`GET {base}/models` with the configured key, like DeepSeek Harness's "fetch models"."""
    key = os.environ.get("DEEPSEEK_API_KEY")
    if not key:
        return {"ok": False, "error": "DEEPSEEK_API_KEY is not set"}
    base = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    req = urllib.request.Request(f"{base}/models", headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except Exception as exc:  # report, never echo the key
        return {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return {"ok": True, "models": sorted(m.get("id") for m in data.get("data", []) if m.get("id"))}
