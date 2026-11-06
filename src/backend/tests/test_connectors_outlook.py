"""Outlook / Microsoft Graph paths against httpx.MockTransport - no real Microsoft service is contacted.
They prove request shape, scope handling, minimisation and failure reporting; scripts/check-outlook.py
is the check against a real account."""
import base64
import hashlib
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.config import settings
from app.db import connect, dumps, loads
from app.providers import mail_readers, net, oauth, tokens, writers

CLIENT_ID = "00000000-0000-0000-0000-00000000c1d0"
# Graph mixes full and short scope names, and personal accounts may return lower case.
MS_SCOPE = ("https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/User.Read "
            "https://graph.microsoft.com/calendars.read openid profile email")
PREFIX = "AAMkADAwATM3ZmYAZS0xNzAwLTE0ODQtMDACLTAwCgBGAAADxyz"  # real Graph ids share a long mailbox prefix


def _msg(n, **kw):
    m = {"id": f"{PREFIX}{n:04d}", "conversationId": f"conv{n}", "subject": f"Mail {n}",
         "from": {"emailAddress": {"name": f"Sender {n}", "address": f"sender{n}@u.example.edu"}},
         "toRecipients": [{"emailAddress": {"address": "student@outlook.com"}}],
         "receivedDateTime": "2026-11-04T01:00:00Z", "hasAttachments": False,
         "body": {"contentType": "text", "content": f"Body {n}"}, "webLink": None}
    m.update(kw)
    return m


@pytest.fixture
def fake_ms(monkeypatch):
    monkeypatch.setattr(settings, "microsoft_client_id", CLIENT_ID)
    monkeypatch.setattr(settings, "microsoft_client_secret", "secret-value")
    monkeypatch.setattr(settings, "microsoft_tenant_id", "common")
    monkeypatch.setattr("time.sleep", lambda s: None)
    tokens.use_memory_store(True)
    st = {"token_forms": [], "refresh_forms": [], "token_status": 200, "sent": [], "urls": []}

    def handler(req: httpx.Request):
        st["urls"].append(str(req.url))
        host, path = req.url.host, req.url.path
        if host == "login.microsoftonline.com" and path == "/common/oauth2/v2.0/token":
            form = parse_qs(req.content.decode())
            if form["grant_type"][0] == "refresh_token":
                st["refresh_forms"].append(form)
                return httpx.Response(200, json={"access_token": "at2", "refresh_token": "rt2", "expires_in": 3600,
                                                 "scope": MS_SCOPE})
            st["token_forms"].append(form)
            if st["token_status"] != 200:
                return httpx.Response(st["token_status"], json={
                    "error": "invalid_client", "error_codes": [7000215],
                    "error_description": "AADSTS7000215: Invalid client secret provided. Trace ID: x"})
            return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600,
                                             "scope": MS_SCOPE, "id_token": "x" * 3000, "ext_expires_in": 3600})
        if host != "graph.microsoft.com":
            return httpx.Response(404)
        if path == "/v1.0/me":
            return httpx.Response(200, json={"mail": None, "userPrincipalName": "student@outlook.com"})
        if path == "/v1.0/me/mailFolders/inbox/messages":
            assert req.headers["Prefer"] == mail_readers.OUTLOOK_PREFER
            if "skiptoken" in str(req.url):
                return httpx.Response(200, json={"value": [_msg(3)]})
            q = req.url.params
            assert q["$filter"].startswith("receivedDateTime ge ") and q["$orderby"] == "receivedDateTime desc"
            assert "body" in q["$select"] and "webLink" in q["$select"]
            return httpx.Response(200, json={"value": [
                _msg(1, hasAttachments=True, subject="Lab 3 due",
                     body={"contentType": "text", "content": "Lab 3 is due 2026-11-12. Call +65 9123 4567. Code 482913"},
                     webLink="https://outlook.live.com/owa/?ItemID=abc&exvsurl=1&viewmodel=ReadMessageItem"),
                _msg(2, body={"contentType": "html", "content": "<p>Hello<br>World</p><script>evil()</script>"},
                     webLink="https://evil.example.com/phish"),
            ], "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages?$skiptoken=abc"})
        if path == "/v1.0/me/mailFolders/junkemail/messages":
            return httpx.Response(200, json={"value": [_msg(4, subject="Junk")]})
        if path == "/v1.0/me/mailFolders/deleteditems/messages":
            return httpx.Response(200, json={"value": []})
        if path.endswith("/attachments"):
            return httpx.Response(200, json={"value": [{"name": "brief.pdf", "size": 1234, "isInline": False},
                                                       {"name": "logo.png", "size": 10, "isInline": True}]})
        if path == "/v1.0/me/calendarView":
            if req.url.params.get("startDateTime"):
                assert "+" not in req.url.query.decode()  # '+08:00' must be percent-encoded
                assert req.url.params["startDateTime"].endswith("+08:00")
            return httpx.Response(200, json={"value": [
                {"id": "e1", "showAs": "busy", "isCancelled": False,
                 "start": {"dateTime": "2026-10-19T02:00:00.0000000"}, "end": {"dateTime": "2026-10-19T03:00:00.0000000"}},
                {"id": "e2", "showAs": "free", "isCancelled": False,
                 "start": {"dateTime": "2026-10-19T05:00:00.0000000"}, "end": {"dateTime": "2026-10-19T06:00:00.0000000"}},
                {"id": "e3", "showAs": "busy", "isCancelled": True,
                 "start": {"dateTime": "2026-10-19T07:00:00.0000000"}, "end": {"dateTime": "2026-10-19T08:00:00.0000000"}}]})
        if path == "/v1.0/me/sendMail":
            st["sent"].append(json.loads(req.content))
            return httpx.Response(202)
        return httpx.Response(404)

    net.set_transport(httpx.MockTransport(handler))
    yield st
    net.set_transport(None)
    tokens.use_memory_store(False)
    with connect() as conn:  # leave the shared test database as other tests expect it
        conn.execute("DELETE FROM messages WHERE connection_id='conn_microsoft'")
        conn.execute("DELETE FROM jobs WHERE connection_id='conn_microsoft'")
        conn.execute("UPDATE connections SET status='disconnected', scopes_json='[]', credential_ref=NULL, "
                     "cursor_json='{}' WHERE id='conn_microsoft'")
        conn.commit()


def _connect(api, capability="read_mail"):
    r = api.post("/api/connections/microsoft/authorize", {"capability": capability}).json()
    q = parse_qs(urlparse(r["authorization_url"]).query)
    cb = api.c.get(f"/api/connections/microsoft/callback?code=abc&state={q['state'][0]}", follow_redirects=False)
    return r["authorization_url"], q, cb


def test_scope_names_are_normalised():
    assert oauth.normalize_ms_scopes(MS_SCOPE.split()) == [
        "Calendars.Read", "Mail.Read", "User.Read", "email", "openid", "profile"]


def test_calendar_granted_with_the_old_permission_asks_to_authorise_again(api, fake_ms):
    _connect(api)
    with connect() as conn:  # a connection made by the previous version, which asked for Calendars.ReadBasic
        conn.execute("UPDATE connections SET scopes_json=? WHERE id='conn_microsoft'",
                     (dumps(["Calendars.ReadBasic", "Mail.Read", "User.Read", "offline_access",
                             "Mail.Send", "Calendars.ReadWrite", "ChatMessage.Send"]),))
        conn.commit()
    caps = next(c for c in api.get("/api/connections").json()["items"] if c["provider"] == "microsoft")["capabilities"]
    assert caps["read_mail"] and not caps["read_busy"]  # shown as "authorise calendar", not as working
    r = api.post("/api/connections/microsoft/authorize", {"capability": "read_busy"}).json()
    scopes = parse_qs(urlparse(r["authorization_url"]).query)["scope"][0].split()
    assert "Calendars.Read" in scopes and "Mail.Read" in scopes  # incremental: mail access is kept
    assert not any(s in scopes for s in ("Calendars.ReadBasic", "Calendars.ReadWrite", "Mail.Send",
                                       "ChatMessage.Send"))  # old grants cannot widen a read-only request
    assert oauth.normalize_ms_scopes(["https://graph.microsoft.com/calendars.readbasic"]) == ["Calendars.ReadBasic"]


def test_outlook_connect_sync_busy_refresh_send(api, fake_ms):
    url, q, cb = _connect(api)
    u = urlparse(url)
    assert u.hostname == "login.microsoftonline.com" and u.path == "/common/oauth2/v2.0/authorize"
    scopes = q["scope"][0].split()
    assert {"Mail.Read", "offline_access", "User.Read"} <= set(scopes) and "Mail.Send" not in scopes
    assert q["code_challenge_method"] == ["S256"] and q["prompt"] == ["select_account"]
    assert q["redirect_uri"] == [settings.microsoft_redirect_uri]
    assert cb.status_code == 303 and "oauth=microsoft:connected" in cb.headers["location"]
    form = fake_ms["token_forms"][0]
    assert form["code_verifier"][0] and form["client_secret"] == ["secret-value"]

    conn_view = next(c for c in api.get("/api/connections").json()["items"] if c["provider"] == "microsoft")
    assert conn_view["status"] == "connected" and conn_view["account_label"] == "student@outlook.com"
    caps = conn_view["capabilities"]
    assert caps["read_mail"] and caps["read_busy"] and not caps["send_mail"]  # lower-case scope still matches
    assert "id_token" not in tokens.load("conn_microsoft:token")

    job = api.post("/api/sync-jobs", {"connection_id": "conn_microsoft", "lookback_days": 7, "max_messages": 10,
                                      "include_spam_trash": True}).json()
    job = api.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "completed", job
    assert job["result"] == {"fetched": 4, "created": 4, "already_had": 0}

    with connect() as conn:
        rows = {r["provider_message_id"][-4:]: r for r in conn.execute(
            "SELECT * FROM messages WHERE connection_id='conn_microsoft'").fetchall()}
    assert set(rows) == {"0001", "0002", "0003", "0004"}
    assert len({r["source_id"] for r in rows.values()}) == 4  # no collision on the shared Graph id prefix
    m1, m2 = rows["0001"], rows["0002"]
    assert "2026-11-12" in m1["body_view"] and "9123" not in m1["body_view"] and "482913" not in m1["body_view"]
    assert loads(m1["attachments_json"], []) == [{"name": "brief.pdf", "size": 1234, "content_read": False}]
    assert "u.example.edu" not in loads(m1["sender_json"], {})["label"]  # address scrubbed before storing
    assert "Sender 1" in loads(m1["sender_json"], {})["label"]
    assert "evil" not in m2["body_view"] and "Hello" in m2["body_view"]

    d1 = api.get(f"/api/messages/{m1['id']}").json()
    assert d1["source"]["kind"] == "microsoft" and d1["source"]["open_url"].startswith("https://outlook.live.com/")
    d2 = api.get(f"/api/messages/{m2['id']}").json()
    assert d2["source"]["open_url"].startswith("https://outlook.office.com/")  # untrusted webLink host ignored

    again = api.post("/api/sync-jobs", {"connection_id": "conn_microsoft", "lookback_days": 7, "max_messages": 10,
                                        "include_spam_trash": True}).json()
    assert api.get(f"/api/jobs/{again['id']}").json()["result"] == {"fetched": 0, "created": 0, "already_had": 4}

    snap = api.post("/api/calendar/snapshots", {"provider": "microsoft", "connection_id": "conn_microsoft",
                                                "time_min": "2026-10-19T08:00:00+08:00", "time_max": "2026-10-20T00:00:00+08:00",
                                                "calendar_ids": [], "display_timezone": "Asia/Singapore"}).json()
    assert snap["status"] == "complete" and len(snap["busy"]) == 1  # free and cancelled events are not busy

    with connect() as conn:  # force an expired access token -> refresh must carry scope + secret
        tok = tokens.load("conn_microsoft:token")
        tok["obtained_at"] = 0
        tokens.save("conn_microsoft:token", tok)
        assert oauth.access_token(conn, "microsoft") == "at2"
    rf = fake_ms["refresh_forms"][0]
    assert {"Mail.Read", "offline_access"} <= set(rf["scope"][0].split()) and rf["client_secret"] == ["secret-value"]

    pdf = b"%PDF-1.4 test attachment"
    upload = "upl_outlook_test"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    (settings.upload_dir / f"{upload}.pdf").write_bytes(pdf)
    payload = {"connection_id": "conn_microsoft", "to": ["ta@uni.example.edu"], "cc": [], "bcc": ["me@outlook.com"],
               "subject": "Re: Lab 3 due", "body": "Thanks, noted.", "thread_id": "conv1",
               "attachments": [{"id": upload, "name": "brief.pdf", "size_bytes": len(pdf),
                                "sha256": hashlib.sha256(pdf).hexdigest()}]}
    status, res = writers.execute("send_email", payload, "op_outlook_1")
    assert status == "accepted" and res["http_status"] == 202  # 202 is not proof of delivery
    msg = fake_ms["sent"][0]["message"]
    assert [r["emailAddress"]["address"] for r in msg["toRecipients"]] == ["ta@uni.example.edu"]
    assert [r["emailAddress"]["address"] for r in msg["bccRecipients"]] == ["me@outlook.com"]
    assert base64.b64decode(msg["attachments"][0]["contentBytes"]) == pdf
    changed = dict(payload, attachments=[dict(payload["attachments"][0], sha256="0" * 64)])
    status, res = writers.execute("send_email", changed, "op_outlook_2")
    assert status == "failed" and len(fake_ms["sent"]) == 1  # nothing sent when the file changed after approval

    out = api.post("/api/connections/conn_microsoft/disconnect").json()
    assert out["status"] == "disconnected" and tokens.load("conn_microsoft:token") is None


def test_outlook_setup_errors_are_reported(api, fake_ms):
    fake_ms["token_status"] = 401
    _, _, cb = _connect(api)
    assert "oauth=microsoft:error" in cb.headers["location"]
    view = next(c for c in api.get("/api/connections").json()["items"] if c["provider"] == "microsoft")
    assert view["status"] == "error" and view["last_error"] == "token_exchange_http_401:AADSTS7000215"
    assert "secret-value" not in json.dumps(view)

    r = api.post("/api/connections/microsoft/authorize", {"capability": "read_mail"}).json()
    state = parse_qs(urlparse(r["authorization_url"]).query)["state"][0]
    cb = api.c.get("/api/connections/microsoft/callback", follow_redirects=False, params={
        "state": state, "error": "access_denied",
        "error_description": "AADSTS90094: Admin consent is required for the permissions requested by this application."})
    assert "oauth=microsoft:needs_admin" in cb.headers["location"]
    view = next(c for c in api.get("/api/connections").json()["items"] if c["provider"] == "microsoft")
    assert view["status"] == "needs_admin" and view["last_error"] == "needs_admin:AADSTS90094"


def test_callback_on_localhost_returns_to_app_origin(api, fake_ms):
    # The Entra portal only accepts http://localhost redirect URIs; the UI and its cookie live on APP_ORIGIN.
    cb = api.c.get("http://localhost:8000/api/connections/microsoft/callback?state=unknown", follow_redirects=False)
    assert cb.status_code == 303
    assert cb.headers["location"] == f"{settings.app_origin}/#/sources/connections?oauth=microsoft:invalid_state"
