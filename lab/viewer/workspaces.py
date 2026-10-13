"""Workspaces: folders a chat session can run in, like DSH Web's workspace list.

A session either gets a fresh folder of its own (the default, under runs/) or runs in
one of these. The list lives in runs/workspaces.json.
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from lab import RUNS_DIR

_FILE = RUNS_DIR / "workspaces.json"
_lock = threading.Lock()


def _load() -> list[dict[str, Any]]:
    try:
        rows = json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("path"), str)]


def _save(rows: list[dict[str, Any]]) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, _FILE)


def list_all() -> list[dict[str, Any]]:
    with _lock:
        return [{**r, "exists": Path(r["path"]).is_dir()} for r in _load()]


def add(path: str) -> dict[str, Any]:
    raw = Path(os.path.expanduser(path.strip()))
    if not raw.is_absolute():
        raise ValueError("use an absolute path (or ~/...)")
    folder = raw.resolve()
    if not folder.is_dir():
        raise ValueError(f"not a folder: {folder}")
    with _lock:
        rows = _load()
        row = next((r for r in rows if r["path"] == str(folder)), None)
        if row is None:
            row = {"path": str(folder), "title": folder.name or str(folder)}
            rows.append(row)
            _save(rows)
    return row


def remove(path: str) -> None:
    with _lock:
        _save([r for r in _load() if r["path"] != path])


def resolve(path: str | None) -> Path | None:
    """A registered workspace folder, or None for a fresh per-session folder."""
    if not path:
        return None
    if path not in {r["path"] for r in list_all()}:
        raise ValueError("unknown workspace; add it first")
    folder = Path(path)
    if not folder.is_dir():
        raise ValueError(f"workspace folder is gone: {folder}")
    return folder


SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", ".dsh-home", ".dsh-runtime", ".mypy_cache", ".pytest_cache"}
# Never listed or served to the browser: secrets a workspace (or a home folder) may hold.
SECRET_DIRS = {".ssh", ".aws", ".gnupg", ".config", ".docker", ".kube"}
SECRET_FILES = re.compile(r"^(\.envrc|\.env(\..*)?|\.netrc|\.npmrc|\.pypirc|\.git-credentials|.*\.(pem|key|p12|pfx)|id_[a-z0-9]+(\.pub)?|credentials(\.\w+)?)$", re.I)


def _secret(rel: Path) -> bool:
    return any(part in SECRET_DIRS for part in rel.parts[:-1]) or bool(SECRET_FILES.match(rel.name))


def files(root: Path, limit: int = 2000) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and d not in SECRET_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(root)
            if _secret(rel):
                continue
            try:
                st = path.stat()
            except OSError:  # deleted while walking
                continue
            out.append({"path": str(rel), "bytes": st.st_size, "mtime": st.st_mtime})
            if len(out) >= limit:
                return out
    return out


def read(root: Path, rel: str, max_bytes: int = 500_000) -> bytes | None:
    from lab import ENV_FILE

    base = root.resolve()
    try:
        path = (base / rel).resolve()  # also follows agent-made symlinks
        if (not path.is_relative_to(base) or _secret(path.relative_to(base)) or path == ENV_FILE.resolve()
                or not path.is_file() or path.stat().st_size > max_bytes):
            return None
        return path.read_bytes()
    except (OSError, ValueError):  # NUL bytes, vanished files
        return None
