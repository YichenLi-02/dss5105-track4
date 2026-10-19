from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ..db import connect, transaction
from ..security import Session, require_mutation, require_session
from ..services import preferences, task_service

router = APIRouter(prefix="/api")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.get("/tasks")
def list_tasks(status: str | None = None, _: Session = Depends(require_session)):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY COALESCE(official_date, '9999'), title").fetchall()
        items = [task_service.row_to_task(conn, r) for r in rows]
        if not preferences.show_demo_data(conn):
            # Hide tasks that come only from sample mail or synthetic fixtures.
            real = {r[0] for r in conn.execute(
                "SELECT DISTINCT e.task_id FROM task_evidence e JOIN messages m ON m.id=e.message_id "
                "WHERE m.connection_id NOT IN ('conn_local_jsonl')").fetchall()}
            items = [t for t in items if t["id"] in real and not t["entity_key"].startswith("synthetic_")]
        if status:
            wanted = set(status.split(","))
            items = [t for t in items if t["status"] in wanted]
        counts: dict[str, int] = {}
        for t in items:
            counts[t["status"]] = counts.get(t["status"], 0) + 1
        return {"items": items, "next_cursor": None, "total": len(items), "counts": counts}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, _: Session = Depends(require_session)):
    with connect() as conn:
        return task_service.get_task(conn, task_id)


class TaskCreate(Strict):
    title: str
    source_id: str | None = None
    evidence_quote: str | None = None
    course: str | None = None
    term: str | None = None


@router.post("/tasks", status_code=201)
def create_task(body: TaskCreate, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return task_service.create_manual_task(conn, body.model_dump())


class TaskPatch(Strict):
    expected_revision: int
    required: bool | None = None
    official_date: str | None = None
    official_time: str | None = None
    source_timezone: str | None = None
    user_planning_cutoff: str | None = None
    estimated_minutes: int | None = None
    status: Literal["needs_review", "confirmed", "in_progress", "completed", "ignored"] | None = None
    title: str | None = None
    course: str | None = None
    term: str | None = None


@router.patch("/tasks/{task_id}")
def patch_task(task_id: str, body: TaskPatch, _: Session = Depends(require_mutation)):
    # exclude_unset keeps explicit nulls (e.g. clearing a planning cutoff) distinct from "not sent".
    with connect() as conn, transaction(conn):
        return task_service.update_task(conn, task_id, body.model_dump(exclude_unset=True))


class ProgressIn(Strict):
    expected_revision: int
    client_event_id: str
    minutes: int
    occurred_at: str
    undo_of: str | None = None


@router.post("/tasks/{task_id}/progress")
def progress(task_id: str, body: ProgressIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return task_service.record_progress(conn, task_id, body.model_dump())
