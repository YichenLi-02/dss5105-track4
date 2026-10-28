"""Course documents: syllabus / assignment brief / academic calendar.

Stored as messages(direction='document'); parsed page text and user-pasted excerpts are kept
apart and never presented as each other. A file that was only uploaded is 'metadata_only'
until real text exists - selecting a file is never reported as successful parsing.
"""
from __future__ import annotations

import hashlib
import io
import re
import sqlite3
import uuid
from pathlib import Path

from ..config import settings
from ..db import audit, dumps, loads, new_id, now_iso
from ..errors import AppError, conflict, not_found
from . import doc_rules
from .privacy import scrub, sha256_text
from .task_service import merge_candidates

DOC_CONNECTION_ID = "conn_local_documents"
KINDS = {"syllabus", "assignment_brief", "academic_calendar"}
MIN_TEXT_CHARS = 8  # below this a PDF is treated as scanned / image-only


# ---------------------------------------------------------------- uploads

def save_upload(filename: str, data: bytes, fmt: str) -> dict:
    if fmt != "pdf":
        raise AppError(422, "UNSUPPORTED_FORMAT", "Only PDF uploads are accepted here")
    if len(data) > settings.max_upload_bytes:
        raise AppError(413, "FILE_TOO_LARGE", "PDF exceeds the 20 MB limit")
    if not data.startswith(b"%PDF-"):
        raise AppError(422, "NOT_A_PDF", "File does not start with a %PDF- header")
    upload_id = "upl_" + uuid.uuid4().hex[:16]
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / f"{upload_id}.pdf").write_bytes(data)
    safe_name = re.sub(r"[^\w.\- ()一-鿿]", "_", Path(filename or "upload.pdf").name)[:120]
    meta = {"upload_id": upload_id, "filename": safe_name, "format": fmt, "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}
    (settings.upload_dir / f"{upload_id}.json").write_text(dumps(meta), encoding="utf-8")
    return meta


def upload_meta(upload_id: str) -> dict:
    if not re.fullmatch(r"upl_[0-9a-f]{16}", upload_id or ""):
        raise AppError(422, "INVALID_UPLOAD_ID", "Unknown upload id")
    p = settings.upload_dir / f"{upload_id}.json"
    if not p.is_file():
        raise not_found("upload")
    return loads(p.read_text(encoding="utf-8"))


def upload_bytes(upload_id: str) -> bytes:
    upload_meta(upload_id)
    return (settings.upload_dir / f"{upload_id}.pdf").read_bytes()


# ---------------------------------------------------------------- parsing

def parse_pdf(data: bytes) -> dict:
    """Return {'status','pages':[{page,text}],'error'} using pypdf; no OCR, no execution of content."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception:  # noqa: BLE001 - unsupported crypto is also "cannot read"
                ok = 0
            if not ok:
                return {"status": "encrypted", "pages": [], "error": "PDF is password-protected"}
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            try:
                txt = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001
                return {"status": "failed", "pages": [], "error": f"page {i}: {type(exc).__name__}"}
            pages.append({"page": i, "text": txt.replace("\r\n", "\n").replace("\x00", "")})
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        return {"status": "failed", "pages": [], "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "failed", "pages": [], "error": f"{type(exc).__name__}"}
    total = sum(len(p["text"].strip()) for p in pages)
    if not pages:
        return {"status": "failed", "pages": [], "error": "PDF has no pages"}
    if total < MIN_TEXT_CHARS:
        return {"status": "needs_ocr", "pages": pages, "error": "No extractable text (scanned or image-only PDF)"}
    return {"status": "text_ready", "pages": pages, "error": None}


def _join_pages(pages: list[dict]) -> tuple[str, list[dict]]:
    parts, spans, pos = [], [], 0
    for p in pages:
        text = scrub(p["text"].strip())
        spans.append({"page": p["page"], "start": pos, "end": pos + len(text)})
        parts.append(text)
        pos += len(text) + 2
    return "\n\n".join(parts), spans


# ---------------------------------------------------------------- records

def _ensure_connection(conn: sqlite3.Connection) -> None:
    ts = now_iso()
    conn.execute(
        """INSERT OR IGNORE INTO connections(id,provider,account_label,scopes_json,capabilities_json,status,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (DOC_CONNECTION_ID, "local_jsonl", "local documents", "[]", dumps({"read_documents": True}),
         "connected", ts, ts))


def create_document(conn: sqlite3.Connection, body: dict) -> dict:
    kind = body.get("kind")
    if kind not in KINDS:
        raise AppError(422, "INVALID_KIND", "kind must be syllabus, assignment_brief or academic_calendar")
    if not body.get("permission_confirmed"):
        raise AppError(422, "PERMISSION_NOT_CONFIRMED", "Confirm you are allowed to provide this material")
    if not (body.get("term") or "").strip():
        raise AppError(422, "TERM_REQUIRED", "Term is required so relative dates use the right calendar")
    _ensure_connection(conn)
    upload = upload_meta(body["upload_id"]) if body.get("upload_id") else None
    excerpt = (body.get("user_excerpt") or "").strip()
    if not upload and not excerpt:
        raise AppError(422, "NO_CONTENT", "Choose a PDF or paste the original text")
    parsed = {"status": "metadata_only", "pages": [], "error": None}
    if upload:
        parsed = parse_pdf(upload_bytes(upload["upload_id"]))
    text, spans = _join_pages(parsed["pages"]) if parsed["status"] == "text_ready" else ("", [])
    status = parsed["status"]
    if not upload:
        status = "text_ready"  # pasted text only; excerpt_origin=user_pasted tells it apart from parsed PDF
    if status in ("needs_ocr", "encrypted", "failed") and excerpt:
        status_note = "user_excerpt_available"
    else:
        status_note = None
    doc_id = new_id("doc")
    source_id = "DOC-" + doc_id[-6:].upper()
    locator = {
        "kind": kind, "title": (body.get("title") or (upload or {}).get("filename") or source_id).strip()[:160],
        "course": (body.get("course") or "").strip() or None, "term": body["term"].strip(),
        "source_timezone": body.get("source_timezone") or settings.display_timezone,
        "filename": (upload or {}).get("filename"), "size_bytes": (upload or {}).get("size_bytes", 0),
        "file_sha256": (upload or {}).get("sha256"), "upload_id": (upload or {}).get("upload_id"),
        "pages": spans, "page_count": len(parsed["pages"]), "extraction_status": status,
        "extraction_error": parsed["error"], "status_note": status_note,
        "user_excerpt": scrub(excerpt), "user_excerpt_page": body.get("user_excerpt_page"),
        "synthetic": bool(body.get("synthetic")), "permission_confirmed": True,
    }
    ts = now_iso()
    source_type = "academic_calendar" if kind == "academic_calendar" else "uploaded_pdf"
    conn.execute(
        """INSERT INTO messages(id,connection_id,provider_message_id,source_type,source_id,direction,subject,sent_at,
           source_timezone,body_view,body_hash,locator_json,analysis_status,analysis_origin,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (doc_id, DOC_CONNECTION_ID, doc_id, source_type, source_id, "document", locator["title"], ts,
         locator["source_timezone"], text, sha256_text(text + "\x1e" + locator["user_excerpt"]), dumps(locator),
         status, "none", ts, ts))
    audit(conn, "document_added", "document", doc_id, {"kind": kind, "status": status, "pages": len(parsed["pages"])})
    return get_document(conn, doc_id)


def _row(conn: sqlite3.Connection, doc_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM messages WHERE id=? AND direction='document'", (doc_id,)).fetchone()
    if not row:
        raise not_found("document")
    return row


def _doc_view(conn: sqlite3.Connection, row: sqlite3.Row, with_text: bool = True) -> dict:
    loc = loads(row["locator_json"], {})
    status = loc.get("extraction_status", "metadata_only")
    if row["excluded"] and status != "deleted":
        pass
    if loc.get("user_excerpt"):
        excerpt, origin = loc["user_excerpt"], "user_pasted"
    elif row["body_view"]:
        excerpt, origin = row["body_view"][:600], "parsed_pdf"
    else:
        excerpt, origin = "", "none"
    from .task_service import row_to_task
    task_rows = conn.execute(
        "SELECT DISTINCT t.* FROM tasks t JOIN task_evidence e ON e.task_id=t.id WHERE e.message_id=?", (row["id"],)).fetchall()
    return {
        "id": row["id"], "source_message_id": row["id"], "source_id": row["source_id"], "kind": loc.get("kind"),
        "title": loc.get("title"), "title_en": _doc_title_en(loc.get("title")),
        "course": loc.get("course"), "term": loc.get("term"),
        "source_timezone": loc.get("source_timezone"), "filename": loc.get("filename"),
        "size_bytes": loc.get("size_bytes", 0), "upload_id": loc.get("upload_id"),
        "page": loc.get("user_excerpt_page"), "excerpt": excerpt,
        "excerpt_origin": origin, "extraction_status": status, "extraction_error": loc.get("extraction_error"),
        "pages": [{"page": p["page"], "chars": p["end"] - p["start"]} for p in loc.get("pages", [])],
        "page_count": loc.get("page_count", 0), "user_excerpt": loc.get("user_excerpt", ""),
        "user_excerpt_page": loc.get("user_excerpt_page"),
        "parsed_text": row["body_view"] if with_text else "",
        "excluded": bool(row["excluded"]), "synthetic": loc.get("synthetic", False), "revision": row["revision"],
        "candidates": [row_to_task(conn, t) for t in task_rows],
    }


def _doc_title_en(title):
    from . import ref_i18n
    return ref_i18n.doc_title(title)


def get_document(conn: sqlite3.Connection, doc_id: str) -> dict:
    return _doc_view(conn, _row(conn, doc_id))


def list_documents(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM messages WHERE direction='document' ORDER BY created_at").fetchall()
    return [_doc_view(conn, r, with_text=False) for r in rows if loads(r["locator_json"], {}).get("extraction_status") != "deleted"]


def _mark_dependents_stale(conn: sqlite3.Connection, doc_id: str, reason: str) -> int:
    """Tasks backed by this document go back to review; plans built on them become stale via revision."""
    rows = conn.execute(
        "SELECT DISTINCT t.id, t.status FROM tasks t JOIN task_evidence e ON e.task_id=t.id WHERE e.message_id=?",
        (doc_id,)).fetchall()
    for r in rows:
        new_status = "needs_review" if r["status"] in ("confirmed", "in_progress", "candidate") else r["status"]
        conn.execute("UPDATE tasks SET status=?, revision=revision+1, updated_at=? WHERE id=?",
                     (new_status, now_iso(), r["id"]))
    if rows:
        audit(conn, "document_dependents_stale", "document", doc_id, {"tasks": len(rows), "reason": reason})
    return len(rows)


def update_document(conn: sqlite3.Connection, doc_id: str, body: dict) -> dict:
    row = _row(conn, doc_id)
    if row["revision"] != body.get("expected_revision"):
        raise conflict("REVISION_CONFLICT", "Document changed; reload", [f"current_revision={row['revision']}"])
    loc = loads(row["locator_json"], {})
    if loc.get("extraction_status") == "deleted":
        raise AppError(409, "DOCUMENT_DELETED", "Local data for this document was deleted")
    content_changed = False
    for key in ("kind", "course", "term", "source_timezone", "title"):
        if key in body and body[key] is not None:
            if key == "kind" and body[key] not in KINDS:
                raise AppError(422, "INVALID_KIND", "Unknown kind")
            content_changed |= loc.get(key) != body[key]
            loc[key] = body[key]
    if "user_excerpt" in body and body["user_excerpt"] is not None:
        new = scrub(body["user_excerpt"].strip())
        content_changed |= new != loc.get("user_excerpt", "")
        loc["user_excerpt"] = new
    if "page" in body:
        loc["user_excerpt_page"] = body["page"]
    excluded = row["excluded"]
    if "excluded" in body and body["excluded"] is not None:
        content_changed |= bool(body["excluded"]) != bool(excluded)
        excluded = 1 if body["excluded"] else 0
    conn.execute("UPDATE messages SET locator_json=?, excluded=?, subject=?, revision=revision+1, updated_at=? WHERE id=?",
                 (dumps(loc), excluded, loc.get("title", row["subject"]), now_iso(), doc_id))
    if content_changed:
        _mark_dependents_stale(conn, doc_id, "excluded" if excluded else "document_changed")
    audit(conn, "document_updated", "document", doc_id, {"excluded": bool(excluded)})
    return get_document(conn, doc_id)


def delete_local_data(conn: sqlite3.Connection, doc_id: str, expected_revision: int) -> dict:
    row = _row(conn, doc_id)
    if row["revision"] != expected_revision:
        raise conflict("REVISION_CONFLICT", "Document changed; reload", [f"current_revision={row['revision']}"])
    loc = loads(row["locator_json"], {})
    affected = _mark_dependents_stale(conn, doc_id, "document_deleted")
    conn.execute("DELETE FROM task_evidence WHERE message_id=?", (doc_id,))
    if loc.get("upload_id"):
        for suffix in (".pdf", ".json"):
            p = settings.upload_dir / f"{loc['upload_id']}{suffix}"
            if p.is_file():
                p.unlink()
    removed = {k: loc.get(k) for k in ("kind", "title", "course", "term", "source_timezone", "filename")}
    loc = {**removed, "extraction_status": "deleted", "pages": [], "user_excerpt": "", "deleted_at": now_iso()}
    conn.execute("UPDATE messages SET body_view='', locator_json=?, excluded=1, revision=revision+1, updated_at=? WHERE id=?",
                 (dumps(loc), now_iso(), doc_id))
    audit(conn, "document_local_data_deleted", "document", doc_id, {"tasks_back_to_review": affected})
    view = _doc_view(conn, _row(conn, doc_id), with_text=False)
    view["affected_tasks"] = affected
    return view


# ---------------------------------------------------------------- extraction

def _page_lookup(loc: dict, field: str):
    if field == "user_excerpt":
        page = loc.get("user_excerpt_page")
        return lambda _pos: page
    spans = loc.get("pages", [])

    def page_of(pos: int):
        for s in spans:
            if s["start"] <= pos <= s["end"]:
                return s["page"]
        return None
    return page_of


def extract_candidates(conn: sqlite3.Connection, doc_id: str, expected_revision: int,
                       calendar_document_ids: list[str]) -> dict:
    row = _row(conn, doc_id)
    if row["revision"] != expected_revision:
        raise conflict("REVISION_CONFLICT", "Document changed; reload", [f"current_revision={row['revision']}"])
    if row["excluded"]:
        raise AppError(409, "DOCUMENT_EXCLUDED", "Excluded documents cannot be used for extraction")
    loc = loads(row["locator_json"], {})
    sources = []
    if row["body_view"]:
        sources.append(("body", row["body_view"]))
    if loc.get("user_excerpt"):
        sources.append(("user_excerpt", loc["user_excerpt"]))
    if not sources:
        raise AppError(422, "NO_TEXT", "No parsed text or pasted excerpt to read",
                       [loc.get("extraction_status", "metadata_only")])
    calendars = []
    for cid in calendar_document_ids:
        crow = conn.execute("SELECT * FROM messages WHERE id=? AND direction='document' AND excluded=0", (cid,)).fetchone()
        if not crow:
            continue
        cloc = loads(crow["locator_json"], {})
        if cloc.get("kind") != "academic_calendar":
            continue
        ctext = "\n".join(filter(None, [crow["body_view"], cloc.get("user_excerpt", "")]))
        calendars.append(doc_rules.calendar_facts(crow["id"], cloc.get("term", ""), ctext))
    if loc.get("kind") == "academic_calendar":
        facts = doc_rules.calendar_facts(doc_id, loc.get("term", ""), "\n".join(t for _, t in sources))
        return {"candidates": 0, "calendar_facts": {
            "reading_week": [d.isoformat() for d in facts.reading_week] if facts.reading_week else None,
            "week1_start": facts.week1_start.isoformat() if facts.week1_start else None},
            "note": "academic calendars provide supporting dates only; they create no deliverables"}
    created = 0
    for field, text in sources:
        cands = doc_rules.extract(text, document_id=doc_id, term=loc.get("term", ""),
                                  timezone=loc.get("source_timezone"), course=loc.get("course"),
                                  calendars=calendars, page_of=_page_lookup(loc, field))
        for c in cands:
            c["evidence"]["field"] = field
            c["message_id"] = doc_id
            c["source_id"] = row["source_id"]
            c["excerpt_origin"] = "user_pasted" if field == "user_excerpt" else "parsed_pdf"
            key = f"doc_{doc_id}_{hashlib.sha256((field + c['evidence']['quote']).encode()).hexdigest()[:10]}"
            before = conn.execute("SELECT 1 FROM tasks WHERE entity_key=?", (key,)).fetchone()
            merge_candidates(conn, key, [c], title=c["title"], course=loc.get("course"), term=loc.get("term"),
                             origin="rule")
            created += 0 if before else 1
    conn.execute("UPDATE messages SET analysis_status='complete', analysis_origin='rule', updated_at=? WHERE id=?",
                 (now_iso(), doc_id))
    audit(conn, "document_extracted", "document", doc_id, {"new_candidates": created, "calendars": len(calendars)})
    return {"candidates": created, "calendars_used": [c.document_id for c in calendars]}


SYNTHETIC_DOCS = [
    {"kind": "syllabus", "course": "DEMO5105", "title": "合成课程大纲 · DEMO5105 (synthetic)",
     "term": "Demo Term A (synthetic, not an NUS calendar)", "source_timezone": "Asia/Singapore",
     "user_excerpt": "DEMO5105 Final report\nThe final report is due the Friday after reading week.\n"
                     "Submission time is not stated.\nProject presentation: Week 12 Wednesday, 14:00.",
     "user_excerpt_page": 3},
    {"kind": "academic_calendar", "course": None, "title": "合成学年日历 · Demo Term A (synthetic)",
     "term": "Demo Term A (synthetic, not an NUS calendar)", "source_timezone": "Asia/Singapore",
     "user_excerpt": "Synthetic academic calendar for demonstration only.\nWeek 1 begins 2026-08-10.\n"
                     "Reading week: 2026-10-05 to 2026-10-11.",
     "user_excerpt_page": 1},
]


def load_synthetic(conn: sqlite3.Connection) -> list[dict]:
    existing = {loads(r["locator_json"], {}).get("title") for r in
                conn.execute("SELECT locator_json FROM messages WHERE direction='document'").fetchall()}
    out = []
    for d in SYNTHETIC_DOCS:
        if d["title"] in existing:
            continue
        out.append(create_document(conn, {**d, "permission_confirmed": True, "synthetic": True}))
    return out
