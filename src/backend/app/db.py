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
