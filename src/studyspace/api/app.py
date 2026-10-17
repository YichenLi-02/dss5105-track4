"""HTTP API and orchestration (member 5's area). The only layer that touches the database.

Every response has the same envelope: {"ok": true, "data": ...} or {"ok": false, "error": {"code", "message"}}.
The X-Workspace header picks whose data a request works on (default "local"); the hosted demo gives each
visitor a separate workspace.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from email.utils import parseaddr
from typing import Any, Literal

from fastapi import FastAPI, File, Header, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import AwareDatetime, BaseModel, Field

from .. import __version__
from ..academic_calendar import AcademicCalendar
from ..config import Settings, load_settings
from ..extraction import extract
from ..ingest import ImportResult, expand_template, parse_eml, parse_file, parse_ics, parse_text
from ..llm import Gateway, get_provider, prepare
from ..models import STALE_DRAFT, Candidate, PlanSettings, Priority, Progress, Task, TaskKind, TimeSlot
from ..planner import NotImplementedYet, build_request, generate, preview
from ..storage import Database
from ..storage import repo
from ..synthetic import DEMO_NOW, KNOWN_NAMES, build as build_synthetic
from ..timeutil import now as real_now

WORKSPACE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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


class TaskPatch(BaseModel):
    title: str | None = None
    due_at: AwareDatetime | None = None
    remaining_minutes: int | None = Field(default=None, ge=0)
    priority: Priority | None = None
    status: Literal["open", "done"] | None = None


class CalendarUpdate(BaseModel):
    slots: list[TimeSlot] = Field(default_factory=list)
    template: dict | None = None  # weekly free-time template, see ingest/availability.py


class DraftRequest(BaseModel):
    settings: PlanSettings = Field(default_factory=PlanSettings)


class AdoptRequest(BaseModel):
    based_on: str  # the draft's input version; adopting a stale draft is refused


class ProgressIn(BaseModel):
    op_id: str = Field(min_length=1, max_length=100)
    task_id: str
    start: AwareDatetime
    end: AwareDatetime
    remaining_minutes: int | None = Field(default=None, ge=0)  # the student's new estimate, if they give one


class PrivacyPreview(BaseModel):
    text: str | None = None
    record_id: str | None = None


# ---- app ------------------------------------------------------------------------------------
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = Database(settings.db_path)
    calendar = AcademicCalendar.load(settings.calendar_path)
    gateway = Gateway(get_provider(settings.llm_provider))

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
            content={"ok": False, "data": None, "error": {"code": "INVALID_INPUT", "message": "request body is not valid", "details": details}},
        )

    # -- helpers ----------------------------------------------------------------------------------
    def workspace(value: str | None) -> str:
        ws = value or "local"
        if not WORKSPACE_ID.match(ws):
            raise ApiError("INVALID_WORKSPACE", "X-Workspace may only contain letters, digits, '-' and '_'")
        return ws

    def clock(conn, ws: str) -> datetime:
        return repo.get_demo_now(conn, ws) or real_now()

    def known_names(conn, ws: str) -> list[str]:
        names = set(KNOWN_NAMES)
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

    # -- pages ------------------------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def home() -> str:
        return LANDING

    # -- system -----------------------------------------------------------------------------------
    @app.get("/api/health", tags=["system"])
    def health() -> dict:
        return ok({"status": "ok", "version": __version__, "llm_provider": gateway.provider.name, "llm_online": gateway.online})

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
                "sources": len(repo.list_sources(conn, ws)),
                "candidates_pending": len(repo.list_candidates(conn, ws, "pending")),
                "tasks": len(repo.list_tasks(conn, ws)),
                "time_slots": len(repo.list_time_slots(conn, ws)),
                "adopted_plan": adopted["plan_id"] if adopted else None,
            })

    @app.post("/api/workspace/reset", tags=["system"])
    def reset(x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            repo.reset_workspace(conn, ws)
        return ok({"workspace": ws, "reset": True})

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
        result = parse_text(body.text, body.subject, body.course_code, body.received_at)
        with db.connect() as conn:
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
            found = repo.list_sources(conn, ws, [record_id])
        if not found:
            raise ApiError("NOT_FOUND", f"no source {record_id}", 404)
        return ok(found[0].model_dump(mode="json"))

    # -- extraction and gate 1 -------------------------------------------------------------------
    @app.post("/api/extract", tags=["tasks"])
    def run_extract(x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            candidates = run_extraction(conn, ws)
        return ok({"mode": "online" if gateway.online else "offline-rules", "candidates": dump(candidates)})

    @app.get("/api/candidates", tags=["tasks"])
    def candidates(status: Literal["pending", "confirmed", "dismissed"] | None = None, x_workspace: str | None = Header(default=None)) -> dict:
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
            if due_at is None:
                raise ApiError(
                    "NEEDS_DUE_AT",
                    "this task has no exact deadline yet; send due_at with the date and time you checked",
                    422,
                    {"due_text": c.due_text, "due_date": c.due_date.isoformat() if c.due_date else None, "flags": c.flags},
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
        if body.template:
            try:
                new += expand_template(body.template, origin="manual")
            except (KeyError, ValueError) as exc:
                raise ApiError("INVALID_TEMPLATE", f"free-time template not readable: {exc}", 422)
        with db.connect() as conn:
            kept = [s for s in repo.list_time_slots(conn, ws) if s.origin != "manual"]
            repo.replace_time_slots(conn, ws, kept + new)
            return ok(dump(repo.list_time_slots(conn, ws)))

    # -- plans and gate 2 -------------------------------------------------------------------------
    @app.post("/api/plans/draft", tags=["plans"])
    def draft(body: DraftRequest | None = None, x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        plan_settings = body.settings if body else PlanSettings()
        with db.connect() as conn:
            now = clock(conn, ws)
            adopted = repo.get_adopted_plan(conn, ws)
            locked = [b for b in adopted["result"].blocks if b.start <= now < b.end] if adopted else []
            request = build_request(
                repo.list_tasks(conn, ws), repo.list_time_slots(conn, ws), now, repo.list_progress(conn, ws), locked, plan_settings
            )
            try:
                result, implemented = generate(request), True
            except NotImplementedYet:
                result, implemented = preview(request), False
            plan_id = f"P-{uuid.uuid4().hex[:10]}"
            based_on = repo.input_version(conn, ws, plan_settings)
            repo.save_plan(conn, ws, plan_id, based_on, request, result)
        return ok({
            "plan_id": plan_id,
            "based_on": based_on,
            "engine_ready": implemented,
            "request": request.model_dump(mode="json"),
            "result": result.model_dump(mode="json"),
        })

    @app.get("/api/plans/current", tags=["plans"])
    def current_plan(x_workspace: str | None = Header(default=None)) -> dict:
        ws = workspace(x_workspace)
        with db.connect() as conn:
            plan = repo.get_adopted_plan(conn, ws)
        return ok(_plan_json(plan) if plan else None)

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
            return ok(_plan_json(repo.get_plan(conn, ws, plan_id)))

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
        return ok({"recorded": recorded, "task": task.model_dump(mode="json")})

    # -- privacy ----------------------------------------------------------------------------------
    @app.post("/api/privacy/preview", tags=["privacy"])
    def privacy_preview(body: PrivacyPreview, x_workspace: str | None = Header(default=None)) -> dict:
        """Exactly what a model provider would receive for this text: cleaned and redacted."""
        ws = workspace(x_workspace)
        with db.connect() as conn:
            text = body.text
            if body.record_id:
                found = repo.list_sources(conn, ws, [body.record_id])
                if not found:
                    raise ApiError("NOT_FOUND", f"no source {body.record_id}", 404)
                text = f"{found[0].subject or ''}\n\n{found[0].body_text}"
            if not text:
                raise ApiError("INVALID_INPUT", "send text or record_id", 422)
            prepared = prepare(text, known_names(conn, ws))
        return ok({"original": text, "would_send": prepared.text, "replaced": prepared.counts, "sent": False})

    return app


def _plan_json(plan: dict) -> dict:
    return {
        "plan_id": plan["plan_id"],
        "status": plan["status"],
        "based_on": plan["based_on"],
        "created_at": plan["created_at"],
        "adopted_at": plan["adopted_at"],
        "result": plan["result"].model_dump(mode="json"),
    }


LANDING = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Studyspace</title>
<style>
:root{--bg:#f7f7f5;--fg:#1d1d1f;--muted:#5f6368;--card:#fff;--line:#e3e3e0;--accent:#2f5d50}
@media (prefers-color-scheme:dark){:root{--bg:#161616;--fg:#ececec;--muted:#a0a0a0;--card:#1f1f1f;--line:#333;--accent:#7fbfa8}}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:720px;margin:0 auto;padding:48px 16px}
h1{font-size:28px;margin:0 0 4px}p{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px;margin:16px 0}
a{color:var(--accent)}code{font-size:14px}
</style></head><body><main>
<h1>Studyspace</h1>
<p>Backend is running. The web front end is still being decided; until then the API can be tried from the interactive docs.</p>
<div class="card"><strong>Try it</strong>
<ol><li>Open <a href="/docs">/docs</a></li>
<li><code>POST /api/demo/load</code> loads the fictional student (clock: Mon 12 Oct 2026, 08:00)</li>
<li><code>GET /api/candidates</code> shows extracted tasks waiting for confirmation</li>
<li><code>POST /api/privacy/preview</code> with a record_id shows what would leave the computer</li></ol></div>
<p>All demo data is synthetic. Real messages stay in the local database.</p>
</main></body></html>"""
