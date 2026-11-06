"""SQLite access: one short-lived connection per unit of work, short write transactions."""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import settings

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def loads(raw: str | None, default: Any = None) -> Any:
    if raw is None or raw == "":
        return default
    return json.loads(raw)


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


EXTRA_TABLES = """
CREATE TABLE IF NOT EXISTS study_checkins (
  block_key TEXT PRIMARY KEY, task_id TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK(outcome IN ('done','partial','missed')),
  minutes INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS estimate_decisions (
  task_id TEXT PRIMARY KEY, decision TEXT NOT NULL CHECK(decision IN ('accepted','kept')),
  from_minutes INTEGER, to_minutes INTEGER, ratio REAL, basis TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS demo_busy (
  id TEXT PRIMARY KEY, start_at TEXT NOT NULL, end_at TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
"""


def init_db(path: Path | None = None) -> None:
    path = path or settings.database_path
    conn = _connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < SCHEMA_VERSION:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        # Additive column migrations for databases created by earlier builds.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(tasks)")}
        if cols and "title_en" not in cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN title_en TEXT")
        if cols and "first_estimate_minutes" not in cols:  # the student's own first estimate, for calibration
            conn.execute("ALTER TABLE tasks ADD COLUMN first_estimate_minutes INTEGER")
            conn.execute("UPDATE tasks SET first_estimate_minutes=estimated_minutes WHERE estimated_minutes > 0")
        if cols and "actual_minutes" not in cols:  # what a finished task really took, as the student says
            conn.execute("ALTER TABLE tasks ADD COLUMN actual_minutes INTEGER")
        # Tables added after the first release (CREATE IF NOT EXISTS is safe to repeat).
        conn.executescript(EXTRA_TABLES)
        ck_cols = {r[1] for r in conn.execute("PRAGMA table_info(study_checkins)")}
        if "planned_minutes" not in ck_cols:  # how long the answered block was meant to be
            conn.execute("ALTER TABLE study_checkins ADD COLUMN planned_minutes INTEGER")
        snap_cols = {r[1] for r in conn.execute("PRAGMA table_info(calendar_snapshots)")}
        if snap_cols and "extras_json" not in snap_cols:  # whether the app's study calendar was read too
            conn.execute("ALTER TABLE calendar_snapshots ADD COLUMN extras_json TEXT NOT NULL DEFAULT '{}'")
        # Startup recovery: anything mid-flight when the process died is not "done".
        ts = now_iso()
        conn.execute("UPDATE jobs SET status='interrupted', updated_at=? WHERE status IN ('queued','running')", (ts,))
        conn.execute(
            "UPDATE proposals SET status='unknown', updated_at=?, result_json=? WHERE status='executing'",
            (ts, dumps({"reason": "process_restarted_during_execution", "action": "verify_remote_state_before_retry"})),
        )
    finally:
        conn.close()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = _connect(settings.database_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def audit(conn: sqlite3.Connection, event_type: str, object_type: str, object_id: str | None,
          summary: dict | None = None) -> None:
    """Audit rows hold IDs/states only - never bodies, keys or tokens."""
    conn.execute(
        "INSERT INTO audit_events(id,event_type,object_type,object_id,summary_json,created_at) VALUES(?,?,?,?,?,?)",
        (new_id("aud"), event_type, object_type, object_id, dumps(summary or {}), now_iso()),
    )
