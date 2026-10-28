"""Read-only mail sync: Gmail (gmail.readonly) and Outlook (Mail.Read).

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
from email.utils import parsedate_to_datetime

from ..db import dumps, loads, now_iso, transaction
from ..errors import AppError
from ..services.import_service import message_uuid
from ..services.privacy import scrub, sha256_text
from . import net, oauth

MAX_BODY = 20000


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


def _store(conn, cid, provider_id, thread, subject, sender, to, sent_at, body, atts) -> bool:
    mid = message_uuid(cid, provider_id)
    if conn.execute("SELECT 1 FROM messages WHERE id=?", (mid,)).fetchone():
        return False
    body = scrub(body.replace(chr(13) + chr(10), chr(10)).replace(chr(13), chr(10)))[:MAX_BODY]
    ts = now_iso()
    conn.execute(
        """INSERT INTO messages(id,connection_id,provider_message_id,source_type,source_id,thread_id,direction,subject,
           sender_json,recipients_json,sent_at,body_view,body_hash,locator_json,attachments_json,analysis_status,
           analysis_origin,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (mid, cid, provider_id, "email", provider_id[:24], thread, "inbound", scrub(subject)[:300],
         dumps({"label": scrub(sender)}), dumps({"to": [scrub(x) for x in to]}), sent_at, body, sha256_text(body),
         dumps({"provider": cid, "body_view": "plain_text_minimised"}), dumps(atts), "pending", "none", ts, ts))
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
            headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
            text, atts = _gmail_parts(m.get("payload", {}))
            try:
                sent = parsedate_to_datetime(headers.get("date", "")).isoformat()
            except (TypeError, ValueError):
                sent = None
            with transaction(conn):
                created += _store(conn, cid, gid, m.get("threadId"), headers.get("subject", ""), headers.get("from", ""),
                                  [headers.get("to", "")], sent, text, atts)
            fetched += 1
            ctx.progress(i + 1)
    else:
        url = ("https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
               "?$top=50&$select=id,conversationId,from,toRecipients,subject,receivedDateTime,body,hasAttachments")
        while url and fetched < limit:
            r = _get(url, token, extra_headers={"Prefer": 'outlook.body-content-type="text"'})
            if r.status_code == 401:
                raise AppError(401, "RECONNECT_REQUIRED", "Microsoft Graph rejected the token")
            r.raise_for_status()
            data = r.json()
            for m in data.get("value", []):
                if fetched >= limit:
                    break
                body = m.get("body", {})
                text = body.get("content", "") if body.get("contentType") == "text" else html_to_text(body.get("content", ""))
                with transaction(conn):
                    created += _store(conn, cid, m["id"], m.get("conversationId"), m.get("subject", ""),
                                      (m.get("from") or {}).get("emailAddress", {}).get("address", ""),
                                      [x["emailAddress"]["address"] for x in m.get("toRecipients", [])],
                                      m.get("receivedDateTime"), text, [])
                fetched += 1
            ctx.progress(fetched)
            nxt = data.get("@odata.nextLink")
            url = nxt if nxt and nxt.startswith("https://graph.microsoft.com/") else None
    with transaction(conn):
        row = conn.execute("SELECT cursor_json FROM connections WHERE id=?", (cid,)).fetchone()
        cur = loads(row[0], {}) if row else {}
        cur.update({"last_sync_at": now_iso(), "last_sync_fetched": fetched})
        conn.execute("UPDATE connections SET cursor_json=? WHERE id=?", (dumps(cur), cid))
    return {"fetched": fetched, "created": created, "already_had": skipped}
