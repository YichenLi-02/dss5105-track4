"""Fixed-purpose external writers. Only proposal_service.confirm() calls execute(), after a
committed single-use claim, with the stored payload. Exactly one provider call per operation;
no generic retry. Timeouts / 5xx become 'unknown' (verify before any new attempt).
"""
from __future__ import annotations

import base64
import hashlib
import sqlite3
from email.message import EmailMessage

import httpx

from ..config import settings
from ..db import connect, loads
from ..services.privacy import is_redacted_address
from . import net, oauth

OP_CAPABILITY = {"send_email": "send_mail", "send_chat": "send_chat", "create_study_events": "study_calendar",
                 "create_study_calendar": "study_calendar"}


def _provider_for(payload: dict, op: str) -> str | None:
    cid = payload.get("connection_id")
    if op == "send_chat":
        return "microsoft"
    if cid in ("conn_google", "conn_microsoft"):
        return cid.split("_", 1)[1]
    if op in ("create_study_events", "create_study_calendar"):
        return "google"
    return None


def capability_blockers(conn: sqlite3.Connection, op: str, payload: dict) -> list[str]:
    out = []
    provider = _provider_for(payload, op)
    if not provider:
        return ["no_real_account_for_this_draft"]
    if not oauth.has_scope(conn, provider, OP_CAPABILITY[op]):
        out.append(f"missing_permission:{provider}:{OP_CAPABILITY[op]}")
    if op == "send_email":
        out += [f"deidentified_recipient:{a}" for a in payload.get("to", []) + payload.get("cc", []) + payload.get("bcc", [])
                if is_redacted_address(a)]
        if not payload.get("to"):
            out.append("recipients:to")
    if op == "send_chat" and payload.get("chat_id") in (None, "", "demo_chat"):
        out.append("verified_chat_id_required")
    if op == "create_study_events":
        cal = _app_calendar_id(conn)
        if not cal:
            out.append("create_study_calendar_first")
    return out


def _app_calendar_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT cursor_json FROM connections WHERE id='conn_google'").fetchone()
    return loads(row[0], {}).get("app_calendar_id") if row else None


def _classify(r: httpx.Response) -> str:
    if r.status_code in (200, 201):
        return "executed"
    if r.status_code == 202:
        return "accepted"  # accepted for processing is not proof of delivery
    if 400 <= r.status_code < 500 and r.status_code != 408:
        return "failed"
    return "unknown"


def _mime(payload: dict) -> bytes:
    msg = EmailMessage()
    msg["To"] = ", ".join(payload["to"])
    if payload.get("cc"):
        msg["Cc"] = ", ".join(payload["cc"])
    if payload.get("bcc"):
        msg["Bcc"] = ", ".join(payload["bcc"])
    msg["Subject"] = payload["subject"]
    msg.set_content(payload["body"])
    for a in payload.get("attachments", []):
        data = (settings.upload_dir / f"{a['id']}.pdf").read_bytes()
        if hashlib.sha256(data).hexdigest() != a["sha256"]:
            raise ValueError("attachment content changed after approval")
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=a["name"])
    return msg.as_bytes()


def execute(op: str, payload: dict, operation_id: str) -> tuple[str, dict]:
    with connect() as conn:
        provider = _provider_for(payload, op)
        try:
            token = oauth.access_token(conn, provider)
        except Exception as exc:  # noqa: BLE001 - nothing was sent
            return "failed", {"reason": "no_valid_token", "detail": getattr(exc, "code", type(exc).__name__)}
        auth = {"Authorization": f"Bearer {token}"}
        try:
            if op == "send_email" and provider == "google":
                raw = base64.urlsafe_b64encode(_mime(payload)).decode()
                r = net.request("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                                headers=auth, json={"raw": raw})
                status = _classify(r)
                return status, {"http_status": r.status_code, "provider_id": r.json().get("id") if status == "executed" else None,
                                "operation_id": operation_id}
            if op == "send_email" and provider == "microsoft":
                msg = {"subject": payload["subject"], "body": {"contentType": "Text", "content": payload["body"]},
                       "toRecipients": [{"emailAddress": {"address": a}} for a in payload["to"]],
                       "ccRecipients": [{"emailAddress": {"address": a}} for a in payload.get("cc", [])],
                       "bccRecipients": [{"emailAddress": {"address": a}} for a in payload.get("bcc", [])]}
                r = net.request("POST", "https://graph.microsoft.com/v1.0/me/sendMail", headers=auth,
                                json={"message": msg, "saveToSentItems": True})
                return _classify(r), {"http_status": r.status_code, "operation_id": operation_id}
            if op == "send_chat":
                r = net.request("POST", f"https://graph.microsoft.com/v1.0/chats/{payload['chat_id']}/messages",
                                headers=auth, json={"body": {"contentType": "text", "content": payload["body"]}})
                return _classify(r), {"http_status": r.status_code, "operation_id": operation_id}
            if op == "create_study_calendar":
                r = net.request("POST", "https://www.googleapis.com/calendar/v3/calendars", headers=auth,
                                json={"summary": payload.get("summary", "Track4 study plan"),
                                      "timeZone": payload.get("timezone", "Asia/Singapore")})
                status = _classify(r)
                if status == "executed":
                    from ..db import dumps, transaction
                    with transaction(conn):
                        row = conn.execute("SELECT cursor_json FROM connections WHERE id='conn_google'").fetchone()
                        cur = loads(row[0], {})
                        cur["app_calendar_id"] = r.json()["id"]
                        conn.execute("UPDATE connections SET cursor_json=? WHERE id='conn_google'", (dumps(cur),))
                return status, {"http_status": r.status_code, "operation_id": operation_id}
            if op == "create_study_events":
                cal = _app_calendar_id(conn)
                results, overall = [], "executed"
                for i, ev in enumerate(payload["events"]):
                    event_id = hashlib.sha256(f"{operation_id}:{i}".encode()).hexdigest()[:40]
                    r = net.request("POST", f"https://www.googleapis.com/calendar/v3/calendars/{cal}/events", headers=auth,
                                    json={"id": event_id, "summary": ev["title"],
                                          "start": {"dateTime": ev["start"], "timeZone": payload["timezone"]},
                                          "end": {"dateTime": ev["end"], "timeZone": payload["timezone"]},
                                          "extendedProperties": {"private": {"operation_id": operation_id,
                                                                             "task_id": ev["task_id"]}}})
                    st = "executed" if r.status_code in (200, 201) else ("executed" if r.status_code == 409 else _classify(r))
                    results.append({"event_id": event_id, "status": st, "http_status": r.status_code})
                    if st != "executed":
                        overall = "unknown" if st == "unknown" else "failed"
                        break  # stop; no automatic rollback of created events
                return overall, {"events": results, "operation_id": operation_id, "partial": overall != "executed"}
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return "unknown", {"reason": "no_definite_response", "detail": type(exc).__name__, "operation_id": operation_id}
        except ValueError as exc:
            return "failed", {"reason": str(exc), "operation_id": operation_id}
    return "failed", {"reason": "unsupported_operation"}
