"""Read/write functions for the orchestration layer. Each takes an open connection and a workspace id."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime
from typing import Iterable, Literal

from ..models import Candidate, PlanBlock, PlanRequest, PlanResult, PlanSettings, Progress, Source, Task, TimeSlot
from ..timeutil import now

ImportStatus = Literal["added", "duplicate", "updated"]


def _ts() -> str:
    return now().isoformat(timespec="seconds")


def content_hash(source: Source) -> str:
    """Same subject and text means the same item, whenever it was added (a re-uploaded PDF, a message pasted twice)."""
    raw = "\x1f".join([source.subject or "", source.body_text])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---- workspaces -----------------------------------------------------------------------------
def ensure_workspace(conn: sqlite3.Connection, ws: str) -> None:
    conn.execute("INSERT OR IGNORE INTO workspaces (id, created_at) VALUES (?, ?)", (ws, _ts()))


def set_demo_now(conn: sqlite3.Connection, ws: str, demo_now: datetime | None) -> None:
    ensure_workspace(conn, ws)
    conn.execute("UPDATE workspaces SET demo_now = ? WHERE id = ?", (demo_now.isoformat() if demo_now else None, ws))


def get_demo_now(conn: sqlite3.Connection, ws: str) -> datetime | None:
    row = conn.execute("SELECT demo_now FROM workspaces WHERE id = ?", (ws,)).fetchone()
    return datetime.fromisoformat(row["demo_now"]) if row and row["demo_now"] else None


def reset_workspace(conn: sqlite3.Connection, ws: str) -> None:
    for table in ("sources", "candidates", "tasks", "time_slots", "plans", "progress", "llm_log", "locks", "settings", "drafts",
                  "files", "activity"):
        conn.execute(f"DELETE FROM {table} WHERE workspace_id = ?", (ws,))
    conn.execute("UPDATE workspaces SET demo_now = NULL WHERE id = ?", (ws,))


# ---- sources --------------------------------------------------------------------------------
def upsert_source(conn: sqlite3.Connection, ws: str, source: Source) -> ImportStatus:
    """Store a source. Same record and same content -> duplicate; same record, new content -> new version."""
    ensure_workspace(conn, ws)
    digest = content_hash(source)
    rows = conn.execute(
        "SELECT version, content_hash FROM sources WHERE workspace_id = ? AND record_id = ? ORDER BY version",
        (ws, source.record_id),
    ).fetchall()
    if any(r["content_hash"] == digest for r in rows):
        return "duplicate"
    version = (rows[-1]["version"] + 1) if rows else 1
    conn.execute(
        """INSERT INTO sources (workspace_id, record_id, version, source_type, course_code, subject, sender,
                                received_at, body_text, meta, content_hash, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            ws, source.record_id, version, source.source_type, source.course_code, source.subject, source.sender,
            source.received_at.isoformat() if source.received_at else None, source.body_text,
            json.dumps(source.meta, ensure_ascii=False), digest, _ts(),
        ),
    )
    return "updated" if rows else "added"


def _row_to_source(row: sqlite3.Row) -> Source:
    return Source(
        record_id=row["record_id"],
        source_type=row["source_type"],
        course_code=row["course_code"],
        subject=row["subject"],
        sender=row["sender"],
        received_at=datetime.fromisoformat(row["received_at"]) if row["received_at"] else None,
        body_text=row["body_text"],
        meta={**json.loads(row["meta"]), "version": row["version"]},
    )


def list_sources(conn: sqlite3.Connection, ws: str, record_ids: Iterable[str] | None = None) -> list[Source]:
    """Latest version of each source, oldest message first."""
    rows = conn.execute(
        """SELECT s.* FROM sources s
           JOIN (SELECT record_id, MAX(version) AS v FROM sources WHERE workspace_id = ? GROUP BY record_id) latest
             ON s.record_id = latest.record_id AND s.version = latest.v
           WHERE s.workspace_id = ?
           ORDER BY COALESCE(s.received_at, s.created_at), s.record_id""",
        (ws, ws),
    ).fetchall()
    sources = [_row_to_source(r) for r in rows]
    if record_ids is not None:
        wanted = set(record_ids)
        sources = [s for s in sources if s.record_id in wanted]
    return sources


# ---- candidates -----------------------------------------------------------------------------
def save_candidates(conn: sqlite3.Connection, ws: str, candidates: Iterable[Candidate]) -> None:
    """Insert or refresh candidates. A candidate the student already handled keeps its status."""
    for c in candidates:
        existing = conn.execute(
            "SELECT status FROM candidates WHERE workspace_id = ? AND candidate_id = ?", (ws, c.candidate_id)
        ).fetchone()
        if existing and existing["status"] != "pending":
            continue
        conn.execute(
            """INSERT OR REPLACE INTO candidates (workspace_id, candidate_id, body, status, created_at)
               VALUES (?, ?, ?, 'pending', ?)""",
            (ws, c.candidate_id, c.model_dump_json(), _ts()),
        )


def list_candidates(conn: sqlite3.Connection, ws: str, status: str | None = None) -> list[Candidate]:
    sql = "SELECT body, status FROM candidates WHERE workspace_id = ?"
    args: list[str] = [ws]
    if status:
        sql += " AND status = ?"
        args.append(status)
    rows = conn.execute(sql + " ORDER BY created_at, candidate_id", args).fetchall()
    out = []
    for r in rows:
        c = Candidate.model_validate_json(r["body"])
        c.status = r["status"]
        out.append(c)
    return out


def get_candidate(conn: sqlite3.Connection, ws: str, candidate_id: str) -> Candidate | None:
    r = conn.execute(
        "SELECT body, status FROM candidates WHERE workspace_id = ? AND candidate_id = ?", (ws, candidate_id)
    ).fetchone()
    if not r:
        return None
    c = Candidate.model_validate_json(r["body"])
    c.status = r["status"]
    return c


def set_candidate_status(conn: sqlite3.Connection, ws: str, candidate_id: str, status: str) -> None:
    conn.execute(
        "UPDATE candidates SET status = ? WHERE workspace_id = ? AND candidate_id = ?", (status, ws, candidate_id)
    )


# ---- tasks ----------------------------------------------------------------------------------
def save_task(conn: sqlite3.Connection, ws: str, task: Task) -> None:
    ensure_workspace(conn, ws)
    conn.execute(
        "INSERT OR REPLACE INTO tasks (workspace_id, task_id, body, updated_at) VALUES (?, ?, ?, ?)",
        (ws, task.task_id, task.model_dump_json(), _ts()),
    )


def list_tasks(conn: sqlite3.Connection, ws: str) -> list[Task]:
    rows = conn.execute("SELECT body FROM tasks WHERE workspace_id = ? ORDER BY task_id", (ws,)).fetchall()
    return sorted((Task.model_validate_json(r["body"]) for r in rows), key=lambda t: (t.due_at, t.task_id))


def delete_task(conn: sqlite3.Connection, ws: str, task_id: str) -> None:
    conn.execute("DELETE FROM tasks WHERE workspace_id = ? AND task_id = ?", (ws, task_id))
    conn.execute("DELETE FROM locks WHERE workspace_id = ? AND task_id = ?", (ws, task_id))


def get_task(conn: sqlite3.Connection, ws: str, task_id: str) -> Task | None:
    r = conn.execute("SELECT body FROM tasks WHERE workspace_id = ? AND task_id = ?", (ws, task_id)).fetchone()
    return Task.model_validate_json(r["body"]) if r else None


# ---- time slots -----------------------------------------------------------------------------
def replace_time_slots(conn: sqlite3.Connection, ws: str, slots: Iterable[TimeSlot]) -> None:
    ensure_workspace(conn, ws)
    conn.execute("DELETE FROM time_slots WHERE workspace_id = ?", (ws,))
    rows = []
    for s in slots:
        if not s.slot_id:
            s = s.model_copy(update={"slot_id": uuid.uuid4().hex[:10]})
        rows.append((ws, s.model_dump_json()))
    conn.executemany("INSERT INTO time_slots (workspace_id, body) VALUES (?, ?)", rows)


def list_time_slots(conn: sqlite3.Connection, ws: str) -> list[TimeSlot]:
    rows = conn.execute("SELECT body FROM time_slots WHERE workspace_id = ?", (ws,)).fetchall()
    return sorted((TimeSlot.model_validate_json(r["body"]) for r in rows), key=lambda s: s.start)


# ---- progress -------------------------------------------------------------------------------
def add_progress(conn: sqlite3.Connection, ws: str, progress: Progress) -> bool:
    """Record completed work. Returns False when this op_id was already recorded (no double counting)."""
    ensure_workspace(conn, ws)
    cur = conn.execute(
        "INSERT OR IGNORE INTO progress (workspace_id, op_id, body, created_at) VALUES (?, ?, ?, ?)",
        (ws, progress.op_id, progress.model_dump_json(), _ts()),
    )
    return cur.rowcount == 1


def list_progress(conn: sqlite3.Connection, ws: str) -> list[Progress]:
    rows = conn.execute("SELECT body FROM progress WHERE workspace_id = ? ORDER BY created_at", (ws,)).fetchall()
    return [Progress.model_validate_json(r["body"]) for r in rows]


# ---- plans ----------------------------------------------------------------------------------
def input_version(conn: sqlite3.Connection, ws: str, settings: PlanSettings) -> str:
    """Fingerprint of everything a plan depends on. If it changes, a draft is stale."""
    payload = {
        "tasks": [t.model_dump(mode="json") for t in list_tasks(conn, ws)],
        "slots": [s.model_dump(mode="json", exclude={"slot_id"}) for s in list_time_slots(conn, ws)],
        "progress": [p.model_dump(mode="json") for p in list_progress(conn, ws)],
        "settings": settings.model_dump(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def save_plan(
    conn: sqlite3.Connection, ws: str, plan_id: str, based_on: str, request: PlanRequest, result: PlanResult
) -> None:
    ensure_workspace(conn, ws)
    conn.execute(
        """INSERT INTO plans (workspace_id, plan_id, status, based_on, request, result, created_at)
           VALUES (?, ?, 'draft', ?, ?, ?, ?)""",
        (ws, plan_id, based_on, request.model_dump_json(), result.model_dump_json(), _ts()),
    )


def get_plan(conn: sqlite3.Connection, ws: str, plan_id: str) -> dict | None:
    r = conn.execute("SELECT * FROM plans WHERE workspace_id = ? AND plan_id = ?", (ws, plan_id)).fetchone()
    return _plan_row(r) if r else None


def get_adopted_plan(conn: sqlite3.Connection, ws: str) -> dict | None:
    r = conn.execute(
        "SELECT * FROM plans WHERE workspace_id = ? AND status = 'adopted' ORDER BY adopted_at DESC LIMIT 1", (ws,)
    ).fetchone()
    return _plan_row(r) if r else None


def adopt_plan(conn: sqlite3.Connection, ws: str, plan_id: str) -> None:
    """Replace the adopted plan in one transaction (the caller's connection commits or rolls back)."""
    conn.execute("UPDATE plans SET status = 'superseded' WHERE workspace_id = ? AND status = 'adopted'", (ws,))
    conn.execute(
        "UPDATE plans SET status = 'adopted', adopted_at = ? WHERE workspace_id = ? AND plan_id = ?",
        (_ts(), ws, plan_id),
    )


def _plan_row(r: sqlite3.Row) -> dict:
    return {
        "plan_id": r["plan_id"],
        "status": r["status"],
        "based_on": r["based_on"],
        "request": PlanRequest.model_validate_json(r["request"]),
        "result": PlanResult.model_validate_json(r["result"]),
        "created_at": r["created_at"],
        "adopted_at": r["adopted_at"],
    }


# ---- llm log --------------------------------------------------------------------------------
def log_llm_call(conn: sqlite3.Connection, ws: str, provider: str, purpose: str, sent_text: str) -> None:
    conn.execute(
        "INSERT INTO llm_log (workspace_id, provider, purpose, sent_text, created_at) VALUES (?, ?, ?, ?, ?)",
        (ws, provider, purpose, sent_text, _ts()),
    )


# ---- locks ----------------------------------------------------------------------------------
def list_locks(conn: sqlite3.Connection, ws: str) -> list[PlanBlock]:
    rows = conn.execute("SELECT task_id, start, end FROM locks WHERE workspace_id = ? ORDER BY start", (ws,)).fetchall()
    return [PlanBlock(task_id=r["task_id"], start=datetime.fromisoformat(r["start"]), end=datetime.fromisoformat(r["end"])) for r in rows]


def set_lock(conn: sqlite3.Connection, ws: str, block: PlanBlock, locked: bool) -> None:
    conn.execute("DELETE FROM locks WHERE workspace_id = ? AND task_id = ? AND start = ?", (ws, block.task_id, block.start.isoformat()))
    if locked:
        conn.execute("INSERT INTO locks (workspace_id, task_id, start, end) VALUES (?, ?, ?, ?)",
                     (ws, block.task_id, block.start.isoformat(), block.end.isoformat()))


# ---- settings -------------------------------------------------------------------------------
def get_setting(conn: sqlite3.Connection, ws: str, key: str, default=None):
    row = conn.execute("SELECT value FROM settings WHERE workspace_id = ? AND key = ?", (ws, key)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(conn: sqlite3.Connection, ws: str, key: str, value) -> None:
    ensure_workspace(conn, ws)
    conn.execute("INSERT OR REPLACE INTO settings (workspace_id, key, value) VALUES (?, ?, ?)",
                 (ws, key, json.dumps(value, ensure_ascii=False)))


# ---- drafts ---------------------------------------------------------------------------------
def get_draft(conn: sqlite3.Connection, ws: str, record_id: str) -> dict | None:
    row = conn.execute("SELECT body, status FROM drafts WHERE workspace_id = ? AND record_id = ?", (ws, record_id)).fetchone()
    return {**json.loads(row["body"]), "status": row["status"]} if row else None


def save_draft(conn: sqlite3.Connection, ws: str, record_id: str, body: dict, status: str = "draft") -> None:
    ensure_workspace(conn, ws)
    conn.execute("INSERT OR REPLACE INTO drafts (workspace_id, record_id, body, status, updated_at) VALUES (?, ?, ?, ?, ?)",
                 (ws, record_id, json.dumps(body, ensure_ascii=False), status, _ts()))


def list_llm_log(conn: sqlite3.Connection, ws: str) -> list[dict]:
    rows = conn.execute("SELECT provider, purpose, sent_text, created_at FROM llm_log WHERE workspace_id = ? ORDER BY rowid DESC",
                        (ws,)).fetchall()
    return [dict(r) for r in rows]


# ---- original files -------------------------------------------------------------------------
def save_file(conn: sqlite3.Connection, ws: str, f: dict, created_at: str | None = None) -> None:
    ensure_workspace(conn, ws)
    conn.execute(
        """INSERT OR REPLACE INTO files (workspace_id, file_id, record_id, filename, content_type, size, data, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (ws, f["file_id"], f.get("record_id"), f["filename"], f["content_type"], len(f["data"]), f["data"], created_at or _ts()),
    )


def get_file(conn: sqlite3.Connection, ws: str, file_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM files WHERE workspace_id = ? AND file_id = ?", (ws, file_id)).fetchone()
    return dict(row) if row else None


def list_files(conn: sqlite3.Connection, ws: str) -> list[dict]:
    rows = conn.execute(
        "SELECT file_id, record_id, filename, content_type, size, created_at FROM files WHERE workspace_id = ? ORDER BY created_at DESC",
        (ws,),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_source(conn: sqlite3.Connection, ws: str, record_id: str) -> bool:
    """Forget a message or file: its versions, its stored original, and pending candidates found only in it."""
    cur = conn.execute("DELETE FROM sources WHERE workspace_id = ? AND record_id = ?", (ws, record_id))
    conn.execute("DELETE FROM files WHERE workspace_id = ? AND record_id = ?", (ws, record_id))
    conn.execute("DELETE FROM drafts WHERE workspace_id = ? AND record_id = ?", (ws, record_id))
    for c in list_candidates(conn, ws, "pending"):
        if set(c.source_ids) <= {record_id}:
            conn.execute("DELETE FROM candidates WHERE workspace_id = ? AND candidate_id = ?", (ws, c.candidate_id))
    return cur.rowcount > 0


# ---- activity log ---------------------------------------------------------------------------
def log_activity(conn: sqlite3.Connection, ws: str, kind: str, label: str, detail: dict | None = None) -> None:
    ensure_workspace(conn, ws)
    demo = get_demo_now(conn, ws)  # a demo workspace lives on its fixed clock, so its log reads consistently
    stamp = demo.isoformat(timespec="seconds") if demo else _ts()
    conn.execute("INSERT INTO activity (workspace_id, kind, label, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                 (ws, kind, label, json.dumps(detail or {}, ensure_ascii=False), stamp))


def list_activity(conn: sqlite3.Connection, ws: str, limit: int = 30) -> list[dict]:
    rows = conn.execute("SELECT kind, label, detail, created_at FROM activity WHERE workspace_id = ? ORDER BY rowid DESC LIMIT ?",
                        (ws, limit)).fetchall()
    return [{"kind": r["kind"], "label": r["label"], "detail": json.loads(r["detail"]), "created_at": r["created_at"]} for r in rows]
