"""SQLite connection and schema. One file, no server; every row belongs to a workspace.

A workspace is one student's data. Locally there is a single workspace ("local"); the hosted demo gives
each visitor their own workspace so demo sessions do not see each other.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workspaces (
    id         TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    demo_now   TEXT              -- fixed clock for demo workspaces, NULL means real time
);

-- original messages, never modified; a changed message with the same record_id becomes a new version
CREATE TABLE IF NOT EXISTS sources (
    rowid        INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    record_id    TEXT NOT NULL,
    version      INTEGER NOT NULL DEFAULT 1,
    source_type  TEXT NOT NULL,
    course_code  TEXT,
    subject      TEXT,
    sender       TEXT,
    received_at  TEXT,
    body_text    TEXT NOT NULL,
    meta         TEXT NOT NULL DEFAULT '{}',
    content_hash TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    UNIQUE (workspace_id, record_id, version)
);

CREATE TABLE IF NOT EXISTS candidates (
    workspace_id    TEXT NOT NULL,
    candidate_id    TEXT NOT NULL,
    body            TEXT NOT NULL,   -- Candidate as JSON
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    PRIMARY KEY (workspace_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    workspace_id TEXT NOT NULL,
    task_id      TEXT NOT NULL,
    body         TEXT NOT NULL,      -- Task as JSON
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, task_id)
);

CREATE TABLE IF NOT EXISTS time_slots (
    rowid        INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    body         TEXT NOT NULL       -- TimeSlot as JSON
);

CREATE TABLE IF NOT EXISTS plans (
    workspace_id TEXT NOT NULL,
    plan_id      TEXT NOT NULL,
    status       TEXT NOT NULL,      -- draft | adopted | superseded
    based_on     TEXT NOT NULL,      -- hash of the inputs the draft was generated from
    request      TEXT NOT NULL,      -- PlanRequest as JSON
    result       TEXT NOT NULL,      -- PlanResult as JSON
    created_at   TEXT NOT NULL,
    adopted_at   TEXT,
    PRIMARY KEY (workspace_id, plan_id)
);

CREATE TABLE IF NOT EXISTS progress (
    workspace_id TEXT NOT NULL,
    op_id        TEXT NOT NULL,
    body         TEXT NOT NULL,      -- Progress as JSON
    created_at   TEXT NOT NULL,
    PRIMARY KEY (workspace_id, op_id)
);

-- what left the computer: every model call, with the cleaned text that was sent
CREATE TABLE IF NOT EXISTS llm_log (
    rowid        INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    provider     TEXT NOT NULL,
    purpose      TEXT NOT NULL,
    sent_text    TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
            )

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
