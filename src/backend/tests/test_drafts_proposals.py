"""T10, T15, T16, T17-ish, style references, live blocking, de-identified recipients."""
import threading
import uuid

import httpx

from conftest import needs_samples


def _confirm(api, p, key=None):
    return api.post(f"/api/proposals/{p['id']}/confirm", {"expected_revision": p["revision"], "payload_hash": p["payload_hash"]},
                    headers={"Idempotency-Key": key or uuid.uuid4().hex})


def _fill(api, d, **fields):
    return api.patch(f"/api/drafts/{d['id']}", {"expected_revision": d["revision"], **fields}).json()


def test_t10_extension_without_reason_is_blocked(api):
    d = api.post("/api/drafts", {"purpose": "extension", "channel": "email", "verified_facts": {"task_title": "Report"},
                                 "attachment_ids": []}).json()
    assert any(f.startswith("reason:") for f in d["missing_fields"])
    assert d["ready_for_review"] is False
    assert "sick" not in d["body"].lower() and "family" not in d["body"].lower()
    p = api.post("/api/proposals", {"source_kind": "draft", "source_object_id": d["id"],
                                    "expected_source_revision": d["revision"], "mode": "demo"}).json()
    assert p["status"] == "blocked" and any("reason" in b for b in p["blocking_fields"])
    assert _confirm(api, p).status_code == 409


def _ready_draft(api):
    d = api.post("/api/drafts", {"purpose": "extension", "channel": "email", "language": "en",
                                 "verified_facts": {"task_title": "Report 2", "reason": "I was in hospital on Oct 18.",
                                                    "requested_new_date": "2026-10-30", "recipient_name": "Dr Tan",
                                                    "signature": "Alex"}, "attachment_ids": []}).json()
    return _fill(api, d, to=["prof@example.edu"])


def test_demo_confirm_simulates_once_and_t16_concurrency(api):
    d = _ready_draft(api)
    assert d["ready_for_review"], d["missing_fields"]
    p = api.post("/api/proposals", {"source_kind": "draft", "source_object_id": d["id"],
                                    "expected_source_revision": d["revision"], "mode": "demo"}).json()
    assert p["status"] == "pending_review" and p["payload"]["body"] == d["body"]
    results = []

    def go(k):
        results.append((k, _confirm(api, p, k)))
    threads = [threading.Thread(target=go, args=(uuid.uuid4().hex,)) for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    ok = [(k, r) for k, r in results if r.status_code == 202]
    assert len(ok) == 1, [r.text for _, r in results]
    winner_key, win = ok[0]
    assert win.json()["status"] == "simulated" and win.json()["result"]["external_call"] is False
    replay = _confirm(api, p, winner_key)  # same idempotency key -> same recorded state, no new execution
    assert replay.status_code == 202 and replay.json()["status"] == "simulated"


def test_t15_edit_after_proposal_invalidates(api):
    d = _ready_draft(api)
    p = api.post("/api/proposals", {"source_kind": "draft", "source_object_id": d["id"],
                                    "expected_source_revision": d["revision"], "mode": "demo"}).json()
    _fill(api, d, to=["other@example.edu"])
    assert api.get(f"/api/proposals/{p['id']}").json()["status"] == "invalidated"
    assert _confirm(api, p).status_code == 409


def test_hash_mismatch_rejected(api):
    d = _ready_draft(api)
    p = api.post("/api/proposals", {"source_kind": "draft", "source_object_id": d["id"],
                                    "expected_source_revision": d["revision"], "mode": "demo"}).json()
    r = api.post(f"/api/proposals/{p['id']}/confirm", {"expected_revision": p["revision"], "payload_hash": "0" * 64},
                 headers={"Idempotency-Key": uuid.uuid4().hex})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PAYLOAD_HASH_MISMATCH"


def test_live_mode_blocked_without_config(api):
    d = _ready_draft(api)
    p = api.post("/api/proposals", {"source_kind": "draft", "source_object_id": d["id"],
                                    "expected_source_revision": d["revision"], "mode": "live"}).json()
    assert p["status"] == "blocked"
    for b in ("app_mode_is_demo", "external_writes_disabled_by_server_config", "external_writes_disabled_in_settings"):
        assert b in p["blocking_fields"]


@needs_samples
def test_reply_draft_keeps_deidentified_recipient_out_of_live(api, imported):
    m = api.get("/api/messages/M16").json()
    d = api.post("/api/drafts", {"source_message_id": m["id"], "purpose": "reply", "channel": "email",
                                 "verified_facts": {}, "attachment_ids": []}).json()
    assert d["to"] and d["recipients_deidentified"] is True
    assert d["subject"].startswith("Re:")
    p = api.post("/api/proposals", {"source_kind": "draft", "source_object_id": d["id"],
                                    "expected_source_revision": d["revision"], "mode": "live"}).json()
    assert any(b.startswith("deidentified_recipient") for b in p["blocking_fields"])


@needs_samples
def test_style_selection_and_generic_fallbacks(api, imported):
    refs = api.get("/api/style-references").json()
    assert len(refs) == 10 and all(r["authorship_verified"] for r in refs)
    m49 = next(r for r in refs if r["sample_id"] == "M49")
    assert "Zoom" not in m49["authored_excerpt"] and "Join from" not in m49["authored_excerpt"]
    rec = api.post("/api/drafts", {"purpose": "reply", "channel": "email", "relationship": "recruiter",
                                   "verified_facts": {}, "attachment_ids": []}).json()
    assert rec["style_mode"] == "generic" and rec["style_reference_ids"] == []
    zh = api.post("/api/drafts", {"purpose": "extension", "channel": "email", "language": "zh",
                                  "verified_facts": {}, "attachment_ids": []}).json()
    assert zh["style_mode"] == "generic" and "[[延期的实际理由]]" in zh["body"]
    prof = api.post("/api/drafts", {"purpose": "extension", "channel": "email", "relationship": "professor",
                                    "verified_facts": {"task_title": "Essay", "reason": "my laptop failed on Monday.",
                                                       "requested_new_date": "Friday", "recipient_name": "Prof Lee",
                                                       "signature": "Sam"}, "attachment_ids": []}).json()
    assert prof["style_mode"] == "personal" and 1 <= len(prof["style_reference_ids"]) <= 3
    assert "Lyrebird" not in prof["body"] and "Sponsor" not in prof["body"]  # tone only, no historical facts
    # Nobody addressed in an old email is carried into a new draft.
    assert not any(n in prof["body"] for n in ("Nadia", "Reyes", "Okafor", "Lindqvist", "Hannah"))
    assert prof["body"].startswith(("Dear Professor Prof Lee,", "Hi Professor Prof Lee,", "Hi Prof Lee,", "Dear Prof Lee,"))
    prof = _fill(api, prof, to=["prof@example.edu"])
    p = api.post("/api/proposals", {"source_kind": "draft", "source_object_id": prof["id"],
                                    "expected_source_revision": prof["revision"], "mode": "demo"}).json()
    assert p["status"] == "pending_review"
    used = prof["style_reference_ids"][0]
    profile = api.get("/api/style-profile").json()
    api.patch(f"/api/style-references/{used}", {"expected_profile_revision": profile["revision"], "included": False})
    assert api.get(f"/api/proposals/{p['id']}").json()["status"] == "invalidated"
    d2 = api.get(f"/api/drafts/{prof['id']}").json()
    assert d2["stale_style"] and d2["body"] == prof["body"] and not d2["ready_for_review"]
    d3 = _fill(api, d2, acknowledge_style_change=True)
    assert d3["ready_for_review"]
    profile = api.get("/api/style-profile").json()
    api.patch(f"/api/style-references/{used}", {"expected_profile_revision": profile["revision"], "included": True})


# SHA-256 prefixes of the original school / place / project words, so this public repo never
# spells them out. The test fails if any word of the imported samples hashes to one of them.
_REAL_TERM_HASHES = {
    "054da1e8bc1cb20b", "b28e4e917773971b", "7742f5a7759dd1c0", "03a8f0dd8edb3378",
    "b056879118a305b2", "4a3484b3bf2fcb0f", "dfc86d362ce5fdf0", "64d362d2e483e802",
}


@needs_samples
def test_dataset_is_pseudonymised(api, imported):
    import hashlib
    import re
    blob = " ".join(m["subject"] + " " + m["sender_label"] for m in api.get("/api/messages?limit=500").json()["items"])
    blob += " ".join(api.get(f"/api/messages/{sid}").json()["body_view"] for sid in ("M29", "M36", "M41", "M43", "M09"))
    words = {w.lower() for w in re.findall(r"[A-Za-z]+", blob)}
    leaked = [w for w in words if hashlib.sha256(w.encode()).hexdigest()[:16] in _REAL_TERM_HASHES]
    assert leaked == []
    assert not re.search(r"\bCSE ?4\d\d\b|Fall C\)", blob)  # original course-code / session format


def test_t20_canvas_and_unknown_hosts_blocked():
    from app.providers import net
    assert not net.allowed("https://canvas.nus.edu.sg/api/v1/courses")
    assert not net.allowed("https://example.instructure.com/x")
    assert not net.allowed("https://evil.example/collect")
    assert not net.allowed("http://graph.microsoft.com/v1.0/me")
    assert net.allowed("https://gmail.googleapis.com/gmail/v1/users/me/messages")


def test_unknown_outcome_on_timeout_is_not_success(monkeypatch):
    from app.providers import net, writers
    monkeypatch.setattr(writers.oauth, "access_token", lambda conn, provider: "tok")

    def boom(request):
        raise httpx.ReadTimeout("timeout", request=request)
    net.set_transport(httpx.MockTransport(boom))
    try:
        status, result = writers.execute("send_chat", {"chat_id": "19:abc", "body": "hi"}, "op-1")
    finally:
        net.set_transport(None)
    assert status == "unknown" and result["reason"] == "no_definite_response"
