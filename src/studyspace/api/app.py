"""HTTP API and orchestration (member 5's area). The only layer that touches the database.

Every response has the same envelope: {"ok": true, "data": ...} or {"ok": false, "error": {"code", "message"}}.
The X-Workspace header picks whose data a request works on (default "local"); the hosted demo gives each
visitor a separate workspace. The web front end in ../web is served from "/".
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, Field

from .. import __version__
from ..academic_calendar import AcademicCalendar
from ..config import Settings, load_settings
from ..drafts import Draft, draft_reply, learn_style
from ..extraction import extract
from ..ingest import ImportResult, expand_template, parse_eml, parse_file, parse_ics, parse_text
from ..llm import Gateway, get_provider, prepare
from ..meetings import suggest_slots
from ..models import (
    MIDNIGHT_AMBIGUITY,
    STALE_DRAFT,
    Candidate,
    Interval,
    PlanBlock,
    PlanSettings,
    Priority,
    Progress,
    Task,
    TaskKind,
    TimeSlot,
)
from ..planner import build_request, check_plan, generate
from ..storage import Database, repo
from ..synthetic import DEMO_NOW, KNOWN_NAMES, build as build_synthetic
from ..synthetic.generator import SENT_SAMPLES, STUDENT
from ..timeutil import TZ, now as real_now
from ..triage import triage

WORKSPACE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
WEB_DIR = Path(__file__).resolve().parents[1] / "web"


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details: Any = None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details


def ok(data: Any) -> dict:
    return {"ok": True, "data": data, "error": None}


# ---- request bodies -------------------------------------------------------------------------
class TextImport(BaseModel):
    text: str
    subject: str | None = None
    course_code: str | None = None
    received_at: AwareDatetime | None = None


class ConfirmCandidate(BaseModel):
    """Gate 1: the student checks the task before it can be planned."""

    title: str | None = None
    due_at: AwareDatetime | None = None
    remaining_minutes: int | None = Field(default=None, ge=0)  # effort estimate; for an event, its length
    priority: Priority = "medium"
    kind: TaskKind | None = None


class TaskIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    course_code: str | None = None
    kind: TaskKind = "deliverable"
    due_at: AwareDatetime
    remaining_minutes: int = Field(ge=0)
    priority: Priority = "medium"


class TaskPatch(BaseModel):
    title: str | None = None
    due_at: AwareDatetime | None = None
    remaining_minutes: int | None = Field(default=None, ge=0)
    priority: Priority | None = None
    status: Literal["open", "done"] | None = None


class CalendarUpdate(BaseModel):
    slots: list[TimeSlot] = Field(default_factory=list)
    template: dict | None = None  # weekly free-time template, see ingest/availability.py


class BusyIn(BaseModel):
    start: AwareDatetime
    end: AwareDatetime
    label: str = "Meeting"


class SettingsIn(BaseModel):
    name: str | None = None
    email: str | None = None
    plan: PlanSettings | None = None


class DraftRequest(BaseModel):
    settings: PlanSettings | None = None


class AdoptRequest(BaseModel):
    based_on: str  # the draft's input version; adopting a stale draft is refused


class LockIn(BaseModel):
    task_id: str
    start: AwareDatetime
    end: AwareDatetime
    locked: bool = True


class ProgressIn(BaseModel):
    op_id: str = Field(min_length=1, max_length=100)
    task_id: str
    start: AwareDatetime
    end: AwareDatetime
    remaining_minutes: int | None = Field(default=None, ge=0)  # the student's new estimate, if they give one


class DraftEdit(BaseModel):
    subject: str | None = None
    body: str


class MeetingRequest(BaseModel):
    duration_minutes: int = Field(default=30, ge=15, le=240)
    start_date: date | None = None
    end_date: date | None = None
    window_start: str = "09:00"
    window_end: str = "21:00"
    weekdays_only: bool = False
    others_busy_ics: str | None = None  # other people's calendar export; only the times are used


class PrivacyPreview(BaseModel):
    text: str | None = None
    record_id: str | None = None


# ---- app ------------------------------------------------------------------------------------
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = Database(settings.db_path)
    calendar = AcademicCalendar.load(settings.calendar_path)
    provider = get_provider(settings.llm_provider)

    app = FastAPI(
        title="Studyspace API",
        version=__version__,
        description="Student productivity agent: messages in, confirmed tasks and a weekly plan out.",
    )

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"ok": False, "data": None, "error": {"code": exc.code, "message": exc.message, "details": exc.details}},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
        return JSONResponse(
            status_code=422,
            content={"ok": False, "data": None, "error": {"code": "INVALID_INPUT", "message": "request is not valid", "details": details}},
        )

    # -- helpers ----------------------------------------------------------------------------------
    def workspace(value: str | None) -> str:
        ws = value or "local"
        if not WORKSPACE_ID.match(ws):
            raise ApiError("INVALID_WORKSPACE", "X-Workspace may only contain letters, digits, '-' and '_'")
        return ws

    def clock(conn, ws: str) -> datetime:
        return repo.get_demo_now(conn, ws) or real_now()

    def profile(conn, ws: str) -> dict:
        return repo.get_setting(conn, ws, "profile", {"name": "Student", "email": None})

    def domain(conn, ws: str) -> str | None:
        email = profile(conn, ws).get("email") or ""
        return email.rsplit("@", 1)[-1].lower() if "@" in email else None

    def plan_settings(conn, ws: str) -> PlanSettings:
        return PlanSettings.model_validate(repo.get_setting(conn, ws, "plan_settings", {}))

    def gateway(conn, ws: str) -> Gateway:
        return Gateway(provider, log=lambda name, purpose, text: repo.log_llm_call(conn, ws, name, purpose, text))

    def known_names(conn, ws: str) -> list[str]:
        names = set(KNOWN_NAMES)
        me = profile(conn, ws).get("name")
        if me:
            names |= {me, me.split()[0]}
        for s in repo.list_sources(conn, ws):
            display, _ = parseaddr(s.sender or "")
            if display:
                names.add(re.sub(r"\s*\(.*?\)", "", display).replace("Prof. ", "").replace("Dr. ", "").strip())
        return sorted(n for n in names if n)

    def store_import(conn, ws: str, result: ImportResult) -> dict:
        counts = {"added": 0, "duplicate": 0, "updated": 0}
        for source in result.sources:
            counts[repo.upsert_source(conn, ws, source)] += 1
        if result.slots:
            # a new timetable replaces the previous one from the same kind of input
            incoming = {(s.origin, s.kind) for s in result.slots}
            kept = [s for s in repo.list_time_slots(conn, ws) if (s.origin, s.kind) not in incoming]
            repo.replace_time_slots(conn, ws, kept + result.slots)
        return {**counts, "slots": len(result.slots), "skipped": result.skipped}

    def run_extraction(conn, ws: str) -> list[Candidate]:
        candidates = extract(repo.list_sources(conn, ws), calendar, clock(conn, ws), repo.list_tasks(conn, ws))
        repo.save_candidates(conn, ws, candidates)
        return repo.list_candidates(conn, ws)

    def dump(items) -> list[dict]:
        return [i.model_dump(mode="json") for i in items]

    def find_source(conn, ws: str, record_id: str):
        found = repo.list_sources(conn, ws, [record_id])
        if not found:
            raise ApiError("NOT_FOUND", f"no source {record_id}", 404)
        return found[0]

    def busy_intervals(conn, ws: str) -> list[Interval]:
        """Classes, meetings and events: time nobody can plan over."""
        busy = [Interval(start=s.start, end=s.end) for s in repo.list_time_slots(conn, ws) if s.kind == "busy"]
        for t in repo.list_tasks(conn, ws):
            if t.kind == "event" and t.status == "open":
                busy.append(Interval(start=t.due_at, end=t.due_at + timedelta(minutes=t.remaining_minutes or 60)))
        return busy

    def current_plan_view(conn, ws: str) -> dict | None:
        plan = repo.get_adopted_plan(conn, ws)
        if plan is None:
            return None
        busy = busy_intervals(conn, ws)
        done = {(p.task_id, p.start.isoformat()) for p in repo.list_progress(conn, ws)}
        locks = repo.list_locks(conn, ws)
        locked = {(b.task_id, b.start.isoformat()) for b in locks}
        blocks = []
        for b in [*plan["result"].blocks, *plan["result"].retained_locked_blocks]:
            key = (b.task_id, b.start.isoformat())
            blocks.append({
                **b.model_dump(mode="json"),
                "locked": key in locked,
                "done": key in done,
                "conflict": any(b.start < x.end and x.start < b.end for x in busy),
            })
        blocks.sort(key=lambda b: b["start"])
        return {**_plan_json(plan), "blocks": blocks, "replan_reasons": replan_reasons(conn, ws, plan, blocks)}

    def replan_reasons(conn, ws: str, plan: dict, blocks: list[dict]) -> list[str]:
        """Why the saved plan may no longer fit. Finishing a session or locking one is not a reason."""
        now = clock(conn, ws)
        old = plan["request"]
        fresh = build_request(repo.list_tasks(conn, ws), repo.list_time_slots(conn, ws), now, settings=old.settings)
        reasons = []
        if any(b["conflict"] and not b["done"] and b["end"] > now.isoformat() for b in blocks):
            reasons.append("a planned session clashes with a class, meeting or exam")
        old_tasks = {t.id: t for t in old.tasks}
        for t in fresh.tasks:
            before = old_tasks.get(t.id)
            if before is None:
                reasons.append(f"new task: {t.title}")
            elif before.due_at != t.due_at:
                reasons.append(f"deadline changed: {t.title}")
            elif t.remaining_minutes > before.remaining_minutes:
                reasons.append(f"more work left than planned: {t.title}")

        def future(intervals) -> set:
            return {(i.start, i.end) for i in intervals if i.end > now}

        if future(fresh.availability) != future(old.availability) or future(fresh.busy) != future(old.busy):
            reasons.append("your available hours or fixed commitments changed")
        return reasons

    # -- system -----------------------------------------------------------------------------------
    @app.get("/api/health", tags=["system"])
    def health() -> dict:
        online = provider.name != "offline"
        return ok({"status": "ok", "version": __version__, "llm_provider": provider.name, "llm_online": online})

    @app.get("/api/workspace", tags=["system"])
    def get_workspace(x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            repo.ensure_workspace(conn, ws)
            adopted = repo.get_adopted_plan(conn, ws)
            return ok({
                "workspace": ws,
                "now": clock(conn, ws).isoformat(),
                "demo_clock": repo.get_demo_now(conn, ws) is not None,
                "profile": profile(conn, ws),
                "sources": len(repo.list_sources(conn, ws)),
                "candidates_pending": len(repo.list_candidates(conn, ws, "pending")),
                "tasks": len([t for t in repo.list_tasks(conn, ws) if t.status == "open"]),
                "time_slots": len(repo.list_time_slots(conn, ws)),
                "adopted_plan": adopted["plan_id"] if adopted else None,
                "llm_provider": provider.name,
            })

    @app.post("/api/workspace/reset", tags=["system"])
    def reset(x_workspace: str | None = Header(default=None)) -> dict:
        """Delete everything stored for this workspace on this computer."""
        ws = workspace(x_workspace)
        with db.connect() as conn:
            repo.reset_workspace(conn, ws)
        return ok({"workspace": ws, "reset": True})

    @app.get("/api/settings", tags=["system"])
    def get_settings(x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            return ok({**profile(conn, ws), "plan": plan_settings(conn, ws).model_dump()})

    @app.put("/api/settings", tags=["system"])
    def put_settings(body: SettingsIn, x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            prof = profile(conn, ws)
            if body.name is not None:
                prof["name"] = body.name
            if body.email is not None:
                prof["email"] = body.email
            repo.set_setting(conn, ws, "profile", prof)
            if body.plan is not None:
                repo.set_setting(conn, ws, "plan_settings", body.plan.model_dump())
            return ok({**prof, "plan": plan_settings(conn, ws).model_dump()})

    @app.post("/api/demo/load", tags=["system"])
    def load_demo(x_workspace: str | None = Header(default=None)) -> dict:
        """Replace this workspace's data with the synthetic student and set the clock to Mon 12 Oct 2026, 08:00."""
        ws = workspace(x_workspace)
        data = build_synthetic()
        result = ImportResult()
        for name, raw in data.emails:
            result.extend(parse_eml(raw, name))
        busy = parse_ics(data.timetable_ics)
        busy.slots = [s.model_copy(update={"origin": "synthetic"}) for s in busy.slots]
        result.extend(busy)
        result.slots.extend(expand_template(data.free_time, origin="synthetic"))
        with db.connect() as conn:
            repo.reset_workspace(conn, ws)
            repo.set_demo_now(conn, ws, DEMO_NOW)
            repo.set_setting(conn, ws, "profile", {"name": STUDENT[0], "email": STUDENT[1]})
            repo.set_setting(conn, ws, "sent_samples", [text for _, text in SENT_SAMPLES])
            summary = store_import(conn, ws, result)
            candidates = run_extraction(conn, ws)
        return ok({"workspace": ws, "now": DEMO_NOW.isoformat(), "import": summary, "candidates": len(candidates)})

    # -- input --------------------------------------------------------------------------------------
    @app.post("/api/import", tags=["input"])
    async def import_files(files: list[UploadFile] = File(...), x_workspace: str | None = Header(default=None)) -> dict:
        """Upload .eml / .csv (member 2's format) / .ics timetable / free-time .json / .txt files."""
        ws = workspace(x_workspace)
        report = []
        with db.connect() as conn:
            for f in files:
                raw = await f.read()
                try:
                    result = parse_file(f.filename or "upload", raw)
                except (ValueError, KeyError, UnicodeDecodeError) as exc:
                    report.append({"filename": f.filename, "error": f"could not read file: {exc}"})
                    continue
                report.append({"filename": f.filename, **store_import(conn, ws, result)})
        return ok({"files": report})

    @app.post("/api/import/text", tags=["input"])
    def import_text(body: TextImport, x_workspace: str | None = Header(default=None)) -> dict:
        """Pasted text: a forwarded email, a Teams or WhatsApp message, a line from a course page."""
        ws = workspace(x_workspace)
        with db.connect() as conn:
            result = parse_text(body.text, body.subject, body.course_code, body.received_at or clock(conn, ws))
            summary = store_import(conn, ws, result)
        return ok({**summary, "record_ids": [s.record_id for s in result.sources]})

    @app.get("/api/sources", tags=["input"])
    def sources(x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            return ok(dump(repo.list_sources(conn, ws)))

    @app.get("/api/sources/{record_id}", tags=["input"])
    def source(record_id: str, x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            return ok(find_source(conn, ws, record_id).model_dump(mode="json"))

    @app.get("/api/inbox", tags=["input"])
    def inbox(x_workspace: str | None = Header(default=None)) -> dict:
        """Messages, newest first, with what each one asks of the student."""
        ws = workspace(x_workspace)
        with db.connect() as conn:
            srcs = repo.list_sources(conn, ws)
            items = {t.record_id: t for t in triage(srcs, repo.list_candidates(conn, ws), domain(conn, ws), clock(conn, ws))}
            out = []
            for s in sorted(srcs, key=lambda x: (x.received_at is not None, x.received_at), reverse=True):
                t = items[s.record_id]
                draft = repo.get_draft(conn, ws, s.record_id)
                out.append({
                    "record_id": s.record_id, "subject": s.subject, "sender": s.sender, "course_code": s.course_code,
                    "received_at": s.received_at.isoformat() if s.received_at else None, "source_type": s.source_type,
                    "snippet": re.sub(r"\s+", " ", s.body_text)[:160], "labels": t.labels, "primary": t.primary,
                    "reasons": t.reasons, "candidate_ids": t.candidate_ids, "sender_kind": t.sender_kind, "urgent": t.urgent,
                    "draft_status": draft["status"] if draft else None,
                })
        return ok(out)

    # -- extraction and gate 1 -------------------------------------------------------------------
    @app.post("/api/extract", tags=["tasks"])
    def run_extract(x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            candidates = run_extraction(conn, ws)
        return ok({"mode": "offline-rules" if provider.name == "offline" else "model", "candidates": dump(candidates)})

    @app.get("/api/candidates", tags=["tasks"])
    def candidates(status: Literal["pending", "confirmed", "dismissed"] | None = None,
                   x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            return ok(dump(repo.list_candidates(conn, ws, status)))

    @app.post("/api/candidates/{candidate_id}/confirm", tags=["tasks"])
    def confirm(candidate_id: str, body: ConfirmCandidate, x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            c = repo.get_candidate(conn, ws, candidate_id)
            if c is None:
                raise ApiError("NOT_FOUND", f"no candidate {candidate_id}", 404)
            if c.status != "pending":
                raise ApiError("ALREADY_HANDLED", f"candidate is already {c.status}", 409)
            due_at = body.due_at or c.due_at
            if due_at is None or (MIDNIGHT_AMBIGUITY in c.flags and body.due_at is None):
                raise ApiError(
                    "NEEDS_DUE_AT",
                    "this task has no exact deadline yet; send due_at with the date and time you checked",
                    422,
                    {"due_text": c.due_text, "due_date": c.due_date.isoformat() if c.due_date else None,
                     "options": [o.isoformat() for o in c.due_options], "flags": c.flags},
                )
            kind = body.kind or c.kind
            existing = repo.get_task(conn, ws, c.related_task_id) if c.related_task_id else None
            minutes = body.remaining_minutes
            if minutes is None:
                if existing is not None:
                    minutes = existing.remaining_minutes
                elif kind == "event":
                    minutes = 60
                else:
                    raise ApiError("NEEDS_ESTIMATE", "send remaining_minutes: how long this task will take", 422)
            task = Task(
                task_id=existing.task_id if existing else "T-" + c.candidate_id.removeprefix("C-"),
                title=body.title or (existing.title if existing else c.title),
                course_code=c.course_code,
                kind=kind,
                due_at=due_at,
                remaining_minutes=minutes,
                priority=body.priority,
                source_ids=sorted(set(c.source_ids) | set(existing.source_ids if existing else [])),
            )
            repo.save_task(conn, ws, task)
            repo.set_candidate_status(conn, ws, candidate_id, "confirmed")
        return ok({"task": task.model_dump(mode="json"), "updated_existing": existing is not None})

    @app.post("/api/candidates/{candidate_id}/dismiss", tags=["tasks"])
    def dismiss(candidate_id: str, x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            if repo.get_candidate(conn, ws, candidate_id) is None:
                raise ApiError("NOT_FOUND", f"no candidate {candidate_id}", 404)
            repo.set_candidate_status(conn, ws, candidate_id, "dismissed")
        return ok({"candidate_id": candidate_id, "status": "dismissed"})

    @app.get("/api/tasks", tags=["tasks"])
    def tasks(x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            return ok(dump(repo.list_tasks(conn, ws)))

    @app.post("/api/tasks", tags=["tasks"])
    def add_task(body: TaskIn, x_workspace: str | None = Header(default=None)) -> dict:
        """A task the student adds by hand; it counts as confirmed."""
        ws = workspace(x_workspace)
        task = Task(task_id=f"T-M{uuid.uuid4().hex[:8]}", **body.model_dump())
        with db.connect() as conn:
            repo.save_task(conn, ws, task)
        return ok(task.model_dump(mode="json"))

    @app.patch("/api/tasks/{task_id}", tags=["tasks"])
    def patch_task(task_id: str, body: TaskPatch, x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            task = repo.get_task(conn, ws, task_id)
            if task is None:
                raise ApiError("NOT_FOUND", f"no task {task_id}", 404)
            task = task.model_copy(update=body.model_dump(exclude_none=True))
            repo.save_task(conn, ws, task)
        return ok(task.model_dump(mode="json"))

    # -- calendar ---------------------------------------------------------------------------------
    @app.get("/api/calendar", tags=["calendar"])
    def get_calendar(x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            return ok(dump(repo.list_time_slots(conn, ws)))

    @app.put("/api/calendar", tags=["calendar"])
    def put_calendar(body: CalendarUpdate, x_workspace: str | None = Header(default=None)) -> dict:
        """Replace the student's own entries (origin "manual"); imported timetables stay."""
        ws = workspace(x_workspace)
        new = [s.model_copy(update={"origin": "manual"}) for s in body.slots]
        new += _template_slots(body.template)
        with db.connect() as conn:
            kept = [s for s in repo.list_time_slots(conn, ws) if s.origin != "manual"]
            repo.replace_time_slots(conn, ws, kept + new)
            return ok(dump(repo.list_time_slots(conn, ws)))

    @app.put("/api/calendar/availability", tags=["calendar"])
    def put_availability(body: CalendarUpdate, x_workspace: str | None = Header(default=None)) -> dict:
        """Replace the hours the student is willing to study; classes and meetings stay."""
        ws = workspace(x_workspace)
        new = [s.model_copy(update={"origin": "manual", "kind": "available"}) for s in body.slots]
        new += _template_slots(body.template)
        with db.connect() as conn:
            kept = [s for s in repo.list_time_slots(conn, ws) if s.kind != "available"]
            repo.replace_time_slots(conn, ws, kept + new)
            repo.set_setting(conn, ws, "availability_template", body.template)
            return ok(dump(repo.list_time_slots(conn, ws)))

    @app.post("/api/calendar/busy", tags=["calendar"])
    def add_busy(body: BusyIn, x_workspace: str | None = Header(default=None)) -> dict:
        """Add a meeting or other fixed commitment. A saved plan that clashes with it is flagged."""
        ws = workspace(x_workspace)
        if body.end <= body.start:
            raise ApiError("INVALID_INPUT", "end must be after start", 422)
        with db.connect() as conn:
            slots = repo.list_time_slots(conn, ws)
            slot = TimeSlot(start=body.start, end=body.end, kind="busy", label=body.label, origin="manual")
            repo.replace_time_slots(conn, ws, [*slots, slot])
            return ok(dump(repo.list_time_slots(conn, ws)))

    @app.delete("/api/calendar/slots/{slot_id}", tags=["calendar"])
    def delete_slot(slot_id: str, x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            slots = repo.list_time_slots(conn, ws)
            kept = [s for s in slots if s.slot_id != slot_id]
            if len(kept) == len(slots):
                raise ApiError("NOT_FOUND", f"no calendar entry {slot_id}", 404)
            repo.replace_time_slots(conn, ws, kept)
        return ok({"deleted": slot_id})

    @app.get("/api/calendar/template", tags=["calendar"])
    def get_template(x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            return ok(repo.get_setting(conn, ws, "availability_template"))

    # -- plans and gate 2 -------------------------------------------------------------------------
    @app.post("/api/plans/draft", tags=["plans"])
    def draft(body: DraftRequest | None = None, x_workspace: str | None = Header(default=None)) -> dict:
        """Make a plan proposal. It replaces nothing until the student adopts it."""
        ws = workspace(x_workspace)
        with db.connect() as conn:
            settings_now = body.settings if body and body.settings else plan_settings(conn, ws)
            now = clock(conn, ws)
            adopted = repo.get_adopted_plan(conn, ws)
            locks = repo.list_locks(conn, ws)
            done = {(p.task_id, p.start) for p in repo.list_progress(conn, ws)}
            if adopted:  # a session already under way stays where it is
                running = [b for b in adopted["result"].blocks if b.start <= now < b.end and (b.task_id, b.start) not in done]
                locks += [b for b in running if all((b.task_id, b.start) != (x.task_id, x.start) for x in locks)]
            tasks_now = repo.list_tasks(conn, ws)
            open_ids = {t.task_id for t in tasks_now if t.status == "open"}
            locks = [b for b in locks if b.task_id in open_ids]
            request = build_request(tasks_now, repo.list_time_slots(conn, ws), now, repo.list_progress(conn, ws), locks, settings_now)
            result = generate(request)
            issues = check_plan(request, result)
            if issues:  # never store a plan that breaks the rules
                raise ApiError("PLAN_CHECK_FAILED", "the generated plan failed the independent check", 500, issues)
            plan_id = f"P-{uuid.uuid4().hex[:10]}"
            based_on = repo.input_version(conn, ws, settings_now)
            repo.save_plan(conn, ws, plan_id, based_on, request, result)
            titles = {t.task_id: t.title for t in tasks_now}
        return ok({
            "plan_id": plan_id,
            "based_on": based_on,
            "checked": True,
            "request": request.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
            "titles": titles,
            "changes": _changes(adopted["result"].blocks if adopted else [], result.blocks, now),
        })

    @app.get("/api/plans/current", tags=["plans"])
    def current_plan(x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            return ok(current_plan_view(conn, ws))

    @app.post("/api/plans/{plan_id}/adopt", tags=["plans"])
    def adopt(plan_id: str, body: AdoptRequest, x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            plan = repo.get_plan(conn, ws, plan_id)
            if plan is None:
                raise ApiError("NOT_FOUND", f"no plan {plan_id}", 404)
            if plan["status"] != "draft":
                raise ApiError("NOT_A_DRAFT", f"plan is {plan['status']}", 409)
            current = repo.input_version(conn, ws, plan["request"].settings)
            if body.based_on != plan["based_on"] or current != plan["based_on"]:
                raise ApiError(STALE_DRAFT, "tasks or calendar changed since this draft was made; generate a new draft", 409,
                               {"draft_based_on": plan["based_on"], "current": current})
            repo.adopt_plan(conn, ws, plan_id)
            return ok(current_plan_view(conn, ws))

    @app.post("/api/plans/lock", tags=["plans"])
    def lock(body: LockIn, x_workspace: str | None = Header(default=None)) -> dict:
        """Fix a planned session in place (or release it). Re-planning keeps locked sessions."""
        ws = workspace(x_workspace)
        with db.connect() as conn:
            if repo.get_task(conn, ws, body.task_id) is None:
                raise ApiError("NOT_FOUND", f"no task {body.task_id}", 404)
            repo.set_lock(conn, ws, PlanBlock(task_id=body.task_id, start=body.start, end=body.end), body.locked)
            return ok(current_plan_view(conn, ws))

    @app.get("/api/plans/current/ics", tags=["plans"])
    def plan_ics(x_workspace: str | None = Header(default=None)) -> Response:
        """The saved plan and deadlines as a calendar file for Outlook, Google or Apple Calendar."""
        ws = workspace(x_workspace)
        with db.connect() as conn:
            plan = repo.get_adopted_plan(conn, ws)
            tasks_by_id = {t.task_id: t for t in repo.list_tasks(conn, ws)}
        if plan is None:
            raise ApiError("NOT_FOUND", "no saved plan yet", 404)
        return Response(_ics(plan, tasks_by_id), media_type="text/calendar",
                        headers={"Content-Disposition": 'attachment; filename="studyspace-plan.ics"'})

    # -- progress ---------------------------------------------------------------------------------
    @app.post("/api/progress", tags=["plans"])
    def progress(body: ProgressIn, x_workspace: str | None = Header(default=None)) -> dict:
        """Record finished work. Sending the same op_id twice is harmless (no double counting)."""
        ws = workspace(x_workspace)
        if body.end <= body.start:
            raise ApiError("INVALID_INPUT", "end must be after start", 422)
        with db.connect() as conn:
            task = repo.get_task(conn, ws, body.task_id)
            if task is None:
                raise ApiError("NOT_FOUND", f"no task {body.task_id}", 404)
            p = Progress(op_id=body.op_id, task_id=body.task_id, start=body.start, end=body.end)
            recorded = repo.add_progress(conn, ws, p)
            if recorded:
                remaining = body.remaining_minutes if body.remaining_minutes is not None else max(0, task.remaining_minutes - p.minutes)
                task = task.model_copy(update={"remaining_minutes": remaining, "status": "done" if remaining == 0 else task.status})
                repo.save_task(conn, ws, task)
                repo.set_lock(conn, ws, PlanBlock(task_id=p.task_id, start=p.start, end=p.end), False)  # done, no longer a lock
        return ok({"recorded": recorded, "task": task.model_dump(mode="json")})

    # -- replies (gate 3) -------------------------------------------------------------------------
    def make_draft(conn, ws: str, record_id: str) -> dict:
        src = find_source(conn, ws, record_id)
        prof = profile(conn, ws)
        style = learn_style(repo.get_setting(conn, ws, "sent_samples", []), (prof.get("name") or "Student").split()[0])
        now = clock(conn, ws)
        slots = suggest_slots(busy_intervals(conn, ws), now.date(), now.date() + timedelta(days=7), 30, now,
                              window=("10:00", "18:00"), weekdays_only=True, max_results=3, per_day=1)
        d: Draft = draft_reply(src, style, slots, domain(conn, ws), gateway(conn, ws))
        return {**d.__dict__, "slots": slots}

    @app.get("/api/drafts/{record_id}", tags=["replies"])
    def get_draft(record_id: str, regenerate: bool = False, x_workspace: str | None = Header(default=None)) -> dict:
        """A reply draft for this message. Studyspace never sends it; the student copies or opens it in their mail app."""
        ws = workspace(x_workspace)
        with db.connect() as conn:
            saved = None if regenerate else repo.get_draft(conn, ws, record_id)
            if saved is None:
                saved = {**make_draft(conn, ws, record_id), "status": "draft"}
                repo.save_draft(conn, ws, record_id, {k: v for k, v in saved.items() if k != "status"})
        return ok(saved)

    @app.put("/api/drafts/{record_id}", tags=["replies"])
    def edit_draft(record_id: str, body: DraftEdit, x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            saved = repo.get_draft(conn, ws, record_id) or make_draft(conn, ws, record_id)
            saved = {k: v for k, v in saved.items() if k != "status"}
            saved["body"] = body.body
            if body.subject is not None:
                saved["subject"] = body.subject
            repo.save_draft(conn, ws, record_id, saved)  # an edit needs a fresh review
        return ok({**saved, "status": "draft"})

    @app.post("/api/drafts/{record_id}/reviewed", tags=["replies"])
    def review_draft(record_id: str, x_workspace: str | None = Header(default=None)) -> dict:
        """Gate 3: the student has read the draft. Only then does the app offer copy / open-in-mail-app."""
        ws = workspace(x_workspace)
        with db.connect() as conn:
            saved = repo.get_draft(conn, ws, record_id)
            if saved is None:
                raise ApiError("NOT_FOUND", "open the draft first", 404)
            body = {k: v for k, v in saved.items() if k != "status"}
            repo.save_draft(conn, ws, record_id, body, status="reviewed")
        return ok({**body, "status": "reviewed", "sent": False})

    # -- meetings ---------------------------------------------------------------------------------
    @app.post("/api/meetings/suggest", tags=["meetings"])
    def meetings(body: MeetingRequest, x_workspace: str | None = Header(default=None)) -> dict:
        """Free times for a meeting, avoiding classes, exams, meetings, locked sessions and other people's busy times."""
        ws = workspace(x_workspace)
        with db.connect() as conn:
            now = clock(conn, ws)
            busy = busy_intervals(conn, ws) + [Interval(start=b.start, end=b.end) for b in repo.list_locks(conn, ws)]
            if body.others_busy_ics:
                busy += [Interval(start=s.start, end=s.end) for s in parse_ics(body.others_busy_ics).slots]
            adopted = repo.get_adopted_plan(conn, ws)
            soft = [Interval(start=b.start, end=b.end) for b in adopted["result"].blocks] if adopted else []
        start = body.start_date or now.date()
        end = body.end_date or start + timedelta(days=6)
        if end < start:
            raise ApiError("INVALID_INPUT", "end_date is before start_date", 422)
        slots = suggest_slots(busy, start, end, body.duration_minutes, now, (body.window_start, body.window_end),
                              soft_busy=soft, weekdays_only=body.weekdays_only)
        return ok({"slots": slots, "considered_busy": len(busy)})

    # -- privacy ----------------------------------------------------------------------------------
    @app.post("/api/privacy/preview", tags=["privacy"])
    def privacy_preview(body: PrivacyPreview, x_workspace: str | None = Header(default=None)) -> dict:
        """Exactly what a model provider would receive for this text: cleaned and redacted."""
        ws = workspace(x_workspace)
        with db.connect() as conn:
            text = body.text
            if body.record_id:
                src = find_source(conn, ws, body.record_id)
                text = f"{src.subject or ''}\n\n{src.body_text}"
            if not text:
                raise ApiError("INVALID_INPUT", "send text or record_id", 422)
            prepared = prepare(text, known_names(conn, ws))
        return ok({"original": text, "would_send": prepared.text, "replaced": prepared.counts, "sent": False})

    @app.get("/api/privacy/log", tags=["privacy"])
    def privacy_log(x_workspace: str | None = Header(default=None)) -> dict:
        """Every text that was sent to a model provider (empty in offline mode)."""
        ws = workspace(x_workspace)
        with db.connect() as conn:
            return ok({"provider": provider.name, "calls": repo.list_llm_log(conn, ws), "database": str(settings.db_path)})

    # -- web front end ----------------------------------------------------------------------------
    if WEB_DIR.exists():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")

    return app


def _template_slots(template: dict | None) -> list[TimeSlot]:
    if not template:
        return []
    try:
        return expand_template(template, origin="manual")
    except (KeyError, ValueError) as exc:
        raise ApiError("INVALID_TEMPLATE", f"free-time template not readable: {exc}", 422)


def _plan_json(plan: dict) -> dict:
    return {
        "plan_id": plan["plan_id"],
        "status": plan["status"],
        "based_on": plan["based_on"],
        "created_at": plan["created_at"],
        "adopted_at": plan["adopted_at"],
        "result": plan["result"].model_dump(mode="json"),
    }


def _changes(old: list[PlanBlock], new: list[PlanBlock], now: datetime) -> dict:
    """What re-planning would change in the future part of the saved plan."""
    key = lambda b: (b.task_id, b.start, b.end)  # noqa: E731
    old_future = {key(b): b for b in old if b.end > now}
    new_keys = {key(b): b for b in new}
    return {
        "kept": len(old_future.keys() & new_keys.keys()),
        "added": [b.model_dump(mode="json") for k, b in new_keys.items() if k not in old_future],
        "removed": [b.model_dump(mode="json") for k, b in old_future.items() if k not in new_keys],
        "had_saved_plan": bool(old),
    }


def _ics(plan: dict, tasks: dict[str, Task]) -> str:
    def stamp(dt: datetime) -> str:
        return dt.astimezone(TZ).strftime("%Y%m%dT%H%M%S")

    def esc(text: str) -> str:
        return text.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Studyspace//Study plan//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:Studyspace plan"]
    blocks = [*plan["result"].blocks, *plan["result"].retained_locked_blocks]
    for i, b in enumerate(blocks):
        title = tasks[b.task_id].title if b.task_id in tasks else b.task_id
        lines += ["BEGIN:VEVENT", f"UID:{plan['plan_id']}-{i}@studyspace.local", f"DTSTAMP:{stamp(b.start)}",
                  f"DTSTART;TZID=Asia/Singapore:{stamp(b.start)}", f"DTEND;TZID=Asia/Singapore:{stamp(b.end)}",
                  f"SUMMARY:{esc('Study: ' + title)}", "END:VEVENT"]
    for t in tasks.values():
        if t.status == "open" and t.kind == "deliverable":
            lines += ["BEGIN:VEVENT", f"UID:due-{t.task_id}@studyspace.local", f"DTSTAMP:{stamp(t.due_at)}",
                      f"DTSTART;TZID=Asia/Singapore:{stamp(t.due_at - timedelta(minutes=15))}",
                      f"DTEND;TZID=Asia/Singapore:{stamp(t.due_at)}", f"SUMMARY:{esc('Due: ' + t.title)}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
