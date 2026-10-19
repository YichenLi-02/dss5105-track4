"""Remove messages from this app only. The source mailbox is never touched (read-only scope).

A removed message becomes a tombstone: body, analysis and attachment metadata are cleared and
`excluded=1`, so later syncs/imports recognise the provider id and do not bring it back.
Task evidence from the message is deleted; tasks left with no evidence are deleted too
(manual tasks are kept). Drafts the user wrote stay as they are.
"""
from __future__ import annotations

import sqlite3

from ..db import audit, dumps, now_iso
from ..errors import AppError


def remove_messages(conn: sqlite3.Connection, ids: list[str]) -> dict:
    if not ids or len(ids) > 500:
        raise AppError(422, "INVALID_SELECTION", "Choose between 1 and 500 messages")
    ts = now_iso()
    removed, task_ids = 0, set()
    for mid in ids:
        row = conn.execute("SELECT id, excluded, direction FROM messages WHERE id=? AND direction='inbound' "
                           "AND source_type='email'", (mid,)).fetchone()
        if not row or row["excluded"]:
            continue
        task_ids |= {r[0] for r in conn.execute("SELECT task_id FROM task_evidence WHERE message_id=?", (mid,))}
        conn.execute("DELETE FROM task_evidence WHERE message_id=?", (mid,))
        conn.execute(
            """UPDATE messages SET excluded=1, body_view='', subject='', sender_json='{}', recipients_json='{}',
               analysis_json=NULL, analysis_status='removed',
               analysis_origin='none', analysis_cache_key=NULL, attachments_json='[]',
               locator_json=?, revision=revision+1, updated_at=? WHERE id=?""",
            (dumps({"removed_at": ts}), ts, mid))
        removed += 1
    tasks_deleted = 0
    for tid in task_ids:
        left = conn.execute("SELECT COUNT(*) FROM task_evidence WHERE task_id=?", (tid,)).fetchone()[0]
        key = conn.execute("SELECT entity_key FROM tasks WHERE id=?", (tid,)).fetchone()
        if left == 0 and key and not key[0].startswith(("manual_", "synthetic_")):
            conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
            tasks_deleted += 1
    audit(conn, "messages_removed_locally", "message", None, {"count": removed, "tasks_deleted": tasks_deleted})
    return {"removed": removed, "tasks_deleted": tasks_deleted, "source_mailbox_changed": False}
