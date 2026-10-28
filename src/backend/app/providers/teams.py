"""Teams: read only chats the user picks (delegated Chat.Read). Personal Microsoft accounts are not
supported by this API; the paste/import path remains the fallback."""
from __future__ import annotations

import sqlite3

from ..errors import AppError
from .mail_readers import html_to_text
from . import net, oauth


def list_chats(conn: sqlite3.Connection) -> list[dict]:
    if not oauth.has_scope(conn, "microsoft", "read_chat"):
        raise AppError(409, "READ_CHAT_SCOPE_MISSING", "Connect Microsoft with Teams chat read permission first")
    token = oauth.access_token(conn, "microsoft")
    r = net.request("GET", "https://graph.microsoft.com/v1.0/me/chats?$top=50&$select=id,topic,chatType",
                    headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        raise AppError(502, "GRAPH_ERROR", f"Graph returned {r.status_code}")
    return [{"id": c["id"], "topic": c.get("topic") or c.get("chatType")} for c in r.json().get("value", [])]


def read_chat(conn: sqlite3.Connection, chat_id: str, limit: int = 50) -> list[dict]:
    token = oauth.access_token(conn, "microsoft")
    r = net.request("GET", f"https://graph.microsoft.com/v1.0/chats/{chat_id}/messages?$top={min(limit, 50)}",
                    headers={"Authorization": f"Bearer {token}"})
    if r.status_code != 200:
        raise AppError(502, "GRAPH_ERROR", f"Graph returned {r.status_code}")
    out = []
    for i, m in enumerate(reversed(r.json().get("value", []))):
        if m.get("messageType") != "message":
            continue
        body = m.get("body", {})
        text = body.get("content", "") if body.get("contentType") == "text" else html_to_text(body.get("content", ""))
        out.append({"source_id": m["id"], "speaker": ((m.get("from") or {}).get("user") or {}).get("displayName"),
                    "timestamp": m.get("createdDateTime"), "text": text})
    return out
