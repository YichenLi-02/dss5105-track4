from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, ConfigDict

from ..db import connect, transaction
from ..security import Session, require_mutation, require_session
from ..services import document_service as ds

router = APIRouter(prefix="/api")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


@router.post("/uploads", status_code=201)
async def upload(file: UploadFile = File(...), format: Literal["pdf"] = Form(...), _: Session = Depends(require_mutation)):
    data = await file.read(ds.settings.max_upload_bytes + 1)
    return ds.save_upload(file.filename or "upload.pdf", data, format)


class DocumentIn(Strict):
    upload_id: str | None = None
    kind: Literal["syllabus", "assignment_brief", "academic_calendar"]
    title: str | None = None
    course: str | None = None
    term: str
    source_timezone: str = "Asia/Singapore"
    user_excerpt: str | None = None
    user_excerpt_page: int | None = None
    permission_confirmed: bool


@router.post("/documents", status_code=201)
def create_document(body: DocumentIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return ds.create_document(conn, body.model_dump())


@router.get("/documents")
def list_documents(_: Session = Depends(require_session)):
    from ..services import preferences
    with connect() as conn:
        docs = ds.list_documents(conn)
        return docs if preferences.show_demo_data(conn) else [d for d in docs if not d["synthetic"]]


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, _: Session = Depends(require_session)):
    with connect() as conn:
        return ds.get_document(conn, doc_id)


class DocumentPatch(Strict):
    expected_revision: int
    kind: Literal["syllabus", "assignment_brief", "academic_calendar"] | None = None
    title: str | None = None
    course: str | None = None
    term: str | None = None
    source_timezone: str | None = None
    page: int | None = None
    user_excerpt: str | None = None
    excluded: bool | None = None


@router.patch("/documents/{doc_id}")
def patch_document(doc_id: str, body: DocumentPatch, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return ds.update_document(conn, doc_id, body.model_dump(exclude_unset=True))


class RevisionIn(Strict):
    expected_revision: int


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str, body: RevisionIn, _: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return ds.delete_local_data(conn, doc_id, body.expected_revision)


class ExtractIn(Strict):
    expected_revision: int
    calendar_document_ids: list[str] = []
    use_model: bool = False


@router.post("/documents/{doc_id}/extract")
def extract(doc_id: str, body: ExtractIn, _: Session = Depends(require_mutation)):
    # Local rules run synchronously (fast, no network). Model extraction for documents is not offered
    # in this build; use_model=true is rejected instead of silently falling back.
    if body.use_model:
        from ..errors import AppError
        raise AppError(422, "MODEL_DOCUMENT_EXTRACTION_NOT_AVAILABLE", "Document extraction uses local rules only")
    with connect() as conn, transaction(conn):
        result = ds.extract_candidates(conn, doc_id, body.expected_revision, body.calendar_document_ids)
        return {"status": "completed", "result": result, "document": ds.get_document(conn, doc_id)}


@router.post("/demo/documents", status_code=201)
def load_demo_documents(_: Session = Depends(require_mutation)):
    with connect() as conn, transaction(conn):
        return ds.load_synthetic(conn)
