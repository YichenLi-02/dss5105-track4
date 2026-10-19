"""Account connections (OAuth), read-only sync jobs, Teams chat read, model status and analysis jobs."""
from __future__ import annotations

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict

from ..config import settings
from ..db import connect, transaction
from ..errors import AppError
from ..llm import adapter
from ..providers import mail_readers, oauth, teams
from ..security import Session, require_mutation, require_session
from ..services import analysis_service, chat_service
from ..services.jobs import create_job, run_job

router = APIRouter(prefix="/api")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.get("/connections")
def list_connections(_: Session = Depends(require_session)):
    with connect() as conn:
        items = oauth.list_connections(conn)
        return {"items": items, "next_cursor": None, "total": len(items)}


class AuthorizeIn(Strict):
    capability: Literal["read_mail", "read_busy", "send_mail", "study_calendar", "read_chat", "send_chat"]


@router.post("/connections/{provider}/authorize")
def authorize(provider: str, body: AuthorizeIn, session: Session = Depends(require_mutation)):
    with connect() as conn:
        return oauth.begin(conn, provider, body.capability, session.id_hash)


@router.get("/connections/{provider}/callback", include_in_schema=True)
def callback(provider: str, code: str | None = None, state: str | None = None, error: str | None = None,
             error_description: str | None = None):
    with connect() as conn, transaction(conn):
        outcome = oauth.callback(conn, provider, code, state, error, error_description)
    # Token never travels in the URL; only an outcome keyword does. Same-origin redirect: the callback
    # is served by this process, which also serves the built UI (in Vite dev the cookie is host-scoped).
    return RedirectResponse(f"/#/sources/connections?oauth={quote(provider)}:{quote(outcome)}", status_code=303)


@router.post("/connections/{connection_id}/disconnect")
def disconnect(connection_id: str, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return oauth.disconnect(conn, connection_id)


class SyncIn(Strict):
    connection_id: str
    lookback_days: int = 7
    max_messages: int = 50
    include_spam_trash: bool = False


@router.post("/sync-jobs", status_code=202)
def sync(body: SyncIn, background: BackgroundTasks, _: Session = Depends(require_mutation)):
    if not 1 <= body.lookback_days <= 90 or not 1 <= body.max_messages <= 500:
        raise AppError(422, "VALIDATION_FAILED", "lookback_days 1-90, max_messages 1-500")
    with connect() as conn:
        provider = body.connection_id.removeprefix("conn_")
        if provider not in ("google", "microsoft") or not oauth.has_scope(conn, provider, "read_mail"):
            raise AppError(409, "NOT_CONNECTED", "Connect a read-only mailbox first; local samples still work")
        busy = conn.execute("SELECT id FROM jobs WHERE kind='sync' AND connection_id=? AND status IN ('queued','running')",
                            (body.connection_id,)).fetchone()
        if busy:
            raise AppError(409, "SYNC_ALREADY_RUNNING", "A sync for this connection is running", [busy[0]])
        job = create_job(conn, "sync", body.model_dump(), body.connection_id)
    background.add_task(run_job, job["id"], mail_readers.sync, False)
    return job


@router.get("/connections/microsoft/chats")
def ms_chats(_: Session = Depends(require_session)):
    with connect() as conn:
        return teams.list_chats(conn)


class ChatImportIn(Strict):
    chat_id: str


@router.post("/connections/microsoft/chats/import", status_code=201)
def ms_chat_import(body: ChatImportIn, _: Session = Depends(require_mutation)):
    with connect() as conn:
        msgs = teams.read_chat(conn, body.chat_id)
        with transaction(conn):
            out = chat_service.create_summary(conn, {"messages": msgs, "title": f"Teams chat {body.chat_id[:12]}"})
            out["chat_id"] = body.chat_id
            return out


@router.get("/model/status")
def model_status(_: Session = Depends(require_session)):
    with connect() as conn:
        return adapter.status(conn)


class AnalysisIn(Strict):
    message_ids: list[str]
    force: bool = False


@router.post("/analysis-jobs", status_code=202)
def analysis(body: AnalysisIn, background: BackgroundTasks, _: Session = Depends(require_mutation)):
    with connect() as conn:
        adapter.require_enabled(conn)
        job = create_job(conn, "analysis", body.model_dump())
    background.add_task(run_job, job["id"], analysis_service.run, False)
    return job
