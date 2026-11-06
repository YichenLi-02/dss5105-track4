"""Writing study blocks to an Outlook study calendar, against a fake Microsoft Graph (httpx.MockTransport):
the app creates its own calendar, writes only inside it (no attendees, UTC times, retry-safe transactionId),
reads it back on the next plan and moves a block by creating the new event and deleting the old one there.
Nothing else in the mailbox is written. Isolated database; no real Microsoft service is contacted."""
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.config import settings
from app.db import connect, dumps, init_db, now_iso
from app.providers import net, tokens

SGT = ZoneInfo("Asia/Singapore")
CAL = "AAMkStudyCalendar=="
READ_SCOPE = ("https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/User.Read "
              "https://graph.microsoft.com/Calendars.Read openid profile email offline_access")


def _graph_event(ev_id, start, end, show="busy"):
    utc = lambda s: datetime.fromisoformat(s).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0000000")
    return {"id": ev_id, "showAs": show, "isCancelled": False, "start": {"dateTime": utc(start)}, "end": {"dateTime": utc(end)}}


@pytest.fixture
def ms(api, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "outlook-study.sqlite3")
    monkeypatch.setattr(settings, "microsoft_client_id", "00000000-0000-0000-0000-00000000c1d0")
    monkeypatch.setattr(settings, "microsoft_client_secret", "secret-value")
    monkeypatch.setattr(settings, "microsoft_tenant_id", "common")
    monkeypatch.setattr(settings, "app_mode", "live")
    monkeypatch.setattr(settings, "enable_external_writes", True)
    init_db()
    tokens.use_memory_store(True)
    prefs = api.get("/api/preferences").json()
    api.patch("/api/preferences", {"expected_revision": prefs["revision"], "enable_external_writes": True,
                                   "weekly_flex_minutes": 0})
    st = {"scope": READ_SCOPE, "primary": [], "study": {}, "calendars": [], "deletes": [], "other_writes": [], "n": 0}

    def handler(req: httpx.Request):
        host, path, method = req.url.host, req.url.path, req.method
        if host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "at", "refresh_token": "rt", "expires_in": 3600,
                                             "scope": st["scope"]})
        if host != "graph.microsoft.com":
            return httpx.Response(404)
        study = f"/v1.0/me/calendars/{CAL}"
        if method == "GET" and path == "/v1.0/me":
            return httpx.Response(200, json={"mail": None, "userPrincipalName": "student@outlook.com"})
        if method == "GET" and path == "/v1.0/me/calendarView":
            return httpx.Response(200, json={"value": [_graph_event(f"p{i}", s, e) for i, (s, e) in enumerate(st["primary"])]})
        if method == "GET" and path == f"{study}/calendarView":
            return httpx.Response(200, json={"value": [
                {"id": k, "showAs": v["showAs"], "isCancelled": False,
                 "start": {"dateTime": v["start"]["dateTime"] + ".0000000"}, "end": {"dateTime": v["end"]["dateTime"] + ".0000000"}}
                for k, v in st["study"].items()]})
        if method == "GET" and path.endswith("/messages"):
            return httpx.Response(200, json={"value": []})
        if method == "POST" and path == "/v1.0/me/calendars":
            st["calendars"].append(json.loads(req.content)["name"])
            return httpx.Response(201, json={"id": CAL, "name": st["calendars"][-1]})
        if method == "POST" and path == f"{study}/events":
            st["n"] += 1
            ev_id = f"AAMkEvent{st['n']}"
            st["study"][ev_id] = json.loads(req.content)
            return httpx.Response(201, json={"id": ev_id})
        if method == "DELETE" and path.startswith(f"{study}/events/"):
            ev_id = path.rsplit("/", 1)[1]
            st["deletes"].append(ev_id)
            return httpx.Response(204) if st["study"].pop(ev_id, None) else httpx.Response(404)
        if method != "GET":
            st["other_writes"].append((method, path))  # anything written outside the study calendar
        return httpx.Response(404)

    net.set_transport(httpx.MockTransport(handler))
    try:
        yield st
    finally:
        net.set_transport(None)
        tokens.use_memory_store(False)


def authorize(api, capability):
    r = api.post("/api/connections/microsoft/authorize", {"capability": capability}).json()
    q = parse_qs(urlparse(r["authorization_url"]).query)
    cb = api.c.get(f"/api/connections/microsoft/callback?code=abc&state={q['state'][0]}", follow_redirects=False)
    assert cb.status_code == 303, cb.text
    return q["scope"][0].split()


def ms_conn(api):
    return next(c for c in api.get("/api/connections").json()["items"] if c["provider"] == "microsoft")


def confirm(api, p):
    return api.post(f"/api/proposals/{p['id']}/confirm", {"expected_revision": p["revision"], "payload_hash": p["payload_hash"]},
                    headers={"Idempotency-Key": uuid.uuid4().hex}).json()


def propose(api, kind, object_id, revision):
    return api.post("/api/proposals", {"source_kind": kind, "source_object_id": object_id,
                                       "expected_source_revision": revision, "mode": "live"}).json()


def snapshot(api, t0, days=3):
    return api.post("/api/calendar/snapshots", {
        "provider": "microsoft", "connection_id": "conn_microsoft", "time_min": t0.isoformat(),
        "time_max": (t0 + timedelta(days=days)).isoformat(), "calendar_ids": [], "display_timezone": "Asia/Singapore"}).json()


def preview(api, ids, t0):
    snap = snapshot(api, t0)
    assert snap["status"] == "complete", snap
    rev = api.get("/api/preferences").json()["revision"]
    return api.post("/api/plans/preview", {"task_ids": ids, "snapshot_id": snap["id"], "preferences_revision": rev}).json()


def task(api, minutes, due):
    t = api.post("/api/tasks", {"title": "Lab report"}).json()
    return api.patch(f"/api/tasks/{t['id']}", {"expected_revision": t["revision"], "official_date": due.isoformat(),
                                               "official_time": "18:00", "source_timezone": "Asia/Singapore",
                                               "estimated_minutes": minutes, "status": "confirmed"}).json()


def next_saturday(hour=9):
    d = datetime.now(SGT).date() + timedelta(days=1)
    while d.weekday() != 5:
        d += timedelta(days=1)
    return datetime(d.year, d.month, d.day, hour, tzinfo=SGT)


def test_outlook_study_calendar_create_write_read_back_and_move(api, ms):
    authorize(api, "read_busy")
    assert not ms_conn(api)["capabilities"]["study_calendar"]
    ms["scope"] = READ_SCOPE + " https://graph.microsoft.com/Calendars.ReadWrite"
    scopes = authorize(api, "study_calendar")
    assert "Calendars.ReadWrite" in scopes and "Calendars.Read" in scopes and "Mail.Send" not in scopes
    c = ms_conn(api)
    assert c["capabilities"]["study_calendar"] and c["capabilities"]["read_busy"]

    p = propose(api, "connection", "conn_microsoft", c["revision"])
    assert p["status"] == "pending_review" and p["payload"]["connection_id"] == "conn_microsoft", p
    assert ms["calendars"] == []  # nothing is created before the student confirms
    assert confirm(api, p)["status"] == "executed" and ms["calendars"] == [p["payload"]["summary"]]
    twice = propose(api, "connection", "conn_microsoft", ms_conn(api)["revision"])
    assert twice["status"] == "blocked" and "study_calendar_exists" in twice["blocking_fields"]

    t0 = next_saturday()
    ms["primary"].append(((t0).isoformat(), (t0 + timedelta(hours=1)).isoformat()))  # Saturday 09:00-10:00 is taken
    a = task(api, 60, t0.date() + timedelta(days=4))
    pl = preview(api, [a["id"]], t0)
    assert pl["status"] == "feasible" and datetime.fromisoformat(pl["sessions"][0]["start"]) >= t0 + timedelta(hours=1)
    w = propose(api, "plan", pl["id"], pl["revision"])
    assert w["status"] == "pending_review", w["blocking_fields"]
    assert (w["payload"]["connection_id"], w["payload"]["calendar_provider"]) == ("conn_microsoft", "microsoft")
    assert confirm(api, w)["status"] == "executed"
    (ev_id, ev), = ms["study"].items()
    assert ev["attendees"] == [] and ev["showAs"] == "busy" and ev["transactionId"] and ev["start"]["timeZone"] == "UTC"
    assert datetime.fromisoformat(ev["start"]["dateTime"] + "+00:00") == datetime.fromisoformat(pl["sessions"][0]["start"])
    assert ms["other_writes"] == []  # only the app's own study calendar was written

    again = preview(api, [a["id"]], t0)  # the next plan reads the Outlook study calendar back
    assert again["status"] == "feasible" and [s.get("kept") for s in again["sessions"]] == [True]

    blk = again["sessions"][0]
    fresh = api.post(f"/api/plans/{again['id']}/fresh-snapshot", {}).json()
    new_start = (datetime.fromisoformat(blk["start"]) + timedelta(hours=3)).isoformat()
    edited = api.post(f"/api/plans/{again['id']}/edit-block", {
        "expected_revision": again["revision"], "snapshot_id": fresh["id"],
        "preferences_revision": api.get("/api/preferences").json()["revision"],
        "task_id": a["id"], "start": blk["start"], "new_start": new_start})
    assert edited.status_code == 201, edited.text
    mv = propose(api, "plan", edited.json()["id"], edited.json()["revision"])
    assert mv["status"] == "pending_review", mv["blocking_fields"]
    assert mv["payload"]["remove_events"][0] | {"start": None, "end": None} == {
        "event_id": ev_id, "task_id": a["id"], "provider": "microsoft", "start": None, "end": None}
    assert confirm(api, mv)["status"] == "executed"
    assert ms["deletes"] == [ev_id] and ev_id not in ms["study"]
    (new_ev,) = ms["study"].values()
    assert datetime.fromisoformat(new_ev["start"]["dateTime"] + "+00:00") == datetime.fromisoformat(new_start)
    assert ms["other_writes"] == []


def test_outlook_plan_goes_to_the_study_calendar_that_exists(api, ms):
    authorize(api, "read_busy")
    with connect() as conn:  # only Google has the app's study calendar
        conn.execute("""INSERT INTO connections(id,provider,account_label,status,scopes_json,cursor_json,created_at,updated_at)
                        VALUES('conn_google','google','g','connected',?,?,?,?)""",
                     (dumps(["https://www.googleapis.com/auth/calendar.app.created",
                             "https://www.googleapis.com/auth/calendar.events.freebusy"]),
                      dumps({"app_calendar_id": "g-study"}), now_iso(), now_iso()))
    t0 = next_saturday()
    a = task(api, 60, t0.date() + timedelta(days=4))
    pl = preview(api, [a["id"]], t0)
    p = propose(api, "plan", pl["id"], pl["revision"])
    assert (p["payload"]["connection_id"], p["payload"]["calendar_provider"]) == ("conn_google", "google")
