"""Tasks: merge candidates from sources, keep evidence, compute what is still missing.

Rules that must hold (see design 01 §4–§6):
- official_time stays NULL when the source does not state it (never default to 23:59);
- contradicting sources keep every candidate and leave official_date NULL until the user picks;
- receipts complete only the deliverable they name;
- the user's planning cutoff is a separate field and never overwrites official values.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..db import audit, dumps, loads, new_id, now_iso
from ..errors import AppError, conflict, not_found

TASK_KINDS = {
    "submission_deadline", "deadline_update", "relative_deadline", "exam_event",
    "exam_availability_window", "conditional_deadline", "response_deadline",
    "urgency_without_deadline", "deadline_in_completed_receipt", "document_deadline",
}
# Times that are real but are not student work: coupons, OTP lifetimes, grading stamps, ...
NON_TASK_KINDS = {
    "class_event", "graded_timestamp", "promotion_expiry", "security_token_lifetime",
    "order_placed_timestamp",
}
CONFLICT_STATUSES = {"conflict_weekday_date", "subject_body_conflict"}
RELATIVE_STATUSES = {"unresolved_source_timezone", "relative_semantics_need_confirmation"}


def parse_zone(name: str | None) -> timezone | ZoneInfo | None:
    if not name:
        return None
    m = re.fullmatch(r"UTC([+-])(\d{2}):(\d{2})", name)
    if m:
        from datetime import timedelta
        sign = 1 if m.group(1) == "+" else -1
        return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def planning_cutoff_utc(official_date: str | None, official_time: str | None, zone: str | None,
                        user_cutoff: str | None) -> str | None:
    if user_cutoff:
        dt = datetime.fromisoformat(user_cutoff)
        if dt.tzinfo is None:
            return None
        return dt.astimezone(timezone.utc).isoformat()
    tz = parse_zone(zone)
    if official_date and official_time and tz:
        dt = datetime.combine(date.fromisoformat(official_date), time.fromisoformat(official_time), tz)
        return dt.astimezone(timezone.utc).isoformat()
    return None


def compute_missing(t: dict) -> list[str]:
    missing = []
    if t["deadline_status"] == "non_task":
        return ["non_task_time"]
    if t["deadline_status"] in ("conflict", "time_conflict") and not t["user_planning_cutoff"]:
        missing.append("resolve_date_conflict")
    if t["deadline_status"] == "relative_unresolved" and not t["user_planning_cutoff"]:
        missing.append("confirm_relative_date")
    if not t["user_planning_cutoff"]:
        if not t["official_date"]:
            missing.append("deadline_date")
        if not t["official_time"]:
            missing.append("deadline_time_or_planning_cutoff")
        if not t["source_timezone"]:
            missing.append("source_timezone")
    if t["estimated_minutes"] is None:
        missing.append("estimated_minutes")
    return missing


def can_confirm(t: dict) -> bool:
    return not compute_missing(t) and t["status"] not in {"completed", "ignored"}


def row_to_task(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    ev = conn.execute(
        """SELECT e.*, m.source_id AS msg_source_id, m.source_type, m.subject, m.sent_at, m.excluded
           FROM task_evidence e JOIN messages m ON m.id=e.message_id WHERE e.task_id=? ORDER BY m.sent_at, e.created_at""",
        (row["id"],),
    ).fetchall()
    t = {k: row[k] for k in row.keys()}
    evidence = [{
        "id": e["id"], "source_id": e["msg_source_id"], "message_id": e["message_id"],
        "source_type": e["source_type"], "subject": e["subject"], "sent_at": e["sent_at"],
        "field": e["field_name"], "quote": e["quote"], "start_char": e["start_char"], "end_char": e["end_char"],
        "relation": e["relation"], "locator": loads(e["locator_json"], {}),
        "field_changes": loads(e["field_changes_json"], {}), "source_excluded": bool(e["excluded"]),
    } for e in ev]
    return {
        "id": t["id"], "entity_key": t["entity_key"], "title": t["title"], "course": t["course"],
        "title_en": _title_en(t["entity_key"]),
        "term": t["term"], "deliverable": t["deliverable"], "required": bool(t["required"]),
        "status": t["status"], "official_date": t["official_date"], "official_time": t["official_time"],
        "source_timezone": t["source_timezone"], "deadline_status": t["deadline_status"],
        "date_candidates": loads(t["date_candidates_json"], []),
        "user_planning_cutoff": t["user_planning_cutoff"], "planning_cutoff_utc": t["planning_cutoff_utc"],
        "estimated_minutes": t["estimated_minutes"], "completed_minutes": t["completed_minutes"],
        "progress": loads(t["progress_json"], []), "missing_fields": loads(t["missing_fields_json"], []),
        "can_confirm": can_confirm({**t, "missing_fields": None}),
        "evidence": evidence, "revision": t["revision"], "updated_at": t["updated_at"],
    }


def _title_en(entity_key: str) -> str | None:
    from . import ref_i18n
    return ref_i18n.task_title(entity_key)


def get_task(conn: sqlite3.Connection, task_id: str) -> dict:
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise not_found("task")
    return row_to_task(conn, row)


def _refresh_derived(conn: sqlite3.Connection, task_id: str) -> None:
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    t = {k: row[k] for k in row.keys()}
    cutoff = planning_cutoff_utc(t["official_date"], t["official_time"], t["source_timezone"], t["user_planning_cutoff"])
    t["planning_cutoff_utc"] = cutoff
    missing = compute_missing(t)
    conn.execute("UPDATE tasks SET planning_cutoff_utc=?, missing_fields_json=? WHERE id=?",
                 (cutoff, dumps(missing), task_id))


# ---------------------------------------------------------------- merge from candidates

def _course_from_key(key: str) -> str | None:
    m = re.match(r"([a-z]{2,4})(\d{3,4})_", key)
    return f"{m.group(1).upper()} {m.group(2)}" if m else None


def _term_from_subject(subject: str) -> str | None:
    m = re.search(r"\((\d{4} (?:Spring|Summer|Fall|Winter)[^)]*)\)", subject or "")
    return m.group(1) if m else None


def _humanize(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def merge_candidates(conn: sqlite3.Connection, entity_key: str, cands: list[dict], *, title: str | None,
                     course: str | None, term: str | None, origin: str) -> str:
    """Create or extend one task from candidate records. Existing user edits are never overwritten."""
    existing = conn.execute("SELECT * FROM tasks WHERE entity_key=? AND owner_id='local_user'", (entity_key,)).fetchone()
    ts = now_iso()
    if existing:
        task_id = existing["id"]
        stored = loads(existing["date_candidates_json"], [])
        known = {c.get("candidate_id") for c in stored}
        added = [c for c in cands if c.get("candidate_id") not in known]
        if added:
            conn.execute("UPDATE tasks SET date_candidates_json=?, updated_at=? WHERE id=?",
                         (dumps(stored + [_cand_view(c) for c in added]), ts, task_id))
        for c in added:
            _add_evidence(conn, task_id, c)
        return task_id

    kinds = {c["kind"] for c in cands}
    is_non_task = kinds <= NON_TASK_KINDS
    # A date computed from a relative phrase ("within 5 days") is only a candidate, never official.
    explicit_dates = sorted({c["official_date_candidate"] for c in cands
                             if c.get("official_date_candidate") and c["kind"] not in NON_TASK_KINDS
                             and c.get("status") not in RELATIVE_STATUSES})
    has_conflict = any(c.get("status") in CONFLICT_STATUSES for c in cands)
    only_relative = not explicit_dates and any(c.get("status") in RELATIVE_STATUSES for c in cands)
    zones = sorted({c["timezone"] for c in cands if c.get("timezone")})

    official_date = official_time = None
    if is_non_task:
        deadline_status = "non_task"
    elif has_conflict or len(explicit_dates) > 1:
        deadline_status = "conflict"
    elif len(explicit_dates) == 1:
        official_date = explicit_dates[0]
        times = sorted({_end_time(c) for c in cands
                        if c.get("official_date_candidate") == official_date and _end_time(c)
                        and c["kind"] not in NON_TASK_KINDS})
        official_time = times[0] if len(times) == 1 else None
        deadline_status = "time_conflict" if len(times) > 1 else ("explicit" if official_time else "date_only")
    elif only_relative:
        deadline_status = "relative_unresolved"
    else:
        deadline_status = "missing"
    source_tz = zones[0] if len(zones) == 1 else None

    if is_non_task:
        status = "ignored"
    elif "deadline_in_completed_receipt" in kinds:
        status = "completed"
    else:
        status = "needs_review"
    required = 0 if kinds & {"conditional_deadline"} or is_non_task else 1
    deliverable = "exam" if kinds & {"exam_event", "exam_availability_window"} else (
        "reply" if "response_deadline" in kinds else "submission")

    task_id = new_id("task")
    conn.execute(
        """INSERT INTO tasks(id,entity_key,title,course,term,deliverable,required,status,official_date,official_time,
           source_timezone,deadline_status,date_candidates_json,estimated_minutes,missing_fields_json,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (task_id, entity_key, title or _humanize(entity_key), course or _course_from_key(entity_key), term,
         deliverable, required, status, official_date, official_time, source_tz, deadline_status,
         dumps([_cand_view(c) for c in cands]), None, "[]", ts, ts),
    )
    for c in cands:
        _add_evidence(conn, task_id, c)
    _refresh_derived(conn, task_id)
    audit(conn, "task_candidate_created", "task", task_id, {"origin": origin, "sources": len(cands)})
    return task_id


def _end_time(c: dict) -> str | None:
    if c["kind"] == "exam_availability_window":
        return c.get("window_end_time_candidate")
    return c.get("official_time_candidate")


def _cand_view(c: dict) -> dict:
    keys = ("candidate_id", "source_id", "kind", "official_date_candidate", "official_time_candidate", "timezone",
            "window_end_date_candidate", "window_end_time_candidate", "required_duration_minutes", "status",
            "interpretation_note", "annotation_status", "origin", "page")
    out = {k: c.get(k) for k in keys if k in c}
    out["source_id"] = c.get("source_id") or c.get("sample_id")
    return out


def _add_evidence(conn: sqlite3.Connection, task_id: str, c: dict) -> None:
    ev = c["evidence"]
    msg = conn.execute("SELECT id, body_view, subject, locator_json FROM messages WHERE id=?", (c["message_id"],)).fetchone()
    if not msg:
        return
    quote, start, end = ev["quote"], ev.get("start_char"), ev.get("end_char")
    field = {"subject": "subject", "user_excerpt": "user_excerpt"}.get(ev.get("field", ""), "body_view")
    if field == "subject":
        text = msg["subject"]
    elif field == "user_excerpt":
        # Pasted text is its own source; it is never presented as parsed PDF text.
        text = loads(msg["locator_json"], {}).get("user_excerpt", "")
    else:
        text = msg["body_view"]
    verified = start is not None and end is not None and text[start:end] == quote
    if not verified:
        idx = text.find(quote)
        start, end = (idx, idx + len(quote)) if idx >= 0 else (None, None)
    dup = conn.execute(
        "SELECT 1 FROM task_evidence WHERE task_id=? AND message_id=? AND quote=? AND IFNULL(start_char,-1)=IFNULL(?,-1)",
        (task_id, msg["id"], quote, start)).fetchone()
    if dup:
        return
    relation = {
        "deadline_update": "update", "deadline_in_completed_receipt": "completion_receipt",
        "relative_deadline": "relative", "conditional_deadline": "conditional",
    }.get(c["kind"], "supports")
    if c.get("status") in CONFLICT_STATUSES:
        relation = "conflict"
    locator = {"candidate_id": c.get("candidate_id"), "kind": c["kind"], "status": c.get("status"),
               "note": c.get("interpretation_note"), "origin": c.get("origin", "reference_annotation"),
               "quote_verified": start is not None}
    if c.get("page") is not None:
        locator["page"] = c["page"]
    if c.get("excerpt_origin"):
        locator["excerpt_origin"] = c["excerpt_origin"]
    changes = {}
    if c["kind"] == "deadline_update":
        changes = {"new_date": c.get("official_date_candidate"), "new_time": c.get("official_time_candidate")}
    conn.execute(
        """INSERT INTO task_evidence(id,task_id,message_id,field_name,quote,start_char,end_char,relation,locator_json,
           field_changes_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (new_id("ev"), task_id, msg["id"], field, quote, start, end, relation, dumps(locator), dumps(changes), now_iso()),
    )


# ---------------------------------------------------------------- user edits

EDITABLE = {"required", "official_date", "official_time", "source_timezone", "user_planning_cutoff",
            "estimated_minutes", "status", "title", "course", "term"}


def update_task(conn: sqlite3.Connection, task_id: str, patch: dict) -> dict:
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise not_found("task")
    if row["revision"] != patch.get("expected_revision"):
        raise conflict("REVISION_CONFLICT", "Task changed since it was loaded; reload before editing",
                       [f"current_revision={row['revision']}"])
    t = {k: row[k] for k in row.keys()}
    changes = {k: v for k, v in patch.items() if k in EDITABLE}
    if "official_time" in changes and changes["official_time"]:
        if not re.fullmatch(r"\d{2}:\d{2}", changes["official_time"]):
            raise AppError(422, "INVALID_TIME", "official_time must be HH:MM")
    if "official_date" in changes and changes["official_date"]:
        date.fromisoformat(changes["official_date"])
    if changes.get("source_timezone") and parse_zone(changes["source_timezone"]) is None:
        raise AppError(422, "INVALID_TIMEZONE", "Unknown timezone")
    if changes.get("user_planning_cutoff"):
        dt = datetime.fromisoformat(changes["user_planning_cutoff"])
        if dt.tzinfo is None:
            raise AppError(422, "CUTOFF_NEEDS_OFFSET", "user_planning_cutoff must include a UTC offset")
    if "required" in changes:
        changes["required"] = 1 if changes["required"] else 0
    t.update(changes)
    if {"official_date", "official_time"} & changes.keys() and t["deadline_status"] in {"conflict", "time_conflict", "relative_unresolved", "missing", "date_only"}:
        t["deadline_status"] = "user_confirmed" if t["official_date"] and t["official_time"] else t["deadline_status"]
    new_status = changes.get("status")
    if new_status == "confirmed" and compute_missing(t):
        raise AppError(422, "TASK_INCOMPLETE", "Task cannot be confirmed yet", compute_missing(t))
    sets = ", ".join(f"{k}=?" for k in changes) + (", " if changes else "")
    conn.execute(
        f"UPDATE tasks SET {sets}deadline_status=?, revision=revision+1, updated_at=? WHERE id=?",
        (*changes.values(), t["deadline_status"], now_iso(), task_id),
    )
    _refresh_derived(conn, task_id)
    audit(conn, "task_updated", "task", task_id, {"fields": sorted(changes)})
    return get_task(conn, task_id)


def record_progress(conn: sqlite3.Connection, task_id: str, body: dict) -> dict:
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        raise not_found("task")
    progress = loads(row["progress_json"], [])
    if any(p["client_event_id"] == body["client_event_id"] for p in progress):
        return get_task(conn, task_id)  # idempotent replay
    if row["revision"] != body["expected_revision"]:
        raise conflict("REVISION_CONFLICT", "Task changed since it was loaded", [f"current_revision={row['revision']}"])
    occurred = datetime.fromisoformat(body["occurred_at"])
    if occurred.tzinfo is None:
        raise AppError(422, "OCCURRED_AT_NEEDS_OFFSET", "occurred_at must include a UTC offset")
    minutes = int(body["minutes"])
    if body.get("undo_of"):
        minutes = -abs(minutes)
    progress.append({"client_event_id": body["client_event_id"], "minutes": minutes,
                     "occurred_at": occurred.isoformat(), "undo_of": body.get("undo_of")})
    completed = max(0, sum(p["minutes"] for p in progress))
    status = row["status"]
    if status == "confirmed" and completed > 0:
        status = "in_progress"
    conn.execute("UPDATE tasks SET progress_json=?, completed_minutes=?, status=?, revision=revision+1, updated_at=? WHERE id=?",
                 (dumps(progress), completed, status, now_iso(), task_id))
    audit(conn, "task_progress", "task", task_id, {"minutes": minutes})
    return get_task(conn, task_id)


def create_manual_task(conn: sqlite3.Connection, body: dict) -> dict:
    ts = now_iso()
    task_id = new_id("task")
    conn.execute(
        """INSERT INTO tasks(id,entity_key,title,course,term,deliverable,required,status,deadline_status,
           missing_fields_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (task_id, f"manual_{task_id}", body["title"].strip()[:200], body.get("course"), body.get("term"),
         "submission", 1, "needs_review", "missing", "[]", ts, ts),
    )
    if body.get("source_id") and body.get("evidence_quote"):
        msg = conn.execute("SELECT id FROM messages WHERE source_id=? OR id=?", (body["source_id"], body["source_id"])).fetchone()
        if msg:
            _add_evidence(conn, task_id, {"message_id": msg["id"], "kind": "manual", "origin": "user",
                                          "evidence": {"quote": body["evidence_quote"], "field": "body"}})
    _refresh_derived(conn, task_id)
    audit(conn, "task_created_manually", "task", task_id, {})
    return get_task(conn, task_id)
