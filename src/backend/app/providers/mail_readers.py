"""Read-only mail sync: Gmail (gmail.readonly) and Outlook / Microsoft 365 (Graph Mail.Read).

Minimise before storing: plain text only (HTML stripped, no remote images), addresses/codes/IDs
scrubbed, attachments kept as metadata. Dedupe by (connection_id, provider_message_id).
The page cursor only advances after the page is stored.
"""
from __future__ import annotations

import base64
import html
import re
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

from ..db import dumps, loads, now_iso, transaction
from ..errors import AppError
from ..services.import_service import message_uuid
from ..services.privacy import scrub, sha256_text
from . import net, oauth

MAX_BODY = 20000
GRAPH = "https://graph.microsoft.com/v1.0"
# Plain-text bodies (no HTML, no remote images) and IDs that stay the same when a mail is moved between folders,
# so dedupe and later replies keep pointing at the same message.
OUTLOOK_PREFER = 'outlook.body-content-type="text", IdType="ImmutableId"'
OUTLOOK_SELECT = "id,conversationId,from,sender,toRecipients,subject,receivedDateTime,body,hasAttachments,webLink"
OUTLOOK_WEB_HOSTS = {"outlook.office.com", "outlook.office365.com", "outlook.live.com"}


def html_to_text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", s)).strip()


def _b64(data: str) -> str:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode("utf-8", errors="replace")


def _gmail_parts(payload: dict) -> tuple[str, list[dict]]:
    plain, htm, atts = [], [], []

    def walk(p):
        mime = p.get("mimeType", "")
        body = p.get("body", {})
        if p.get("filename"):
            atts.append({"name": p["filename"], "size": body.get("size", 0), "content_read": False})
        elif mime == "text/plain" and body.get("data"):
            plain.append(_b64(body["data"]))
        elif mime == "text/html" and body.get("data"):
            htm.append(_b64(body["data"]))
        for c in p.get("parts", []) or []:
            walk(c)
    walk(payload)
    text = "\n".join(plain) if plain else html_to_text("\n".join(htm))
    return text, atts


def _get(url: str, token: str, params=None, attempts: int = 3, extra_headers=None):
    """Bounded retry for reads only; honours Retry-After. Writes never use this."""
    for i in range(attempts):
        r = net.request("GET", url, params=params, headers={"Authorization": f"Bearer {token}", **(extra_headers or {})})
        if r.status_code == 429 or r.status_code >= 500:
            wait = min(int(r.headers.get("Retry-After", 2 ** i)), 30)
            time.sleep(wait)
            continue
        return r
    return r


def _store(conn, cid, provider_id, thread, subject, sender, to, sent_at, body, atts, locator_extra=None,
           direction="inbound") -> bool:
    mid = message_uuid(cid, provider_id)
    if conn.execute("SELECT 1 FROM messages WHERE id=?", (mid,)).fetchone():
        return False
    body = scrub(body.replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10)))[:MAX_BODY]
    # Short reference id used for evidence and model task keys. Gmail ids are short and unique; Graph ids are
    # ~150 chars and share a long mailbox prefix, so a prefix would collide - hash those instead.
    source_id = provider_id if len(provider_id) <= 24 else "msg_" + sha256_text(provider_id)[:16]
    ts = now_iso()
    conn.execute(
        """INSERT INTO messages(id,connection_id,provider_message_id,source_type,source_id,thread_id,direction,subject,
           sender_json,recipients_json,sent_at,body_view,body_hash,locator_json,attachments_json,analysis_status,
           analysis_origin,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (mid, cid, provider_id, "email", source_id, thread, direction, scrub(subject)[:300],
         dumps({"label": scrub(sender)}), dumps({"to": [scrub(x) for x in to]}), sent_at, body, sha256_text(body),
         dumps({"provider": cid, "body_view": "plain_text_minimised", **(locator_extra or {})}), dumps(atts),
         "pending", "none", ts, ts))
    return True


def sync(ctx, payload: dict) -> dict:
    conn: sqlite3.Connection = ctx.conn
    cid = payload["connection_id"]
    provider = "google" if cid == "conn_google" else "microsoft" if cid == "conn_microsoft" else None
    if not provider or not oauth.has_scope(conn, provider, "read_mail"):
        raise AppError(409, "READ_SCOPE_MISSING", "This connection has no read-mail permission")
    token = oauth.access_token(conn, provider)
    days, limit = payload["lookback_days"], payload["max_messages"]
    created = fetched = skipped = 0
    if provider == "google":
        page, ids = None, []
        while len(ids) < limit:
            params = {"maxResults": min(50, limit - len(ids)), "q": f"newer_than:{days}d",
                      "includeSpamTrash": str(bool(payload.get("include_spam_trash"))).lower()}
            if page:
                params["pageToken"] = page
            r = _get("https://gmail.googleapis.com/gmail/v1/users/me/messages", token, params)
            if r.status_code == 401:
                raise AppError(401, "RECONNECT_REQUIRED", "Gmail rejected the token")
            r.raise_for_status()
            data = r.json()
            ids += [m["id"] for m in data.get("messages", [])]
            page = data.get("nextPageToken")
            if not page:
                break
        ctx.progress(0, None)
        for i, gid in enumerate(ids[:limit]):
            if conn.execute("SELECT 1 FROM messages WHERE id=?", (message_uuid(cid, gid),)).fetchone():
                skipped += 1  # already stored (or removed by the user): no need to download it again
                ctx.progress(i + 1)
                continue
            r = _get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{gid}", token, {"format": "full"})
            if r.status_code != 200:
                ctx.error(f"message {gid}: http {r.status_code}")
                conn.execute("UPDATE jobs SET failed_count=failed_count+1 WHERE id=?", (ctx.job_id,))
                continue
            m = r.json()
            labels = set(m.get("labelIds") or [])
            if "DRAFT" in labels:
                fetched += 1
                ctx.progress(i + 1)
                continue  # unfinished drafts are not incoming work or approved tone examples
            direction = "outbound" if "SENT" in labels and "INBOX" not in labels else "inbound"
            headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
            text, atts = _gmail_parts(m.get("payload", {}))
            try:
                sent = parsedate_to_datetime(headers.get("date", "")).isoformat()
            except (TypeError, ValueError):
                sent = None
            with transaction(conn):
                created += _store(conn, cid, gid, m.get("threadId"), headers.get("subject", ""), headers.get("from", ""),
                                  [headers.get("to", "")], sent, text, atts, direction=direction)
            fetched += 1
            ctx.progress(i + 1)
    else:
        fetched, created, skipped = _sync_outlook(ctx, conn, cid, token, days, limit,
                                                  bool(payload.get("include_spam_trash")))
    with transaction(conn):
        row = conn.execute("SELECT cursor_json FROM connections WHERE id=?", (cid,)).fetchone()
        cur = loads(row[0], {}) if row else {}
        cur.update({"last_sync_at": now_iso(), "last_sync_fetched": fetched})
        conn.execute("UPDATE connections SET cursor_json=? WHERE id=?", (dumps(cur), cid))
    return {"fetched": fetched, "created": created, "already_had": skipped}


# ---------------------------------------------------------------- Outlook / Microsoft Graph

def _graph_error(r) -> str:
    """'http 403 ErrorAccessDenied' - status plus Graph's error code, never the response body."""
    try:
        code = (r.json().get("error") or {}).get("code") or ""
    except Exception:  # noqa: BLE001
        code = ""
    return f"http {r.status_code} {code}".strip()


def _outlook_sender(m: dict) -> str:
    ea = (m.get("from") or m.get("sender") or {}).get("emailAddress") or {}
    name, addr = (ea.get("name") or "").strip(), (ea.get("address") or "").strip()
    if name and addr and name.lower() != addr.lower():
        return f"{name} <{addr}>"  # same shape as a Gmail From header, so drafts find the reply address
    return addr or name


def _outlook_web_link(m: dict) -> dict:
    link = m.get("webLink") or ""
    u = urlparse(link)
    return {"web_link": link} if u.scheme == "https" and u.hostname in OUTLOOK_WEB_HOSTS else {}


def _outlook_attachments(token: str, message_id: str) -> list[dict] | None:
    """Names and sizes only; attachment content is never downloaded."""
    r = _get(f"{GRAPH}/me/messages/{quote(message_id, safe='')}/attachments", token,
             {"$select": "name,size,isInline"}, extra_headers={"Prefer": 'IdType="ImmutableId"'})
    if r.status_code != 200:
        return None
    return [{"name": a.get("name") or "attachment", "size": a.get("size", 0), "content_read": False}
            for a in r.json().get("value", []) if not a.get("isInline")]


def _sync_outlook(ctx, conn: sqlite3.Connection, cid: str, token: str, days: int, limit: int,
                  include_spam_trash: bool) -> tuple[int, int, int]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    folders = ["inbox"] + (["junkemail", "deleteditems"] if include_spam_trash else [])
    fetched = created = skipped = seen = 0
    ctx.progress(0, None)
    for folder in folders:
        url: str | None = f"{GRAPH}/me/mailFolders/{folder}/messages"
        params: dict | None = {"$top": str(min(50, limit)), "$select": OUTLOOK_SELECT,
                               "$filter": f"receivedDateTime ge {since}", "$orderby": "receivedDateTime desc"}
        while url and seen < limit:
            r = _get(url, token, params, extra_headers={"Prefer": OUTLOOK_PREFER})
            params = None  # @odata.nextLink already carries the query
            if r.status_code == 401:
                raise AppError(401, "RECONNECT_REQUIRED", "Microsoft Graph rejected the token; reconnect Outlook")
            if r.status_code == 404 and folder != "inbox":
                break  # optional folder not present in this mailbox
            if r.status_code != 200:
                raise AppError(502, "GRAPH_ERROR", f"Outlook {folder} could not be listed ({_graph_error(r)})")
            data = r.json()
            for m in data.get("value", []):
                if seen >= limit:
                    break
                seen += 1
                if conn.execute("SELECT 1 FROM messages WHERE id=?", (message_uuid(cid, m["id"]),)).fetchone():
                    skipped += 1  # already stored (or removed by the user): keep it as it is
                    ctx.progress(seen)
                    continue
                body = m.get("body") or {}
                content = body.get("content") or ""
                text = content if (body.get("contentType") or "").lower() == "text" else html_to_text(content)
                atts: list[dict] = []
                if m.get("hasAttachments"):
                    listed = _outlook_attachments(token, m["id"])
                    if listed is None:
                        ctx.error(f"message {m['id'][:16]}: attachment names unavailable")
                    else:
                        atts = listed
                with transaction(conn):
                    created += _store(conn, cid, m["id"], m.get("conversationId"), m.get("subject") or "",
                                      _outlook_sender(m),
                                      [(x.get("emailAddress") or {}).get("address", "") for x in m.get("toRecipients") or []],
                                      m.get("receivedDateTime"), text, atts, _outlook_web_link(m))
                fetched += 1
                ctx.progress(seen)
            nxt = data.get("@odata.nextLink")
            url = nxt if nxt and nxt.startswith(GRAPH + "/") else None
    return fetched, created, skipped
