"""W08 proposals: immutable payload + hash, bound to a source revision, a session and an expiry.

Confirmation is a single conditional UPDATE (pending_review -> executing); only one request can
win. Demo mode never calls a provider: it records 'simulated'. Live execution happens after the
claim is committed, through a fixed-purpose writer, never with text sent in the confirm request.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from ..config import settings
from ..db import audit, connect, dumps, loads, new_id, now_iso, transaction
from ..errors import AppError, conflict, not_found
from . import preferences
from .privacy import is_redacted_address, sha256_text

TTL_MINUTES = 15
OPEN_STATUSES = ("pending_review", "blocked")


def canonical(payload: dict) -> bytes:
    def check(v):
        if isinstance(v, float):
            raise ValueError("floats are not allowed in approval payloads")
        if isinstance(v, dict):
            for x in v.values():
                check(x)
        elif isinstance(v, list):
            for x in v:
                check(x)
        elif v is not None and not isinstance(v, (str, int, bool)):
            raise ValueError("non-JSON payload value")
    check(payload)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


def invalidate_for_source(conn: sqlite3.Connection, kind: str, object_id: str, reason: str) -> int:
    cur = conn.execute(
        f"UPDATE proposals SET status='invalidated', result_json=?, updated_at=? WHERE source_kind=? AND source_object_id=? "
        f"AND status IN {OPEN_STATUSES}",
        (dumps({"reason": reason}), now_iso(), kind, object_id))
    return cur.rowcount


# ---------------------------------------------------------------- payload builders

def _file_sha(upload_id: str) -> str | None:
    p = settings.upload_dir / f"{upload_id}.pdf"
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def _draft_payload(conn: sqlite3.Connection, draft_id: str, mode: str) -> tuple[dict, int, list[str], str | None]:
    from .draft_service import get_draft
    d = get_draft(conn, draft_id)
    blocking = [f for f in d["missing_fields"]]
    src = None
    if d["source_message_id"]:
        src = conn.execute("SELECT source_id, connection_id, thread_id, provider_message_id FROM messages WHERE id=?",
                           (d["source_message_id"],)).fetchone()
    attachments = []
    for a in d["attachments"]:
        current = _file_sha(a["id"])  # bind current content, not the name
        if current is None:
            blocking.append(f"attachment_missing:{a['name']}")
        attachments.append({"id": a["id"], "name": a["name"], "size_bytes": a["size_bytes"], "sha256": current or ""})
    if d["channel"] == "teams":
        op = "send_chat"
        payload = {"operation": op, "mode": mode, "chat_id": d["verified_facts"].get("chat_id") or "demo_chat",
                   "body": d["body"]}
    else:
        op = "send_email"
        payload = {"operation": op, "mode": mode, "connection_id": d["connection_id"] or (src["connection_id"] if src else None),
                   "to": d["to"], "cc": d["cc"], "bcc": d["bcc"], "subject": d["subject"], "body": d["body"],
                   "attachments": attachments, "reply_to_source_id": src["source_id"] if src else None,
                   # Keep a real reply in the original conversation (Gmail threadId + RFC 5322 reply headers).
                   "thread_id": src["thread_id"] if src else None,
                   "reply_to_provider_message_id": src["provider_message_id"] if src else None,
                   "style_reference_ids": d["style_reference_ids"]}
    if mode == "live":
        for a in d["to"] + d["cc"] + d["bcc"]:
            if is_redacted_address(a):
                blocking.append(f"deidentified_recipient:{a}")
        if src and src["connection_id"].startswith("conn_local"):
            blocking.append("sample_source_has_no_writable_account")
    return payload, d["revision"], blocking, op


def _plan_payload(conn: sqlite3.Connection, plan_id: str, mode: str) -> tuple[dict, int, list[str], str]:
    from .plan_service import get_plan, study_calendar_target
    p = get_plan(conn, plan_id)
    target = study_calendar_target(conn, p)
    blocking = []
    if p["status"] != "feasible":
        blocking.append(f"plan_status:{p['status']}")
    blocking += [f"stale:{r}" for r in p["stale_reasons"]]
    payload = {"operation": "create_study_events", "mode": mode, "plan_id": plan_id,
               # The account whose app-created study calendar receives the new blocks; shown in the review.
               "connection_id": f"conn_{target}", "calendar_provider": target,
               "calendar": "app_study_calendar", "timezone": p["inputs"].get("display_timezone"),
               "attendees": [],
               "events": [{"task_id": s["task_id"], "title": f"Study: {s['task_title']}", "start": s["start"],
                           "end": s["end"]} for s in p["sessions"] if not s.get("kept")],
               # Already-written blocks this plan moves: their old events are removed after the new ones exist.
               "remove_events": [{"event_id": x["event_id"], "task_id": x["task_id"], "start": x["start"], "end": x["end"],
                                  "provider": x.get("provider") or "google"}
                                 for x in p["inputs"].get("remove_written", [])]}
    if mode == "live":
        if p["synthetic"]:
            blocking.append("synthetic_plan_not_live")
        if not payload["events"] and not payload["remove_events"]:
            blocking.append("no_new_study_sessions")
        if any(datetime.fromisoformat(ev["start"]) <= datetime.now(timezone.utc) for ev in payload["events"]):
            blocking.append("past_study_session")
    return payload, p["revision"], blocking, "create_study_events"


def _live_blockers(conn: sqlite3.Connection, op: str, payload: dict) -> list[str]:
    out = []
    prefs, _ = preferences.get_raw(conn)
    if settings.app_mode != "live":
        out.append("app_mode_is_demo")
    if not settings.enable_external_writes:
        out.append("external_writes_disabled_by_server_config")
    if not prefs.get("enable_external_writes"):
        out.append("external_writes_disabled_in_settings")
    from ..providers import writers
    out += writers.capability_blockers(conn, op, payload)
    return out


def _build(conn, source_kind, object_id, mode):
    if source_kind == "draft":
        return _draft_payload(conn, object_id, mode)
    if source_kind == "plan":
        return _plan_payload(conn, object_id, mode)
    if source_kind == "connection":
        row = conn.execute("SELECT revision FROM connections WHERE id=?", (object_id,)).fetchone()
        if not row or object_id not in ("conn_google", "conn_microsoft"):
            raise AppError(422, "UNSUPPORTED_SOURCE", "A study calendar is created on a connected Google or Outlook account")
        prefs, _ = preferences.get_raw(conn)
        payload = {"operation": "create_study_calendar", "mode": mode, "connection_id": object_id,
                   "summary": "Track4 学习计划 / study plan", "timezone": prefs["display_timezone"]}
        return payload, row["revision"], [], "create_study_calendar"
    raise AppError(422, "UNSUPPORTED_SOURCE", "Proposals are built from drafts or plans")


def view(row: sqlite3.Row) -> dict:
    status = row["status"]
    if status == "pending_review" and datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        status = "expired"
    result = loads(row["result_json"], None)
    return {"id": row["id"], "mode": row["mode"], "operation": row["operation"], "status": status,
            "source_kind": row["source_kind"], "source_object_id": row["source_object_id"],
            "source_revision": row["source_revision"], "revision": row["revision"],
            "payload_hash": row["payload_hash"], "payload": loads(row["payload_json"], {}),
            "expires_at": row["expires_at"], "blocking_fields": loads(row["dependencies_json"], {}).get("blocking", []),
            "result": result, "created_at": row["created_at"]}


def create(conn: sqlite3.Connection, body: dict, session) -> dict:
    mode = body.get("mode", "demo")
    payload, source_rev, blocking, op = _build(conn, body["source_kind"], body["source_object_id"], mode)
    if body.get("operation") and body["operation"] != op:
        raise AppError(422, "OPERATION_MISMATCH", f"This source produces {op}")
    if source_rev != body["expected_source_revision"]:
        raise conflict("SOURCE_CHANGED", "Source changed since it was shown; reload",
                       [f"current_revision={source_rev}"])
    if mode == "live":
        blocking += _live_blockers(conn, op, payload)
    invalidate_for_source(conn, body["source_kind"], body["source_object_id"], "superseded_by_new_proposal")
    pid, ts = new_id("prop"), now_iso()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=TTL_MINUTES)).replace(microsecond=0).isoformat()
    conn.execute(
        """INSERT INTO proposals(id,session_id_hash,operation,mode,connection_id,source_kind,source_object_id,source_revision,
           dependencies_json,payload_json,payload_hash,nonce_hash,expires_at,status,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, session.id_hash, op, mode, None, body["source_kind"], body["source_object_id"], source_rev,
         dumps({"blocking": blocking}), dumps(payload), payload_hash(payload), sha256_text(secrets.token_hex(16)),
         expires, "blocked" if blocking else "pending_review", ts, ts))
    audit(conn, "proposal_created", "proposal", pid, {"operation": op, "mode": mode, "blocked": len(blocking)})
    return view(conn.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone())


def get(conn: sqlite3.Connection, pid: str) -> dict:
    row = conn.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
    if not row:
        raise not_found("proposal")
    return view(row)


def cancel(conn: sqlite3.Connection, pid: str, expected_revision: int) -> dict:
    cur = conn.execute("UPDATE proposals SET status='cancelled', revision=revision+1, updated_at=? WHERE id=? AND revision=? "
                       f"AND status IN {OPEN_STATUSES}", (now_iso(), pid, expected_revision))
    if cur.rowcount != 1:
        p = get(conn, pid)
        raise conflict("PROPOSAL_NOT_CANCELLABLE", "Proposal is not open or changed", [p["status"]])
    audit(conn, "proposal_cancelled", "proposal", pid, {})
    return get(conn, pid)


def confirm(pid: str, body: dict, session, idempotency_key: str) -> dict:
    """Validate, claim exactly once, commit, then execute outside the write transaction."""
    if not idempotency_key or len(idempotency_key) > 120:
        raise AppError(422, "IDEMPOTENCY_KEY_REQUIRED", "Send an Idempotency-Key header")
    with connect() as conn:
        with transaction(conn):
            same = conn.execute("SELECT * FROM proposals WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if same:
                if same["id"] != pid:
                    raise conflict("IDEMPOTENCY_KEY_REUSED", "Key already used for another proposal")
                return view(same)  # replay: report the recorded state, never execute again
            row = conn.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
            if not row:
                raise not_found("proposal")
            p = view(row)
            if p["status"] != "pending_review":
                raise conflict("PROPOSAL_NOT_PENDING", "Proposal cannot be confirmed", [p["status"]])
            if row["revision"] != body["expected_revision"]:
                raise conflict("PROPOSAL_CHANGED", "Proposal revision changed")
            if not secrets.compare_digest(row["session_id_hash"], session.id_hash):
                raise AppError(403, "WRONG_SESSION", "Proposal was created in another session; review it again")
            current, rev, blocking, _ = _build(conn, row["source_kind"], row["source_object_id"], row["mode"])
            if row["mode"] == "live":
                blocking += _live_blockers(conn, row["operation"], current)
            stored = row["payload_hash"]
            changed = rev != row["source_revision"] or payload_hash(current) != stored
            if changed or blocking:
                conn.execute("UPDATE proposals SET status='invalidated', result_json=?, updated_at=? WHERE id=?",
                             (dumps({"reason": "content_changed" if changed else "now_blocked", "blocking": blocking}),
                              now_iso(), pid))
                audit(conn, "proposal_invalidated", "proposal", pid, {"changed": changed})
                return get(conn, pid)
            if not secrets.compare_digest(body["payload_hash"], stored):
                raise conflict("PAYLOAD_HASH_MISMATCH", "The reviewed payload is not the stored one; review again")
            op_id = str(uuid.uuid4())
            ts = now_iso()
            cur = conn.execute(
                """UPDATE proposals SET status='executing', execution_operation_id=?, idempotency_key=?, approved_at=?,
                   consumed_at=?, updated_at=? WHERE id=? AND status='pending_review' AND revision=?""",
                (op_id, idempotency_key, ts, ts, ts, pid, row["revision"]))
            if cur.rowcount != 1:
                raise conflict("ALREADY_CLAIMED", "Another request already confirmed this proposal")
            audit(conn, "proposal_approved", "proposal", pid, {"operation": row["operation"], "mode": row["mode"]})
            payload, mode, op = loads(row["payload_json"], {}), row["mode"], row["operation"]

        # Claim committed. Execute with the stored payload only.
        if mode == "demo":
            status, result = "simulated", {"simulated": True, "external_call": False, "operation_id": op_id}
        else:
            stop = recheck_busy_before_write(conn, payload) if op == "create_study_events" else None
            if stop:
                # Nothing is written. This approval is used up; a new plan needs a new review.
                status, result = "invalidated", {**stop, "external_call": False, "operation_id": op_id}
            else:
                from ..providers import writers
                status, result = writers.execute(op, payload, op_id)
        with transaction(conn):
            conn.execute("UPDATE proposals SET status=?, result_json=?, updated_at=? WHERE id=?",
                         (status, dumps(result), now_iso(), pid))
            audit(conn, "proposal_executed", "proposal", pid, {"status": status})
        return get(conn, pid)


def recheck_busy_before_write(conn: sqlite3.Connection, payload: dict) -> dict | None:
    """Read free/busy again just before study events are written. The calendar may have changed after the
    preview (a meeting added inside the 5-minute snapshot window). Returns None when it is safe to write, or the
    reason to stop: a new conflict, or a re-read that did not fully succeed (never treated as free time).
    This narrows the race window; it cannot rule out a change made between this read and the write itself."""
    from ..providers import calendars
    from .plan_service import get_plan, get_snapshot, study_calendars
    events = payload.get("events") or []
    if not events:
        return None  # only removals: nothing new can collide
    plan = get_plan(conn, payload["plan_id"])
    snap = get_snapshot(conn, plan["inputs"]["snapshot_id"])
    starts = [datetime.fromisoformat(e["start"]) for e in events]
    ends = [datetime.fromisoformat(e["end"]) for e in events]
    t0, t1 = min(starts), max(ends)
    tz = payload.get("timezone") or snap["display_timezone"]
    reads = [(snap["provider"], snap.get("connection_id"), snap.get("calendar_ids") or ["primary"], False)]
    if snap.get("study_calendar", {}).get("status") == "complete":
        for prov, cal in study_calendars(conn):  # also catches events added to a study calendar by hand
            reads.append((prov, f"conn_{prov}", [cal], True))
    from .plan_service import _subtract_intervals
    busy: list[tuple[datetime, datetime]] = []
    for provider, cid, ids, own in reads:
        try:
            res = calendars.read_busy(conn, provider, cid, t0, t1, tz, ids)
        except Exception as exc:  # noqa: BLE001 - a failed re-read stops the write
            return {"reason": "busy_recheck_failed", "errors": [type(exc).__name__]}
        if res["status"] != "complete":
            return {"reason": "busy_recheck_failed", "errors": res.get("errors", [])}
        got = [(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])) for b in res["busy"]]
        moving = [(datetime.fromisoformat(x["start"]), datetime.fromisoformat(x["end"]))
                  for x in payload.get("remove_events", []) if (x.get("provider") or "google") == provider]
        if own and moving:
            # The old events of blocks being moved are still in the study calendar until this write removes them.
            # An event in the other provider cannot explain busy time in this calendar.
            got = [piece for iv in got for piece in _subtract_intervals(iv, moving)]
        busy += got
    conflicts = [{"event_start": e["start"], "event_end": e["end"], "busy_start": bs.isoformat(), "busy_end": be.isoformat()}
                 for e, s, en in zip(events, starts, ends) for bs, be in busy if s < be and bs < en]
    if not conflicts:
        return None
    # Force a fresh plan: the snapshot behind this plan no longer reflects the calendar.
    conn.execute("UPDATE calendar_snapshots SET expires_at=? WHERE id=?", (now_iso(), snap["id"]))
    audit(conn, "study_write_stopped_conflict", "plan", payload["plan_id"], {"conflicts": len(conflicts)})
    return {"reason": "calendar_conflict", "conflicts": conflicts}
