from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from ..db import audit, connect, dumps, loads, now_iso, transaction
from ..errors import conflict, not_found
from ..security import Session, require_mutation, require_session
from ..services import importance, preferences
from ..services.import_service import message_detail, message_summary

router = APIRouter(prefix="/api")
CATEGORIES = ("academic", "career", "events", "promotions", "other")


def _threshold(conn) -> float:
    return preferences.get_raw(conn)[0].get("large_amount_threshold", importance.DEFAULT_THRESHOLD)


def _counts(conn) -> dict:
    th = _threshold(conn)
    demo = preferences.show_demo_data(conn)
    rows = conn.execute("SELECT analysis_json, subject FROM messages WHERE direction='inbound' AND source_type='email' AND excluded=0"
                        + ("" if demo else " AND connection_id NOT LIKE 'conn_local%'")).fetchall()
    counts = {"all": len(rows), "important": 0, "needs_reply": 0, "needs_action": 0, "uncategorized": 0,
              **{c: 0 for c in CATEGORIES}}
    for r in rows:
        a = loads(r[0], None) or {}
        cat = a.get("category")
        counts[cat if cat in CATEGORIES else "uncategorized"] += 1
        counts["important"] += importance.evaluate(a, th, r[1])[0] if a else 0
        counts["needs_reply"] += a.get("needs_reply") is True
        counts["needs_action"] += a.get("needs_action") is True
    return counts


@router.get("/messages")
def list_messages(
    direction: Literal["inbound", "outbound", "document"] = "inbound",
    category: str | None = None,
    needs_reply: bool | None = None,
    needs_action: bool | None = None,
    important: bool | None = None,
    q: str | None = None,
    cursor: int = 0,
    limit: int = Query(200, ge=1, le=500),
    _: Session = Depends(require_session),
):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE direction=? AND source_type IN ('email') AND excluded=0"
            + ("" if direction != "inbound" or preferences.show_demo_data(conn) else " AND connection_id NOT LIKE 'conn_local%'")
            + " ORDER BY sent_at DESC", (direction,)).fetchall()
        th = _threshold(conn)
        items = [message_summary(r, th) for r in rows]
        if category and category != "all":
            items = [m for m in items if m["category"] == category]
        # Requirement filters combine with AND, as in the design.
        if needs_reply:
            items = [m for m in items if m["needs_reply"] is True]
        if needs_action:
            items = [m for m in items if m["needs_action"] is True]
        if important:
            items = [m for m in items if m["important"]]
        if q:
            needle = q.strip().lower()
            items = [m for m in items if needle in (m["subject"] + " " + m["summary"] + " " + m["source_id"] + " "
                                                    + m["sender_label"]).lower()]
        # Important / attention first, then newest - same order as the reference cards.
        items.sort(key=lambda m: (not m["important"], not m["attention_flags"]))
        page = items[cursor:cursor + limit]
        nxt = str(cursor + limit) if cursor + limit < len(items) else None
        return {"items": page, "next_cursor": nxt, "total": len(items), "counts": _counts(conn)}


def _source_info(conn, row) -> dict:
    """Where the original lives. Links are built only from the provider's own message id and the
    connected account - never from URLs found inside the mail."""
    from urllib.parse import quote
    cid = row["connection_id"]
    info = {"kind": "sample" if cid.startswith("conn_local") else cid.removeprefix("conn_"),
            "provider_message_id": row["provider_message_id"], "thread_id": row["thread_id"],
            "received_at": row["sent_at"], "account": None, "open_url": None}
    if cid in ("conn_google", "conn_microsoft"):
        acc = conn.execute("SELECT account_label FROM connections WHERE id=?", (cid,)).fetchone()
        info["account"] = acc[0] if acc else None
        pid = row["provider_message_id"]
        if cid == "conn_google" and pid.isalnum():
            info["open_url"] = (f"https://mail.google.com/mail/?authuser={quote(info['account'] or '')}#all/{pid}")
        elif cid == "conn_microsoft":
            info["open_url"] = f"https://outlook.office.com/mail/deeplink/read/{quote(pid, safe='')}"
    return info


@router.get("/messages/{message_id}")
def get_message(message_id: str, _: Session = Depends(require_session)):
    with connect() as conn:
        row = conn.execute("SELECT * FROM messages WHERE id=? OR source_id=?", (message_id, message_id)).fetchone()
        if not row:
            raise not_found("message")
        detail = message_detail(row, _threshold(conn))
        detail["source"] = _source_info(conn, row)
        detail["linked_tasks"] = [dict(r) for r in conn.execute(
            """SELECT DISTINCT t.id, t.title, t.title_en, t.status, e.relation FROM task_evidence e JOIN tasks t ON t.id=e.task_id
               WHERE e.message_id=?""", (row["id"],)).fetchall()]
        from ..services import ref_i18n
        for lt in detail["linked_tasks"]:
            key = conn.execute("SELECT entity_key FROM tasks WHERE id=?", (lt["id"],)).fetchone()[0]
            lt["title_en"] = lt["title_en"] or ref_i18n.task_title(key)
        return detail


class AnalysisCorrection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int
    category: Literal["academic", "career", "events", "promotions", "other"] | None = None
    needs_reply: bool | None = None
    needs_action: bool | None = None
    important: bool | None = None


class RemoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_ids: list[str]


@router.post("/messages/remove")
def remove(body: RemoveIn, _: Session = Depends(require_mutation)):
    """Remove from this app only; the Gmail/Outlook original is untouched (read-only access)."""
    from ..services.removal import remove_messages
    with connect() as conn, transaction(conn):
        return remove_messages(conn, body.message_ids)


@router.patch("/messages/{message_id}/analysis")
def correct_analysis(message_id: str, body: AnalysisCorrection, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        row = conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        if not row:
            raise not_found("message")
        if row["revision"] != body.expected_revision:
            raise conflict("REVISION_CONFLICT", "Message changed; reload", [f"current_revision={row['revision']}"])
        a = loads(row["analysis_json"], None) or {}
        changes = body.model_dump(exclude_none=True, exclude={"expected_revision"})
        history = a.get("corrections", [])
        history.append({"at": now_iso(), "previous_origin": row["analysis_origin"],
                        "previous": {k: a.get(k) for k in changes}})
        if "important" in changes:
            a["important_override"] = changes["important"]  # explicit user choice beats the rule
        a.update(changes)
        a["corrections"] = history
        conn.execute("UPDATE messages SET analysis_json=?, analysis_origin='user', revision=revision+1, updated_at=? WHERE id=?",
                     (dumps(a), now_iso(), message_id))
        audit(conn, "analysis_corrected", "message", message_id, {"fields": sorted(changes)})
        return message_detail(conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone(), _threshold(conn))
