"""Live calendar flow and its boundaries, using an isolated database and HTTP transport."""
import json
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.config import settings
from app.db import connect, dumps, init_db, now_iso
from app.providers import calendars, net, oauth

SGT = ZoneInfo("Asia/Singapore")
CAL_SCOPE = "https://www.googleapis.com/auth/calendar.app.created"


@pytest.fixture
def live_calendar(api, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "live-calendar.sqlite3")
    monkeypatch.setattr(settings, "app_mode", "live")
    monkeypatch.setattr(settings, "enable_external_writes", True)
    init_db()
    prefs = api.get("/api/preferences").json()
    assert api.patch("/api/preferences", {"expected_revision": prefs["revision"],
                                          "enable_external_writes": True}).status_code == 200
    with connect() as conn:
        conn.execute("""INSERT INTO connections(id,provider,account_label,status,scopes_json,cursor_json,created_at,updated_at)
                        VALUES('conn_google','google','unit test','connected',?,?,?,?)""",
                     (dumps([CAL_SCOPE, "https://www.googleapis.com/auth/calendar.events.freebusy",
                             "https://www.googleapis.com/auth/gmail.readonly"]),
                      dumps({"app_calendar_id": "unit-study-calendar"}), now_iso(), now_iso()))
    monkeypatch.setattr(calendars, "read_busy", lambda *a, **kw: {
        "busy": [], "errors": [], "status": "complete", "version": "test-v1"})
    monkeypatch.setattr(oauth, "access_token", lambda *a: "unit-test-token")
    calls = []

    def handler(req):
        calls.append(req)
        if req.method == "POST" and req.url.path == "/calendar/v3/calendars/unit-study-calendar/events":
            return httpx.Response(200, json={"id": json.loads(req.content)["id"], "status": "confirmed"})
        return httpx.Response(404)

    net.set_transport(httpx.MockTransport(handler))
    try:
        yield calls
    finally:
        net.set_transport(None)


def ready_plan(api, provider="google", start_offset=1):
    tomorrow = datetime.now(SGT).replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=start_offset)
    cutoff = datetime.now(SGT).date() + timedelta(days=4)
    task = api.post("/api/tasks", {"title": "Calendar integration test"}).json()
    task = api.patch(f"/api/tasks/{task['id']}", {"expected_revision": task["revision"],
                     "official_date": cutoff.isoformat(), "official_time": "18:00", "source_timezone": "Asia/Singapore",
                     "estimated_minutes": 30, "status": "confirmed"}).json()
    snap = api.post("/api/calendar/snapshots", {
        "provider": provider, "connection_id": "conn_google" if provider == "google" else None,
        "time_min": tomorrow.isoformat(), "time_max": (tomorrow + timedelta(days=3)).isoformat(),
        "calendar_ids": ["primary"], "display_timezone": "Asia/Singapore"}).json()
    prefs = api.get("/api/preferences").json()
    plan = api.post("/api/plans/preview", {"task_ids": [task["id"]], "snapshot_id": snap["id"],
                                           "preferences_revision": prefs["revision"]}).json()
    assert plan["status"] == "feasible", plan
    assert len(plan["sessions"]) == 1
    return task, plan


def proposal(api, plan):
    return api.post("/api/proposals", {"source_kind": "plan", "source_object_id": plan["id"],
                                       "expected_source_revision": plan["revision"], "mode": "live"}).json()


def test_live_calendar_requires_confirmation_and_replay_does_not_duplicate(api, live_calendar):
    _, plan = ready_plan(api)
    p = proposal(api, plan)
    assert p["status"] == "pending_review" and p["mode"] == "live"
    assert live_calendar == []  # Neither planning nor reviewing writes to a provider.
    body = {"expected_revision": p["revision"], "payload_hash": p["payload_hash"]}
    headers = {"Idempotency-Key": uuid.uuid4().hex}
    confirmed = api.post(f"/api/proposals/{p['id']}/confirm", body, headers=headers)
    assert confirmed.status_code == 202 and confirmed.json()["status"] == "executed"
    assert len(live_calendar) == 1
    event = json.loads(live_calendar[0].content)
    assert event["start"]["dateTime"] == p["payload"]["events"][0]["start"]
    assert not event.get("attendees")
    replay = api.post(f"/api/proposals/{p['id']}/confirm", body, headers=headers)
    assert replay.status_code == 202 and replay.json()["status"] == "executed"
    assert len(live_calendar) == 1


def test_live_calendar_refuses_synthetic_busy_times(api, live_calendar):
    _, plan = ready_plan(api, provider="mock")
    p = proposal(api, plan)
    assert p["status"] == "blocked" and "synthetic_plan_not_live" in p["blocking_fields"]
    assert live_calendar == []


def test_live_calendar_refuses_past_study_blocks(api, live_calendar):
    _, plan = ready_plan(api, start_offset=-1)
    p = proposal(api, plan)
    assert p["status"] == "blocked" and "past_study_session" in p["blocking_fields"]
    assert live_calendar == []


def test_live_calendar_requires_google_write_scope(api, live_calendar):
    _, plan = ready_plan(api)
    with connect() as conn:
        conn.execute("UPDATE connections SET scopes_json='[]' WHERE id='conn_google'")
    p = proposal(api, plan)
    assert p["status"] == "blocked" and "missing_permission:google:study_calendar" in p["blocking_fields"]
    assert live_calendar == []


def test_manual_tasks_stay_visible_with_a_real_mailbox(api, live_calendar):
    task, _ = ready_plan(api)
    synthetic = api.post("/api/demo/planning-scenario", {"effort_minutes": 360}).json()
    assert api.get("/api/preferences").json()["show_demo_data_effective"] is False
    visible = {t["id"] for t in api.get("/api/tasks").json()["items"]}
    assert task["id"] in visible and synthetic["id"] not in visible
