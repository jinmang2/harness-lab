"""Composer attachments, as DeepSeek Harness Web handles them (MIT).

- Images (PNG, JPEG, WebP, GIF) go to the model as image content blocks, only on a
  model that declares image input; the rest is rejected with DSH's message.
- Any other file is saved as a read-only copy and the model gets DSH's handle
  text with its path (`fileHandleText`, packages/llm/llm/src/content.ts); the
  bytes never go into the request.
"""

from __future__ import annotations

import base64
import hashlib
import re
import struct
import uuid
from pathlib import Path
from typing import Any

IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
MAX_IMAGE_BYTES = 20 * 1024 * 1024  # attachment-local admission default
MAX_IMAGES_PER_MESSAGE = 20
MAX_FILE_BYTES = 100 * 1024 * 1024  # DSH has no file cap; this lab keeps uploads bounded


def _dims(data: bytes, mime: str) -> tuple[int, int] | None:
    try:
        if mime == "image/png" and data[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", data[16:24])
        if mime == "image/gif" and data[:4] == b"GIF8":
            return struct.unpack("<HH", data[6:10])
        if mime == "image/webp" and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            chunk = data[12:16]
            if chunk == b"VP8X":
                return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
            if chunk == b"VP8 ":
                w, h = struct.unpack("<HH", data[26:30])
                return w & 0x3FFF, h & 0x3FFF
            if chunk == b"VP8L":
                b = int.from_bytes(data[21:25], "little")
                return (b & 0x3FFF) + 1, ((b >> 14) & 0x3FFF) + 1
        if mime == "image/jpeg" and data[:2] == b"\xff\xd8":
            i = 2
            while i + 9 < len(data):
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker, size = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    h, w = struct.unpack(">HH", data[i + 5:i + 9])
                    return w, h
                i += 2 + size
    except (struct.error, IndexError):
        return None
    return None


def _magic_ok(data: bytes, mime: str) -> bool:
    return {
        "image/png": data[:8] == b"\x89PNG\r\n\x1a\n",
        "image/jpeg": data[:3] == b"\xff\xd8\xff",
        "image/gif": data[:6] in (b"GIF87a", b"GIF89a"),
        "image/webp": data[:4] == b"RIFF" and data[8:12] == b"WEBP",
    }.get(mime, False)


def save(folder: Path, name: str, mime: str, data_b64: str) -> dict[str, Any]:
    """Store one upload read-only under `folder`; returns its record (no bytes)."""
    try:
        data = base64.b64decode(data_b64, validate=True)
    except (ValueError, TypeError):
        raise ValueError("attachment data must be base64") from None
    clean = re.sub(r"[^\w.\- ()]+", "_", Path(name or "file").name).strip(" .") or "file"
    if len(clean) > 120:  # keep the stored name well under filesystem limits, extension intact
        stem, dot, ext = clean.rpartition(".")
        clean = (stem[: 110 - len(ext)] + dot + ext) if dot and len(ext) <= 10 else clean[:120]
    kind = "image" if mime in IMAGE_TYPES else "file"
    if kind == "image":
        if not _magic_ok(data, mime):
            raise ValueError("Only PNG, JPG, WebP, and GIF images are supported")
        if len(data) >= MAX_IMAGE_BYTES:
            raise ValueError("Each image must be smaller than 20 MB")
    elif len(data) > MAX_FILE_BYTES:
        raise ValueError("files over 100 MB are not accepted in this lab")
    aid = "att-" + uuid.uuid4().hex[:12]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{aid}-{clean}"
    path.write_bytes(data)
    path.chmod(0o444)  # DSH saves a verbatim read-only copy
    rec: dict[str, Any] = {"id": aid, "name": clean, "mime": mime or "application/octet-stream", "bytes": len(data),
                           "sha256": hashlib.sha256(data).hexdigest(), "kind": kind, "path": str(path)}
    if kind == "image" and (wh := _dims(data, mime)):
        rec["width"], rec["height"] = wh
    return rec


def file_handle_text(rec: dict[str, Any]) -> str:
    return (f'[File "{rec["name"]}" ({rec["bytes"]} bytes, sha256:{rec["sha256"][:8]}): verbatim read-only copy saved at '
            f'"{rec["path"]}". Read that path with your file tools when its contents are needed; copy it to a writable '
            "location before modifying it. When delegating file work, include this saved path in the delegation prompt; "
            "only subagents sharing this execution environment can read it.]")


def image_handle_text(rec: dict[str, Any]) -> str:
    size = f" request preview {rec['width']}x{rec['height']}px." if rec.get("width") else ""
    return f'Image "{rec["name"]}" ({rec["id"]});{size}'


def content_blocks(text: str, recs: list[dict[str, Any]]) -> list[dict[str, Any]] | str:
    """User message content: attachments first, then the typed text (DSH order)."""
    if not recs:
        return text
    blocks: list[dict[str, Any]] = []
    for rec in recs:
        if rec["kind"] == "image":
            data = base64.b64encode(Path(rec["path"]).read_bytes()).decode()
            blocks.append({"type": "image_url", "image_url": {"url": f"data:{rec['mime']};base64,{data}"}})
            blocks.append({"type": "text", "text": image_handle_text(rec)})
        else:
            blocks.append({"type": "text", "text": file_handle_text(rec)})
    if text:
        blocks.append({"type": "text", "text": text})
    return blocks


def public(rec: dict[str, Any]) -> dict[str, Any]:
    """What the browser sees: no host path."""
    return {k: rec[k] for k in ("id", "name", "mime", "bytes", "kind", "width", "height") if k in rec}
