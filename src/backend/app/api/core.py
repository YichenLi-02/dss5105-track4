"""Health, session, preferences, imports and jobs."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Response
from pydantic import BaseModel, ConfigDict

from ..config import VERSION, settings
from ..db import connect, transaction
from ..errors import AppError, not_found
from ..security import COOKIE, Session, create_session, require_mutation, require_session
from ..services import import_service, preferences
from ..services.jobs import create_job, job_view, run_job

router = APIRouter(prefix="/api")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def capabilities() -> dict:
    return {
        "model_configured": settings.model_configured,
        "model_processing_env_enabled": settings.allow_model_processing,
        "llm_provider": settings.llm_provider if settings.model_configured else "none",
        "google_oauth_configured": settings.google_configured,
        "microsoft_oauth_configured": settings.microsoft_configured,
        "external_writes_env_enabled": settings.enable_external_writes,
        "sample_data_available": (settings.sample_data_dir / "selected_50.jsonl").is_file(),
        "reference_view_available": (settings.sample_data_dir / "reference_view.json").is_file()
        or (settings.design_dir / "ui" / "index.html").is_file(),
        "canvas_lms": False,
        "ui_build": _ui_build(),
    }


def _ui_build() -> str | None:
    """Name of the built JS bundle, so an open tab can tell it is running an older UI."""
    from ..main import FRONTEND_DIST
    assets = FRONTEND_DIST / "assets"
    if not assets.is_dir():
        return None
    js = sorted(assets.glob("index-*.js"), key=lambda p: p.stat().st_mtime)
    return js[-1].name if js else None


@router.get("/health")
def health():
    return {"status": "ok", "version": VERSION, "mode": settings.app_mode, "capabilities": capabilities()}


class SessionIn(Strict):
    bootstrap_code: str | None = None


@router.post("/session")
def new_session(body: SessionIn, response: Response):
    s = create_session(body.bootstrap_code)
    response.set_cookie(COOKIE, s.session_id, httponly=True, samesite="strict", secure=False, path="/")
    return {"owner_id": "local_user", "csrf_token": s.csrf_token}


# ---------------------------------------------------------------- preferences

class PreferencesPatch(Strict):
    expected_revision: int
    display_timezone: str | None = None
    day_start: str | None = None
    day_end: str | None = None
    daily_cap_minutes: int | None = None
    session_min_minutes: int | None = None
    session_target_minutes: int | None = None
    session_max_minutes: int | None = None
    break_minutes: int | None = None
    deadline_buffer_minutes: int | None = None
    weekly_flex_minutes: int | None = None
    allow_model_processing: bool | None = None
    enable_external_writes: bool | None = None
    ui_language: Literal["zh-CN", "en"] | None = None
    large_amount_threshold: int | None = None
    show_demo_data: bool | None = None
    show_demo_data_auto: bool | None = None


@router.get("/preferences")
def get_preferences(_: Session = Depends(require_session)):
    with connect() as conn:
        return preferences.view(conn)


@router.patch("/preferences")
def patch_preferences(body: PreferencesPatch, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return preferences.update(conn, body.model_dump(exclude_none=True))


# ---------------------------------------------------------------- imports / jobs

class ImportIn(Strict):
    source: Literal["selected_50", "uploaded_file"]
    upload_id: str | None = None


def _import_job(ctx, payload):
    result = import_service.import_selected_50(ctx.conn, ctx.job_id)
    ctx.progress(result["inbound"] + result["outbound_style"], result["inbound"] + result["outbound_style"])
    return result


@router.post("/imports", status_code=202)
def create_import(body: ImportIn, background: BackgroundTasks, _: Session = Depends(require_mutation)):
    if body.source == "uploaded_file":
        # PDFs go through /api/documents (multipart); generic file imports are not part of this build.
        raise AppError(422, "USE_DOCUMENT_UPLOAD", "Upload PDFs via POST /api/documents")
    with connect() as conn:
        running = conn.execute("SELECT id FROM jobs WHERE kind='import_selected_50' AND status IN ('queued','running')").fetchone()
        if running:
            raise AppError(409, "IMPORT_ALREADY_RUNNING", "An import is already running", [running["id"]])
        job = create_job(conn, "import_selected_50", {"source": body.source})
    background.add_task(run_job, job["id"], _import_job)
    return job


@router.get("/jobs/{job_id}")
def get_job(job_id: str, _: Session = Depends(require_session)):
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise not_found("job")
        return job_view(row)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, _: Session = Depends(require_mutation)):
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise not_found("job")
        if row["status"] in ("queued", "running"):
            conn.execute("UPDATE jobs SET cancel_requested=1 WHERE id=?", (job_id,))
            if row["status"] == "queued":
                conn.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (job_id,))
        return job_view(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())


@router.get("/audit")
def recent_audit(_: Session = Depends(require_session)):
    """Processing log for the collapsed '处理记录' panel: IDs/states only, never bodies."""
    with connect() as conn:
        rows = conn.execute("SELECT event_type, object_type, object_id, summary_json, created_at FROM audit_events "
                            "ORDER BY created_at DESC LIMIT 60").fetchall()
        return [dict(r) for r in rows]
