"""Phase 4-6 paths exercised against httpx.MockTransport - no real provider or model is contacted.
These prove request shape, scope gating and failure handling, not that a real account works."""
import base64
import json
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.config import settings
from app.providers import net, oauth, tokens


@pytest.fixture
def fake_google(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "secret")
    tokens.use_memory_store(True)
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, str(req.url)))
        host, path = req.url.host, req.url.path
        if host == "oauth2.googleapis.com" and path == "/token":
            form = parse_qs(req.content.decode())
            assert form["code_verifier"][0]  # PKCE verifier is sent
            return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600,
                                             "scope": "openid email https://www.googleapis.com/auth/gmail.readonly "
                                                      "https://www.googleapis.com/auth/calendar.events.freebusy"})
        if host == "openidconnect.googleapis.com":
            return httpx.Response(200, json={"email": "student@example.edu"})
        if path == "/gmail/v1/users/me/messages":
            assert req.url.params["includeSpamTrash"] == "false"
            return httpx.Response(200, json={"messages": [{"id": "g1"}, {"id": "g2"}]})
        if path.startswith("/gmail/v1/users/me/messages/"):
            gid = path.rsplit("/", 1)[1]
            if gid == "g2":
                return httpx.Response(500)
            body = base64.urlsafe_b64encode(b"Hi, the lab is due 2026-11-02. Call me at +65 9123 4567. Code 482913").decode()
            return httpx.Response(200, json={"id": gid, "threadId": "t1", "payload": {"mimeType": "text/plain",
                                  "headers": [{"name": "Subject", "value": "Lab"}, {"name": "From", "value": "TA <ta@uni.edu>"},
                                              {"name": "Date", "value": "Mon, 19 Oct 2026 09:00:00 +0800"}],
                                  "body": {"data": body}}})
        if path == "/calendar/v3/freeBusy":
            return httpx.Response(200, json={"calendars": {"primary": {"busy": [
                {"start": "2026-10-19T02:00:00Z", "end": "2026-10-19T04:00:00Z"}]}}})
        return httpx.Response(404)
    net.set_transport(httpx.MockTransport(handler))
    yield calls
    net.set_transport(None)
    tokens.use_memory_store(False)


def test_oauth_read_only_flow_sync_and_busy(api, fake_google, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    r = api.post("/api/connections/google/authorize", {"capability": "read_mail"}).json()
    q = parse_qs(urlparse(r["authorization_url"]).query)
    assert "gmail.send" not in q["scope"][0] and q["code_challenge_method"] == ["S256"]
    cb = api.c.get(f"/api/connections/google/callback?code=abc&state={q['state'][0]}", follow_redirects=False)
    assert cb.status_code == 303 and "oauth=google:connected" in cb.headers["location"]
    assert "at" not in cb.headers["location"].split("?")[1].replace("oauth", "")  # token never in the URL
    conn = next(c for c in api.get("/api/connections").json()["items"] if c["provider"] == "google")
    assert conn["status"] == "connected" and conn["capabilities"]["read_mail"] and not conn["capabilities"]["send_mail"]
    # Replaying the same state is rejected.
    again = api.c.get(f"/api/connections/google/callback?code=abc&state={q['state'][0]}", follow_redirects=False)
    assert "invalid_state" in again.headers["location"]

    job = api.post("/api/sync-jobs", {"connection_id": "conn_google", "lookback_days": 7, "max_messages": 10,
                                      "include_spam_trash": False}).json()
    job = api.get(f"/api/jobs/{job['id']}").json()
    assert job["status"] == "partial" and job["failed_count"] == 1 and job["result"]["created"] == 1
    synced = [m for m in api.get("/api/messages?limit=500").json()["items"] if m["source_id"] == "g1"]
    body = api.get(f"/api/messages/{synced[0]['id']}").json()["body_view"]
    assert "2026-11-02" in body and "9123" not in body and "482913" not in body  # minimised before storing

    snap = api.post("/api/calendar/snapshots", {"provider": "google", "connection_id": "conn_google",
                                                "time_min": "2026-10-19T08:00:00+08:00", "time_max": "2026-10-20T00:00:00+08:00",
                                                "calendar_ids": ["primary"], "display_timezone": "Asia/Singapore"}).json()
    assert snap["status"] == "complete" and len(snap["busy"]) == 1

    # Live send stays blocked: no gmail.send scope, demo app mode, writes disabled.
    d = api.post("/api/drafts", {"source_message_id": synced[0]["id"], "purpose": "reply", "channel": "email",
                                 "verified_facts": {"reply_points": "Thanks, noted.", "recipient_name": "TA", "signature": "Sam"},
                                 "attachment_ids": []}).json()
    p = api.post("/api/proposals", {"source_kind": "draft", "source_object_id": d["id"],
                                    "expected_source_revision": d["revision"], "mode": "live"}).json()
    assert p["status"] == "blocked"
    assert any(b.startswith("missing_permission:google:send_mail") for b in p["blocking_fields"])
    assert not any("messages/send" in u for _, u in fake_google)

    out = api.post("/api/connections/conn_google/disconnect").json()
    assert out["status"] == "disconnected" and tokens.load("conn_google:token") is None


def test_oauth_denied_keeps_existing_access(api, fake_google):
    r = api.post("/api/connections/google/authorize", {"capability": "send_mail"}).json()
    state = parse_qs(urlparse(r["authorization_url"]).query)["state"][0]
    cb = api.c.get(f"/api/connections/google/callback?error=access_denied&state={state}", follow_redirects=False)
    assert "google:denied" in cb.headers["location"]


def test_model_adapter_validates_evidence(api, monkeypatch):
    from app.llm import adapter
    from app.services import analysis_service
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_model", "test-model")
    monkeypatch.setattr(settings, "allow_model_processing", True)
    sent = []

    def handler(req):
        body = json.loads(req.content)
        sent.append(body)
        payload = json.loads(body["input"][1]["content"])
        out = {"source_id": payload["source_id"], "category": "academic", "summary": "s", "needs_reply": False,
               "needs_action": True, "attention_flags": [], "unknowns": [],
               "candidates": [{"title": "Lab", "course": None, "deliverable": None, "date": "2026-11-02", "time": None,
                               "timezone": None, "status": "pending", "needs_review": True,
                               "evidence": [{"source_id": payload["source_id"], "field": "body",
                                             "quote": "invented text not in source" if "BAD" in payload["subject"] else "due 2026-11-02"}]}]}
        return httpx.Response(200, json={"status": "completed", "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                                         "output": [{"content": [{"type": "output_text", "text": json.dumps(out)}]}]})
    p = {"source_id": "X1", "subject": "Lab", "body": "The lab is due 2026-11-02.", "sent_at": None, "source_timezone": None}
    parsed, usage = adapter.structured_call(adapter.BOUNDARY, p, adapter.MAIL_ANALYSIS, "mail_analysis",
                                            transport=httpx.MockTransport(handler))
    assert analysis_service.check(parsed, p) == [] and usage["total_tokens"] == 15
    assert sent[0]["store"] is False and sent[0]["text"]["format"]["strict"] is True
    assert "annotation" not in sent[0]["input"][1]["content"]
    bad = dict(p, subject="BAD")
    parsed, _ = adapter.structured_call(adapter.BOUNDARY, bad, adapter.MAIL_ANALYSIS, "mail_analysis",
                                        transport=httpx.MockTransport(handler))
    assert any(e.startswith("quote_not_in_source") for e in analysis_service.check(parsed, bad))
    # Still gated by the user's own setting.
    st = api.get("/api/model/status").json()
    assert st["enabled"] is False and st["reasons"] == ["user_has_not_enabled_model_processing"]


def test_minimized_payload_never_contains_annotation(api, imported):
    from app.db import connect
    from app.services.analysis_service import minimized
    with connect() as conn:
        row = conn.execute("SELECT * FROM messages WHERE source_id='M10'").fetchone()
    p = minimized(row)
    assert set(p) == {"source_id", "subject", "body", "sent_at", "source_timezone"}
    assert "holdout" not in json.dumps(p) and "AI_assisted" not in json.dumps(p)


def test_old_model_output_gets_english_copy(api, imported, monkeypatch):
    from app.db import connect, dumps, loads
    from app.llm import adapter
    from app.services import analysis_service
    sent = []

    def fake(system, payload, schema, name, **kw):
        sent.append(payload)
        en = {"金融产品推广": "Financial product promotion", "提交申诉": "Submit an appeal"}
        return {"items": [{"id": x["id"], "zh": x["text"], "en": en[x["text"]]} for x in payload["items"]]}, {}
    monkeypatch.setattr(adapter, "structured_call", fake)
    monkeypatch.setattr(adapter, "require_enabled", lambda conn: None)
    with connect() as conn:
        row = conn.execute("SELECT * FROM messages WHERE direction='inbound' LIMIT 1").fetchone()
        old = (row["analysis_json"], row["analysis_origin"])
        conn.execute("UPDATE messages SET analysis_json=?, analysis_origin='model' WHERE id=?",
                     (dumps({"summary": "s", "attention_flags": ["金融产品推广"]}), row["id"]))
        conn.execute("""INSERT INTO tasks(id,entity_key,title,status,created_at,updated_at)
                        VALUES('task_tr','model_X_0','提交申诉','needs_review','t','t')""")
        conn.commit()
        try:
            assert analysis_service.translate_pending(conn) == {"flags": 1, "titles": 1}
            a = loads(conn.execute("SELECT analysis_json FROM messages WHERE id=?", (row["id"],)).fetchone()[0], {})
            assert a["attention_flags_en"] == ["Financial product promotion"]
            assert api.get("/api/tasks/task_tr").json()["title_en"] == "Submit an appeal"
            assert all(set(x) == {"id", "text"} for x in sent[0]["items"])  # only notes/titles, no mail text
            assert analysis_service.translate_pending(conn) == {"flags": 0, "titles": 0}  # done once
            t = api.get("/api/tasks/task_tr").json()
            api.patch("/api/tasks/task_tr", {"expected_revision": t["revision"], "title": "My own title"})
            assert api.get("/api/tasks/task_tr").json()["title_en"] is None  # user's title shown as typed
        finally:
            conn.execute("UPDATE messages SET analysis_json=?, analysis_origin=? WHERE id=?", (*old, row["id"]))
            conn.execute("DELETE FROM tasks WHERE id='task_tr'")
            conn.commit()


def test_real_gmail_reply_stays_in_thread(monkeypatch):
    from email import message_from_bytes
    from app.providers import writers
    monkeypatch.setattr(oauth, "access_token", lambda conn, provider: "at")
    sent = []

    def handler(req: httpx.Request):
        if req.method == "GET" and req.url.path == "/gmail/v1/users/me/messages/g1":
            return httpx.Response(200, json={"payload": {"headers": [{"name": "Message-ID", "value": "<orig@mail.uni.edu>"}]}})
        if req.url.path == "/gmail/v1/users/me/messages/send":
            sent.append(json.loads(req.content))
            return httpx.Response(200, json={"id": "s1"})
        return httpx.Response(404)
    net.set_transport(httpx.MockTransport(handler))
    try:
        status, res = writers.execute("send_email", {
            "connection_id": "conn_google", "to": ["ta@uni.edu"], "cc": [], "bcc": [], "subject": "Re: Lab",
            "body": "Thanks, noted.", "attachments": [], "thread_id": "t1", "reply_to_provider_message_id": "g1"}, "op1")
    finally:
        net.set_transport(None)
    assert status == "executed" and res["provider_id"] == "s1"
    assert sent[0]["threadId"] == "t1"
    mime = message_from_bytes(base64.urlsafe_b64decode(sent[0]["raw"]))
    assert mime["In-Reply-To"] == "<orig@mail.uni.edu>" and mime["To"] == "ta@uni.edu"
