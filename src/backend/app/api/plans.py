"""Calendar snapshots, plan preview / replan, and group discussion summaries."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from ..db import connect, transaction
from ..errors import AppError
from ..security import Session, require_mutation, require_session
from ..services import calibration_service, chat_service, plan_service

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
        pid = plan_service.latest_plan_id(conn)
        return plan_service.get_plan(conn, pid) if pid else None


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


class SnapshotRef(Strict):
    snapshot_id: str


@router.post("/plans/{plan_id}/fresh-snapshot", status_code=201)
def fresh_snapshot(plan_id: str, _: Session = Depends(require_mutation)):
    """Re-read the same calendars over the same days as the plan (read-only towards the calendar)."""
    with connect() as conn, transaction(conn):
        return plan_service.fresh_snapshot(conn, plan_id)


@router.post("/plans/{plan_id}/conflicts")
def conflicts(plan_id: str, body: SnapshotRef, _: Session = Depends(require_mutation)):
    """Read-only check of a plan against a fresh calendar snapshot."""
    with connect() as conn:
        return plan_service.check_conflicts(conn, plan_id, body.snapshot_id)


class RepairIn(Strict):
    snapshot_id: str
    preferences_revision: int


@router.post("/plans/{plan_id}/repair-options", status_code=201)
def repair_options(plan_id: str, body: RepairIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return plan_service.repair_options(conn, plan_id, body.snapshot_id, body.preferences_revision)


class AdoptIn(Strict):
    expected_revision: int


@router.post("/plans/{plan_id}/adopt")
def adopt(plan_id: str, body: AdoptIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return plan_service.adopt_option(conn, plan_id, body.expected_revision)


class EditIn(Strict):
    expected_revision: int
    snapshot_id: str
    preferences_revision: int
    task_id: str
    start: str
    new_start: str | None = None
    minutes: int | None = None
    remove: bool = False
    unlock: bool = False
    acknowledge: list[str] = []


@router.post("/plans/{plan_id}/edit-block", status_code=201)
def edit_block(plan_id: str, body: EditIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return plan_service.edit_block(conn, plan_id, body.model_dump())


@router.get("/study-checkins")
def checkins(_: Session = Depends(require_session)):
    with connect() as conn:
        items = plan_service.pending_checkins(conn)
        return {"items": items, "total": len(items)}


class CheckinIn(Strict):
    key: str
    outcome: Literal["done", "partial", "missed"]
    minutes: int | None = None


@router.post("/study-checkins")
def checkin(body: CheckinIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return plan_service.record_checkin(conn, body.model_dump())


class DemoMeetingIn(Strict):
    start: str
    minutes: int = 60
    label: str | None = None


@router.get("/demo/busy")
def demo_busy(_: Session = Depends(require_session)):
    with connect() as conn:
        return {"items": plan_service.demo_meetings(conn)}


@router.post("/demo/busy", status_code=201)
def add_demo_busy(body: DemoMeetingIn, _: Session = Depends(require_mutation)):
    if not 5 <= body.minutes <= 600:
        raise AppError(422, "VALIDATION_FAILED", "minutes must be 5-600")
    with connect() as conn, transaction(conn):
        return plan_service.add_demo_meeting(conn, body.model_dump())


@router.delete("/demo/busy")
def clear_demo_busy(_: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return plan_service.clear_demo_meetings(conn)


class DecideIn(Strict):
    task_id: str
    expected_revision: int
    decision: Literal["accept", "keep"]


class OverrunIn(Strict):
    task_id: str
    expected_revision: int
    finished: bool
    more_minutes: int | None = None


@router.get("/calibration")
def calibration(_: Session = Depends(require_session)):
    """Estimate suggestions from finished tasks, overrun questions and the check-in completion rate (read-only)."""
    with connect() as conn:
        return calibration_service.overview(conn)


@router.post("/calibration/decide")
def calibration_decide(body: DecideIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return calibration_service.decide(conn, body.model_dump())


@router.post("/calibration/overrun")
def calibration_overrun(body: OverrunIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return calibration_service.answer_overrun(conn, body.model_dump())


@router.post("/demo/calibration-history", status_code=201)
def demo_calibration_history(_: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return calibration_service.load_demo_history(conn)


@router.delete("/demo/calibration-history")
def clear_demo_calibration_history(_: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return calibration_service.clear_demo_history(conn)


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
