"""Fixed-purpose external writers. Only proposal_service.confirm() calls execute(), after a
committed single-use claim, with the stored payload. Exactly one provider call per operation;
no generic retry. Timeouts / 5xx become 'unknown' (verify before any new attempt).
"""
from __future__ import annotations

import base64
import hashlib
import sqlite3
from datetime import datetime, timezone
from email.message import EmailMessage
from urllib.parse import quote

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
        if not app_calendar_id(conn, provider):
            out.append("create_study_calendar_first")
        for p in sorted({rm.get("provider") or "google" for rm in payload.get("remove_events", [])} - {provider}):
            if not oauth.has_scope(conn, p, "study_calendar"):  # an old block lives in the other account's study calendar
                out.append(f"missing_permission:{p}:study_calendar")
    if op == "create_study_calendar" and app_calendar_id(conn, provider):
        out.append("study_calendar_exists")
    return out


def app_calendar_id(conn: sqlite3.Connection, provider: str = "google") -> str | None:
    """The study calendar this app created in that account (the only calendar it ever writes to)."""
    row = conn.execute("SELECT cursor_json FROM connections WHERE id=?", (f"conn_{provider}",)).fetchone()
    return loads(row[0], {}).get("app_calendar_id") if row else None


_app_calendar_id = app_calendar_id  # earlier name


def _save_calendar_id(conn: sqlite3.Connection, provider: str, cal_id: str) -> None:
    from ..db import dumps, transaction
    with transaction(conn):
        row = conn.execute("SELECT cursor_json FROM connections WHERE id=?", (f"conn_{provider}",)).fetchone()
        cur = loads(row[0], {})
        cur["app_calendar_id"] = cal_id
        conn.execute("UPDATE connections SET cursor_json=? WHERE id=?", (dumps(cur), f"conn_{provider}"))


GRAPH = "https://graph.microsoft.com/v1.0"


def _graph_study_events(cal: str) -> str:
    # Every Outlook write goes through this path: events inside the app's own study calendar, nothing else.
    return f"{GRAPH}/me/calendars/{quote(cal, safe='')}/events"


def _graph_time(iso: str) -> dict:
    """Graph wants a local date-time plus a zone name; UTC avoids any Windows/IANA zone-name mismatch."""
    return {"dateTime": datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "UTC"}


def _create_event(provider: str, auth: dict, cal: str, payload: dict, ev: dict, key: str, operation_id: str):
    """-> (status, event id, http status). key is stable per proposal and event, so a retry cannot duplicate it."""
    if provider == "microsoft":
        r = net.request("POST", _graph_study_events(cal), headers=auth, json={
            "subject": ev["title"], "start": _graph_time(ev["start"]), "end": _graph_time(ev["end"]),
            "showAs": "busy", "isReminderOn": False, "attendees": [], "transactionId": key,
            "body": {"contentType": "text", "content": "Study block planned and reviewed in the Track4 study assistant."}})
        st = "executed" if r.status_code in (200, 201) else _classify(r)
        return st, (r.json().get("id") if st == "executed" else None), r.status_code
    r = net.request("POST", f"https://www.googleapis.com/calendar/v3/calendars/{cal}/events", headers=auth,
                    json={"id": key, "summary": ev["title"],
                          "start": {"dateTime": ev["start"], "timeZone": payload["timezone"]},
                          "end": {"dateTime": ev["end"], "timeZone": payload["timezone"]},
                          "extendedProperties": {"private": {"operation_id": operation_id, "task_id": ev["task_id"]}}})
    st = "executed" if r.status_code in (200, 201, 409) else _classify(r)  # 409: this exact event already exists
    return st, key, r.status_code


def _delete_event(provider: str, auth: dict, cal: str, event_id: str):
    if provider == "microsoft":
        r = net.request("DELETE", f"{_graph_study_events(cal)}/{quote(event_id, safe='')}", headers=auth)
    else:
        r = net.request("DELETE", f"https://www.googleapis.com/calendar/v3/calendars/{cal}/events/"
                        f"{quote(event_id, safe='')}", headers=auth)
    return r


def _classify(r: httpx.Response) -> str:
    if r.status_code in (200, 201):
        return "executed"
    if r.status_code == 202:
        return "accepted"  # accepted for processing is not proof of delivery
    if 400 <= r.status_code < 500 and r.status_code != 408:
        return "failed"
    return "unknown"


def _mime(payload: dict, reply_headers: dict | None = None) -> bytes:
    msg = EmailMessage()
    for k, v in (reply_headers or {}).items():
        msg[k] = v
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


GRAPH_INLINE_ATTACHMENT_LIMIT = 3 * 1024 * 1024  # sendMail request body must stay under 4 MB after base64


def _graph_attachments(payload: dict) -> list[dict]:
    """fileAttachment items for Graph sendMail, bound to the content hash that was approved."""
    out, total = [], 0
    for a in payload.get("attachments", []):
        data = (settings.upload_dir / f"{a['id']}.pdf").read_bytes()
        if hashlib.sha256(data).hexdigest() != a["sha256"]:
            raise ValueError("attachment content changed after approval")
        total += len(data)
        if total > GRAPH_INLINE_ATTACHMENT_LIMIT:
            raise ValueError("attachments_too_large_for_outlook_send (limit 3 MB)")
        out.append({"@odata.type": "#microsoft.graph.fileAttachment", "name": a["name"],
                    "contentType": "application/pdf", "contentBytes": base64.b64encode(data).decode()})
    return out


def _gmail_reply_headers(auth: dict, payload: dict) -> dict:
    """In-Reply-To/References of the original mail (read-only lookup). Missing headers only lose threading."""
    mid = payload.get("reply_to_provider_message_id")
    if not mid:
        return {}
    try:
        r = net.request("GET", f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}", headers=auth,
                        params={"format": "metadata", "metadataHeaders": ["Message-ID", "References"]})
        if r.status_code != 200:
            return {}
        h = {x["name"].lower(): x["value"] for x in r.json().get("payload", {}).get("headers", [])}
    except (httpx.HTTPError, ValueError):
        return {}
    if not h.get("message-id"):
        return {}
    return {"In-Reply-To": h["message-id"], "References": (h.get("references", "") + " " + h["message-id"]).strip()}


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
                raw = base64.urlsafe_b64encode(_mime(payload, _gmail_reply_headers(auth, payload))).decode()
                body = {"raw": raw}
                if payload.get("thread_id"):
                    body["threadId"] = payload["thread_id"]
                r = net.request("POST", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                                headers=auth, json=body)
                status = _classify(r)
                return status, {"http_status": r.status_code, "provider_id": r.json().get("id") if status == "executed" else None,
                                "operation_id": operation_id}
            if op == "send_email" and provider == "microsoft":
                # sendMail sends exactly the reviewed recipients, subject, body and attachments in one call.
                msg = {"subject": payload["subject"], "body": {"contentType": "Text", "content": payload["body"]},
                       "toRecipients": [{"emailAddress": {"address": a}} for a in payload["to"]],
                       "ccRecipients": [{"emailAddress": {"address": a}} for a in payload.get("cc", [])],
                       "bccRecipients": [{"emailAddress": {"address": a}} for a in payload.get("bcc", [])]}
                attachments = _graph_attachments(payload)  # ValueError -> failed, nothing sent
                if attachments:
                    msg["attachments"] = attachments
                r = net.request("POST", "https://graph.microsoft.com/v1.0/me/sendMail", headers=auth,
                                json={"message": msg, "saveToSentItems": True})
                return _classify(r), {"http_status": r.status_code, "operation_id": operation_id}
            if op == "send_chat":
                r = net.request("POST", f"https://graph.microsoft.com/v1.0/chats/{payload['chat_id']}/messages",
                                headers=auth, json={"body": {"contentType": "text", "content": payload["body"]}})
                return _classify(r), {"http_status": r.status_code, "operation_id": operation_id}
            if op == "create_study_calendar":
                name = payload.get("summary", "Track4 study plan")
                if provider == "microsoft":
                    r = net.request("POST", f"{GRAPH}/me/calendars", headers=auth, json={"name": name})
                else:
                    r = net.request("POST", "https://www.googleapis.com/calendar/v3/calendars", headers=auth,
                                    json={"summary": name, "timeZone": payload.get("timezone", "Asia/Singapore")})
                status = _classify(r)
                if status == "executed":
                    _save_calendar_id(conn, provider, r.json()["id"])
                out = {"http_status": r.status_code, "operation_id": operation_id}
                if provider == "microsoft" and r.status_code == 409:
                    out["reason"] = "calendar_name_exists"  # an Outlook calendar with this name is already there
                return status, out
            if op == "create_study_events":
                cal = app_calendar_id(conn, provider)
                results, overall = [], "executed"
                for i, ev in enumerate(payload["events"]):
                    key = hashlib.sha256(f"{operation_id}:{i}".encode()).hexdigest()[:40]
                    st, event_id, http = _create_event(provider, auth, cal, payload, ev, key, operation_id)
                    results.append({"event_id": event_id, "status": st, "http_status": http})
                    if st != "executed":
                        overall = "unknown" if st == "unknown" else "failed"
                        break  # stop; no automatic rollback of created events
                removed = []
                if overall == "executed":
                    # Moving a written block = the new event exists first, then the old one (an event this app created
                    # in its own study calendar, in whichever account it was written) is deleted. Nothing in the
                    # person's other calendars is touched.
                    auths = {provider: auth}
                    for rm in payload.get("remove_events", []):
                        rp = rm.get("provider") or "google"
                        if rp not in auths:
                            try:
                                auths[rp] = {"Authorization": f"Bearer {oauth.access_token(conn, rp)}"}
                            except Exception as exc:  # noqa: BLE001 - no token: the old block is left alone
                                removed.append({"event_id": rm["event_id"], "status": "failed",
                                                "detail": getattr(exc, "code", type(exc).__name__)})
                                overall = "failed"
                                break
                        old_cal = app_calendar_id(conn, rp)
                        if not old_cal:  # never guess a calendar, and never report an undeleted event as gone
                            removed.append({"event_id": rm["event_id"], "status": "failed", "detail": "study_calendar_unknown"})
                            overall = "failed"
                            break
                        try:
                            r = _delete_event(rp, auths[rp], old_cal, rm["event_id"])
                            st = ("executed" if r.status_code in (200, 204) else
                                  "already_gone" if r.status_code in (404, 410) else _classify(r))
                            removed.append({"event_id": rm["event_id"], "status": st, "http_status": r.status_code})
                        except (httpx.TimeoutException, httpx.TransportError) as exc:
                            st = "unknown"
                            removed.append({"event_id": rm["event_id"], "status": st, "detail": type(exc).__name__})
                        if st not in ("executed", "already_gone"):
                            overall = "unknown" if st == "unknown" else "failed"
                            break
                out = {"events": results, "removed": removed, "operation_id": operation_id, "partial": overall != "executed"}
                if overall != "executed" and removed and all(x["status"] == "executed" for x in results):
                    out["reason"] = "old_event_not_removed"  # new blocks exist; the old one is still in the calendar
                return overall, out
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return "unknown", {"reason": "no_definite_response", "detail": type(exc).__name__, "operation_id": operation_id}
        except ValueError as exc:
            return "failed", {"reason": str(exc), "operation_id": operation_id}
    return "failed", {"reason": "unsupported_operation"}
