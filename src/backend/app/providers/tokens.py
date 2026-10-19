"""OAuth tokens live in the OS credential store (Windows Credential Manager via keyring).
The database only holds a credential_ref; tokens never reach the browser or logs.

Windows limits one credential blob to 2560 bytes (~1280 UTF-16 chars), so only the fields we
need are kept (id_token is dropped) and anything still too long is split into numbered parts.
"""
from __future__ import annotations

import json

from ..errors import AppError

SERVICE = "student-work-assistant"
KEEP = ("access_token", "refresh_token", "expires_in", "obtained_at", "token_type", "scope")
CHUNK = 1000
_memory: dict[str, str] = {}  # used only when tests switch the backend off
_use_memory = False


def use_memory_store(flag: bool = True) -> None:
    global _use_memory
    _use_memory = flag


def _kr():
    import keyring
    return keyring


def save(ref: str, token: dict) -> None:
    data = json.dumps({k: token[k] for k in KEEP if k in token}, separators=(",", ":"))
    if _use_memory:
        _memory[ref] = data
        return
    parts = [data[i:i + CHUNK] for i in range(0, len(data), CHUNK)] or [""]
    try:
        kr = _kr()
        delete(ref)
        for i, part in enumerate(parts):
            kr.set_password(SERVICE, f"{ref}#{i}", part)
        kr.set_password(SERVICE, ref, json.dumps({"parts": len(parts)}))
    except Exception as exc:  # noqa: BLE001
        delete(ref)
        raise AppError(503, "CREDENTIAL_STORE_UNAVAILABLE",
                       "Could not write to the system credential store; refusing to keep the token in plain text",
                       [type(exc).__name__]) from exc


def load(ref: str) -> dict | None:
    if _use_memory:
        raw = _memory.get(ref)
        return json.loads(raw) if raw else None
    try:
        kr = _kr()
        head = kr.get_password(SERVICE, ref)
        if not head:
            return None
        meta = json.loads(head)
        if "parts" not in meta:  # legacy single-entry format
            return meta
        raw = "".join(kr.get_password(SERVICE, f"{ref}#{i}") or "" for i in range(meta["parts"]))
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return None


def delete(ref: str) -> None:
    if _use_memory:
        _memory.pop(ref, None)
        return
    try:
        kr = _kr()
        head = kr.get_password(SERVICE, ref)
        n = json.loads(head).get("parts", 0) if head else 0
        for i in range(max(n, 8)):
            try:
                kr.delete_password(SERVICE, f"{ref}#{i}")
            except Exception:  # noqa: BLE001
                pass
        kr.delete_password(SERVICE, ref)
    except Exception:  # noqa: BLE001
        pass
