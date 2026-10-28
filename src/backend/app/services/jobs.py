"""Persistent job records + an in-process runner (FastAPI background tasks are not durable).

On restart, queued/running jobs are marked 'interrupted' (see db.init_db); the user retries.
"""
from __future__ import annotations

import sqlite3
import traceback
from typing import Callable

from ..db import connect, dumps, loads, new_id, now_iso, transaction


class Cancelled(Exception):
    pass


def job_view(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"], "kind": row["kind"], "status": row["status"], "processed": row["processed"],
        "total": row["total"], "failed_count": row["failed_count"], "cancel_requested": bool(row["cancel_requested"]),
        "errors": loads(row["errors_json"], []), "result": loads(row["checkpoint_json"], {}).get("result"),
    }


def create_job(conn: sqlite3.Connection, kind: str, payload: dict, connection_id: str | None = None) -> dict:
    jid, ts = new_id("job"), now_iso()
    conn.execute(
        "INSERT INTO jobs(id,connection_id,kind,status,input_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
        (jid, connection_id, kind, "queued", dumps(payload), ts, ts),
    )
    return job_view(conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone())


class JobContext:
    def __init__(self, conn: sqlite3.Connection, job_id: str):
        self.conn, self.job_id = conn, job_id

    def progress(self, processed: int, total: int | None = None, failed: int | None = None) -> None:
        self.conn.execute(
            "UPDATE jobs SET processed=?, total=COALESCE(?, total), failed_count=COALESCE(?, failed_count), updated_at=? WHERE id=?",
            (processed, total, failed, now_iso(), self.job_id))
        if self.conn.execute("SELECT cancel_requested FROM jobs WHERE id=?", (self.job_id,)).fetchone()[0]:
            raise Cancelled()

    def error(self, message: str) -> None:
        row = self.conn.execute("SELECT errors_json FROM jobs WHERE id=?", (self.job_id,)).fetchone()
        errs = loads(row[0], [])[-49:] + [message[:300]]
        self.conn.execute("UPDATE jobs SET errors_json=? WHERE id=?", (dumps(errs), self.job_id))


def run_job(job_id: str, fn: Callable[[JobContext, dict], dict], atomic: bool = True) -> None:
    """atomic=True: one write transaction (local imports). Network jobs pass atomic=False and
    commit per item so no write lock is held during provider/model calls."""
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["status"] != "queued":
            return
        conn.execute("UPDATE jobs SET status='running', updated_at=? WHERE id=?", (now_iso(), job_id))
        ctx = JobContext(conn, job_id)
        try:
            if atomic:
                with transaction(conn):
                    result = fn(ctx, loads(row["input_json"], {}))
            else:
                result = fn(ctx, loads(row["input_json"], {}))
            failed = conn.execute("SELECT failed_count FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
            status = "partial" if failed else "completed"
            conn.execute("UPDATE jobs SET status=?, checkpoint_json=?, updated_at=? WHERE id=?",
                         (status, dumps({"result": result}), now_iso(), job_id))
        except Cancelled:
            conn.execute("UPDATE jobs SET status='cancelled', updated_at=? WHERE id=?", (now_iso(), job_id))
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed silently
            ctx.error(f"{type(exc).__name__}: {exc}")
            conn.execute("UPDATE jobs SET status='failed', updated_at=? WHERE id=?", (now_iso(), job_id))
            traceback.print_exc()
