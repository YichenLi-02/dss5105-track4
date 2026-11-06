"""Planning rules from the group review: daily cap across all tasks, written study blocks are not planned twice,
and free/busy is read again right before a real calendar write. Isolated database, mocked calendar."""
import json
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.config import settings
from app.db import connect, dumps, init_db, now_iso
from app.providers import calendars, net, oauth

SGT = ZoneInfo("Asia/Singapore")
CAL = "study-cal"


@pytest.fixture
def isolated(api, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "planning-rules.sqlite3")
    init_db()
    prefs = api.get("/api/preferences").json()
    api.patch("/api/preferences", {"expected_revision": prefs["revision"], "weekly_flex_minutes": 0})
    yield


@pytest.fixture
def live(api, isolated, monkeypatch):
    monkeypatch.setattr(settings, "app_mode", "live")
    monkeypatch.setattr(settings, "enable_external_writes", True)
    prefs = api.get("/api/preferences").json()
    api.patch("/api/preferences", {"expected_revision": prefs["revision"], "enable_external_writes": True})
    with connect() as conn:
        conn.execute("""INSERT INTO connections(id,provider,account_label,status,scopes_json,cursor_json,created_at,updated_at)
                        VALUES('conn_google','google','unit test','connected',?,?,?,?)""",
                     (dumps(["https://www.googleapis.com/auth/calendar.app.created",
                             "https://www.googleapis.com/auth/calendar.events.freebusy"]),
                      dumps({"app_calendar_id": CAL}), now_iso(), now_iso()))
    st = {"primary": [], "study": [], "fail": set(), "writes": []}

    def read_busy(conn, provider, cid, t0, t1, tz, ids):
        which = "study" if ids == [CAL] else "primary"
        if which in st["fail"]:
            return {"busy": [], "errors": [f"{which}: backendError"], "status": "failed", "version": "x"}
        items = [b for b in st[which] if datetime.fromisoformat(b["start"]) < t1 and t0 < datetime.fromisoformat(b["end"])]
        return {"busy": [{**b, "kind": "busy", "source_id": f"google:{which}"} for b in items], "errors": [],
                "status": "complete", "version": "v"}

    def handler(req):
        if req.method == "POST" and req.url.path == f"/calendar/v3/calendars/{CAL}/events":
            ev = json.loads(req.content)
            st["writes"].append(ev)
            st["study"].append({"start": ev["start"]["dateTime"], "end": ev["end"]["dateTime"]})
            return httpx.Response(200, json={"id": ev["id"]})
        return httpx.Response(404)

    monkeypatch.setattr(calendars, "read_busy", read_busy)
    monkeypatch.setattr(oauth, "access_token", lambda *a: "unit-test-token")
    net.set_transport(httpx.MockTransport(handler))
    try:
        yield st
    finally:
        net.set_transport(None)


def next_saturday(hour=9) -> datetime:
    d = datetime.now(SGT).date() + timedelta(days=1)
    while d.weekday() != 5:  # the synthetic calendar has no busy time on Saturdays
        d += timedelta(days=1)
    return datetime(d.year, d.month, d.day, hour, tzinfo=SGT)


def make_task(api, title, minutes, due: date):
    t = api.post("/api/tasks", {"title": title}).json()
    return api.patch(f"/api/tasks/{t['id']}", {"expected_revision": t["revision"], "official_date": due.isoformat(),
                                               "official_time": "18:00", "source_timezone": "Asia/Singapore",
                                               "estimated_minutes": minutes, "status": "confirmed"}).json()


def log(api, task, minutes, when, event_id=None):
    cur = api.get(f"/api/tasks/{task['id']}").json()
    return api.post(f"/api/tasks/{task['id']}/progress", {"expected_revision": cur["revision"], "minutes": minutes,
                                                          "client_event_id": event_id or uuid.uuid4().hex,
                                                          "occurred_at": when.isoformat()}).json()


def plan(api, ids, t0, provider="mock", days=3):
    snap = api.post("/api/calendar/snapshots", {
        "provider": provider, "connection_id": "conn_google" if provider == "google" else None,
        "time_min": t0.isoformat(), "time_max": (t0 + timedelta(days=days)).isoformat(),
        "calendar_ids": ["primary"], "display_timezone": "Asia/Singapore"}).json()
    prefs = api.get("/api/preferences").json()
    return api.post("/api/plans/preview", {"task_ids": ids, "snapshot_id": snap["id"],
                                           "preferences_revision": prefs["revision"]}).json()


def propose(api, p):
    return api.post("/api/proposals", {"source_kind": "plan", "source_object_id": p["id"],
                                       "expected_source_revision": p["revision"], "mode": "live"}).json()


def confirm(api, p):
    return api.post(f"/api/proposals/{p['id']}/confirm", {"expected_revision": p["revision"],
                                                          "payload_hash": p["payload_hash"]},
                    headers={"Idempotency-Key": uuid.uuid4().hex})


def day(p, d):
    return next(x for x in p["days"] if x["date"] == d.isoformat())


def test_daily_cap_counts_work_logged_on_other_tasks(api, isolated):
    sat = next_saturday()
    a = make_task(api, "A", 240, sat.date() + timedelta(days=4))
    b = make_task(api, "B", 300, sat.date() + timedelta(days=4))
    log(api, a, 60, sat.replace(hour=8))
    only_b = plan(api, [b["id"]], sat)
    assert day(only_b, sat.date())["completed"] == 60 and day(only_b, sat.date())["planned"] == 60
    both = plan(api, [a["id"], b["id"]], sat)
    assert day(both, sat.date())["planned"] == 60 and both["violations"] == []


def test_progress_is_recorded_only_on_the_chosen_task_and_replays_safely(api, isolated):
    sat = next_saturday()
    a = make_task(api, "A", 120, sat.date() + timedelta(days=4))
    b = make_task(api, "B", 120, sat.date() + timedelta(days=4))
    eid = uuid.uuid4().hex
    log(api, b, 45, sat, eid)
    log(api, b, 45, sat, eid)  # same request sent twice
    assert api.get(f"/api/tasks/{b['id']}").json()["completed_minutes"] == 45
    assert api.get(f"/api/tasks/{a['id']}").json()["completed_minutes"] == 0


def test_written_block_is_kept_and_not_written_again(api, live):
    t0 = next_saturday()
    a = make_task(api, "A", 60, t0.date() + timedelta(days=4))
    first = plan(api, [a["id"]], t0, "google")
    assert first["status"] == "feasible" and len(first["sessions"]) == 1
    assert confirm(api, propose(api, first)).json()["status"] == "executed" and len(live["writes"]) == 1

    again = plan(api, [a["id"]], t0, "google")
    assert again["status"] == "feasible" and [s.get("kept") for s in again["sessions"]] == [True]
    p = propose(api, again)
    assert p["status"] == "blocked" and "no_new_study_sessions" in p["blocking_fields"]
    assert len(live["writes"]) == 1

    b = make_task(api, "B", 150, t0.date() + timedelta(days=4))
    both = plan(api, [a["id"], b["id"]], t0, "google")
    kept = next(s for s in both["sessions"] if s.get("kept"))
    ks, ke = datetime.fromisoformat(kept["start"]), datetime.fromisoformat(kept["end"])
    for s in (x for x in both["sessions"] if not x.get("kept")):
        ss, se = datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])
        assert se <= ks or ke <= ss
    assert both["violations"] == [] and day(both, ks.astimezone(SGT).date())["planned"] <= 120
    assert {e["task_id"] for e in propose(api, both)["payload"]["events"]} == {b["id"]}


def test_block_removed_in_calendar_is_suggested_again(api, live):
    t0 = next_saturday()
    a = make_task(api, "A", 60, t0.date() + timedelta(days=4))
    confirm(api, propose(api, plan(api, [a["id"]], t0, "google")))
    live["study"].clear()
    again = plan(api, [a["id"]], t0, "google")
    assert not any(s.get("kept") for s in again["sessions"]) and again["per_task"][0]["planned"] == 60
    assert any(b.startswith("study_block_removed_in_calendar") for b in again["binding_constraints"])


def test_meeting_added_after_preview_blocks_the_write(api, live):
    t0 = next_saturday()
    a = make_task(api, "A", 60, t0.date() + timedelta(days=4))
    pl = plan(api, [a["id"]], t0, "google")
    p = propose(api, pl)
    start = datetime.fromisoformat(pl["sessions"][0]["start"])
    live["primary"].append({"start": (start + timedelta(minutes=30)).isoformat(),
                            "end": (start + timedelta(minutes=60)).isoformat()})
    r = confirm(api, p).json()
    assert r["status"] == "invalidated" and r["result"]["reason"] == "calendar_conflict"
    assert live["writes"] == []
    assert api.get(f"/api/plans/{pl['id']}").json()["status"] == "stale"
    assert confirm(api, p).status_code == 409  # the used approval cannot be confirmed again


def test_failed_reread_pauses_the_write(api, live):
    t0 = next_saturday()
    a = make_task(api, "A", 60, t0.date() + timedelta(days=4))
    p = propose(api, plan(api, [a["id"]], t0, "google"))
    live["fail"].add("primary")
    r = confirm(api, p).json()
    assert r["status"] == "invalidated" and r["result"]["reason"] == "busy_recheck_failed"
    assert live["writes"] == []


def set_prefs(api, **kw):
    prefs = api.get("/api/preferences").json()
    r = api.patch("/api/preferences", {"expected_revision": prefs["revision"], **kw})
    assert r.status_code == 200, r.text
    return r.json()


def by_task_day(p):
    out = {}
    for s in p["sessions"]:
        k = (s["task_id"], s["start"][:10])
        out[k] = out.get(k, 0) + s["minutes"]
    return out


def test_one_task_gets_at_most_the_per_task_cap_each_day(api, isolated):
    assert api.get("/api/preferences").json()["task_daily_cap_minutes"] == 120  # on by default
    set_prefs(api, daily_cap_minutes=240)
    sat = next_saturday()
    a = make_task(api, "A", 300, sat.date() + timedelta(days=4))
    b = make_task(api, "B", 120, sat.date() + timedelta(days=4))
    p = plan(api, [a["id"], b["id"]], sat, days=3)
    assert p["status"] == "feasible" and p["violations"] == []
    per = by_task_day(p)
    assert max(per.values()) <= 120 and day(p, sat.date())["planned"] <= 240
    assert per[(a["id"], sat.date().isoformat())] == 120  # the day cap alone would have allowed more

    log(api, a, 90, sat.replace(hour=8))  # 90 minutes on A already done that morning
    again = plan(api, [a["id"]], sat, days=3)
    assert by_task_day(again).get((a["id"], sat.date().isoformat()), 0) <= 30 and again["violations"] == []


def test_per_task_cap_that_makes_work_impossible_is_reported(api, isolated):
    set_prefs(api, daily_cap_minutes=240)
    sat = next_saturday()
    a = make_task(api, "A", 300, sat.date() + timedelta(days=1))  # due Sunday 18:00: two days at 120 = 240 < 300
    p = plan(api, [a["id"]], sat, days=2)
    assert p["status"] == "infeasible" and p["unmet_minutes"] == 60
    assert any(b.startswith(f"task_daily_cap:{a['id']}:300:240") for b in p["binding_constraints"])


def test_editing_past_the_per_task_cap_needs_explicit_acceptance(api, isolated):
    set_prefs(api, daily_cap_minutes=240)
    sat = next_saturday()
    a = make_task(api, "A", 300, sat.date() + timedelta(days=4))
    p = plan(api, [a["id"]], sat, days=3)
    first = p["sessions"][1]  # the second block of the day: making it longer overlaps nothing
    assert first["start"][:10] == sat.date().isoformat() and by_task_day(p)[(a["id"], sat.date().isoformat())] == 120
    snap = api.post("/api/calendar/snapshots", {"provider": "mock", "connection_id": None, "time_min": sat.isoformat(),
                                                 "time_max": (sat + timedelta(days=3)).isoformat(), "calendar_ids": ["primary"],
                                                 "display_timezone": "Asia/Singapore"}).json()
    body = {"expected_revision": p["revision"], "snapshot_id": snap["id"],
            "preferences_revision": api.get("/api/preferences").json()["revision"],
            "task_id": a["id"], "start": first["start"], "minutes": 90}
    r = api.post(f"/api/plans/{p['id']}/edit-block", body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "SOFT_RULES"
    soft = r.json()["error"]["details"]
    assert any(x.startswith("task_daily_cap_exceeded:") for x in soft)
    ok = api.post(f"/api/plans/{p['id']}/edit-block", {**body, "acknowledge": soft})
    assert ok.status_code == 201 and ok.json()["status"] == "feasible"


def test_per_task_cap_below_the_session_minimum_is_rejected(api, isolated):
    prefs = api.get("/api/preferences").json()
    r = api.patch("/api/preferences", {"expected_revision": prefs["revision"], "task_daily_cap_minutes": 20})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_PREFERENCES"
    assert set_prefs(api, task_daily_cap_minutes=0)["task_daily_cap_minutes"] == 0  # 0 = no separate limit
