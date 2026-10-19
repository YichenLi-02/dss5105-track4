"""Calendar snapshots, plan preview / replan, and group discussion summaries."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ..db import connect, transaction
from ..security import Session, require_mutation, require_session
from ..services import chat_service, plan_service

router = APIRouter(prefix="/api")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SnapshotIn(Strict):
    provider: Literal["mock", "google", "microsoft"]
    connection_id: str | None = None
    time_min: str
    time_max: str
    calendar_ids: list[str] = []
    display_timezone: str = "Asia/Singapore"


@router.post("/calendar/snapshots", status_code=201)
def snapshot(body: SnapshotIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return plan_service.create_snapshot(conn, body.model_dump())


class PreviewIn(Strict):
    task_ids: list[str]
    snapshot_id: str
    preferences_revision: int


@router.post("/plans/preview", status_code=201)
def preview(body: PreviewIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return plan_service.build_plan(conn, body.task_ids, body.snapshot_id, body.preferences_revision)


@router.get("/plans/latest")
def latest(_: Session = Depends(require_session)):
    with connect() as conn:
        row = conn.execute("SELECT id FROM plans ORDER BY created_at DESC, rowid DESC LIMIT 1").fetchone()
        return plan_service.get_plan(conn, row[0]) if row else None


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, _: Session = Depends(require_session)):
    with connect() as conn:
        return plan_service.get_plan(conn, plan_id)


class ReplanIn(Strict):
    expected_revision: int
    snapshot_id: str
    preferences_revision: int


@router.post("/plans/{plan_id}/replan", status_code=201)
def replan(plan_id: str, body: ReplanIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return plan_service.replan(conn, plan_id, body.model_dump())


class ScenarioIn(Strict):
    effort_minutes: int = 360


@router.post("/demo/planning-scenario", status_code=201)
def scenario(body: ScenarioIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return plan_service.load_synthetic_scenario(conn, body.effort_minutes)


class ChatLine(Strict):
    source_id: str
    speaker: str | None
    timestamp: str | None
    text: str


class ChatIn(Strict):
    messages: list[ChatLine] = []
    raw_text: str | None = None
    title: str | None = None
    synthetic: bool = False


@router.post("/chat-summaries", status_code=201)
def summarize(body: ChatIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return chat_service.create_summary(conn, body.model_dump())


@router.get("/demo/chat")
def demo_chat(_: Session = Depends(require_session)):
    return {"raw_text": chat_service.SYNTHETIC_CHAT, "synthetic": True}
