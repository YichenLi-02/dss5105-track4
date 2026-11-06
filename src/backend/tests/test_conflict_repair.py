"""Conflict handling end to end through the API: a new meeting hits a planned block, the student compares repair
options and picks one, edits a block by hand (hard limits refused, soft rules only after explicit acceptance),
an already-written block is moved in the study calendar (new event created, old one deleted), and past written
blocks get a "did you do it?" check-in. Isolated database, mocked calendar."""
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
CAL = "study-cal"
WEEK0 = datetime(2026, 10, 19, 8, 0, tzinfo=SGT)  # the offline sample week


@pytest.fixture
def isolated(api, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "conflicts.sqlite3")
    init_db()
    yield


@pytest.fixture
def live(api, isolated, monkeypatch):
    monkeypatch.setattr(settings, "app_mode", "live")
    monkeypatch.setattr(settings, "enable_external_writes", True)
    prefs = api.get("/api/preferences").json()
    api.patch("/api/preferences", {"expected_revision": prefs["revision"], "enable_external_writes": True,
                                   "weekly_flex_minutes": 0})
    with connect() as conn:
        conn.execute("""INSERT INTO connections(id,provider,account_label,status,scopes_json,cursor_json,created_at,updated_at)
                        VALUES('conn_google','google','unit test','connected',?,?,?,?)""",
                     (dumps(["https://www.googleapis.com/auth/calendar.app.created",
                             "https://www.googleapis.com/auth/calendar.events.freebusy"]),
                      dumps({"app_calendar_id": CAL}), now_iso(), now_iso()))
    st = {"primary": [], "study": {}, "writes": [], "deletes": []}

    def read_busy(conn, provider, cid, t0, t1, tz, ids):
        items = list(st["study"].values()) if ids == [CAL] else st["primary"]
        items = [b for b in items if datetime.fromisoformat(b["start"]) < t1 and t0 < datetime.fromisoformat(b["end"])]
        return {"busy": [{**b, "kind": "busy", "source_id": "x"} for b in items], "errors": [], "status": "complete",
                "version": "v"}

    def handler(req):
        base = f"/calendar/v3/calendars/{CAL}/events"
        if req.method == "POST" and req.url.path == base:
            ev = json.loads(req.content)
            st["writes"].append(ev)
            st["study"][ev["id"]] = {"start": ev["start"]["dateTime"], "end": ev["end"]["dateTime"]}
            return httpx.Response(200, json={"id": ev["id"]})
        if req.method == "DELETE" and req.url.path.startswith(base + "/"):
            eid = req.url.path.rsplit("/", 1)[1]
            st["deletes"].append(eid)
            return httpx.Response(204) if st["study"].pop(eid, None) else httpx.Response(404)
        return httpx.Response(404)

    monkeypatch.setattr(calendars, "read_busy", read_busy)
    monkeypatch.setattr(oauth, "access_token", lambda *a: "unit-test-token")
    net.set_transport(httpx.MockTransport(handler))
    try:
        yield st
    finally:
        net.set_transport(None)


def rev(api):
    return api.get("/api/preferences").json()["revision"]


def snapshot(api, t0, days, provider="mock"):
    return api.post("/api/calendar/snapshots", {
        "provider": provider, "connection_id": "conn_google" if provider == "google" else None,
        "time_min": t0.isoformat(), "time_max": (t0 + timedelta(days=days)).isoformat(),
        "calendar_ids": ["primary"], "display_timezone": "Asia/Singapore"}).json()


def preview(api, ids, t0, days, provider="mock"):
    snap = snapshot(api, t0, days, provider)
    return api.post("/api/plans/preview", {"task_ids": ids, "snapshot_id": snap["id"], "preferences_revision": rev(api)}).json()


def options(api, p, t0, days, provider="mock"):
    snap = snapshot(api, t0, days, provider)
    r = api.post(f"/api/plans/{p['id']}/repair-options", {"snapshot_id": snap["id"], "preferences_revision": rev(api)})
    assert r.status_code == 201, r.text
    return r.json()


def propose(api, p, mode):
    return api.post("/api/proposals", {"source_kind": "plan", "source_object_id": p["id"],
                                       "expected_source_revision": p["revision"], "mode": mode}).json()


def confirm(api, p):
    return api.post(f"/api/proposals/{p['id']}/confirm", {"expected_revision": p["revision"], "payload_hash": p["payload_hash"]},
                    headers={"Idempotency-Key": uuid.uuid4().hex}).json()


def make_task(api, title, minutes, due, at="18:00"):
    t = api.post("/api/tasks", {"title": title}).json()
    return api.patch(f"/api/tasks/{t['id']}", {"expected_revision": t["revision"], "official_date": due.isoformat(),
                                               "official_time": at, "source_timezone": "Asia/Singapore",
                                               "estimated_minutes": minutes, "status": "confirmed"}).json()


def next_saturday(hour=9):
    d = datetime.now(SGT).date() + timedelta(days=1)
    while d.weekday() != 5:
        d += timedelta(days=1)
    return datetime(d.year, d.month, d.day, hour, tzinfo=SGT)


def overlaps(s, start, minutes):
    a, b = datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])
    st = datetime.fromisoformat(start)
    return a < st + timedelta(minutes=minutes) and st < b


def test_new_meeting_conflict_is_fixed_with_the_fewest_changes(api, isolated):
    task = api.post("/api/demo/planning-scenario", {"effort_minutes": 360}).json()
    plan = preview(api, [task["id"]], WEEK0, 5)
    assert plan["status"] == "feasible"
    first = plan["sessions"][0]
    assert api.post("/api/demo/busy", {"start": first["start"], "minutes": 30, "label": "TA office hour"}).status_code == 201

    snap = snapshot(api, WEEK0, 5)
    chk = api.post(f"/api/plans/{plan['id']}/conflicts", {"snapshot_id": snap["id"]}).json()
    assert chk["kind"] == "calendar" and len(chk["conflicts"]) == 1 and chk["needs_attention"]

    res = options(api, plan, WEEK0, 5)
    best = res["options"][0]
    assert best["recommended"] and best["strategy"] == "shift" and best["unmet"] == 0 and best["relaxed"] == []
    assert best["changed"] == 1  # only the clashing block moves, as one piece
    assert not any(overlaps(s, first["start"], 30) for s in best["plan"]["sessions"])
    assert propose(api, best["plan"], "demo")["status"] == "blocked"  # not chosen yet

    adopted = api.post(f"/api/plans/{best['plan']['id']}/adopt", {"expected_revision": best["plan"]["revision"]}).json()
    assert adopted["status"] == "feasible" and adopted["previous_plan_id"] == plan["id"]
    assert api.get("/api/plans/latest").json()["id"] == adopted["id"]
    assert api.get(f"/api/plans/{plan['id']}").json()["status"] == "stale"
    again = api.post(f"/api/plans/{best['plan']['id']}/adopt", {"expected_revision": adopted["revision"]})
    assert again.status_code == 409  # a choice is made once
    p = propose(api, adopted, "demo")
    assert p["status"] == "pending_review" and confirm(api, p)["status"] == "simulated"
    assert api.delete("/api/demo/busy").json()["items"] == []


def test_work_that_no_longer_fits_gets_labelled_relaxations_and_an_extension_hint(api, isolated):
    task = api.post("/api/demo/planning-scenario", {"effort_minutes": 18 * 60}).json()
    plan = preview(api, [task["id"]], WEEK0, 5)
    assert plan["status"] == "infeasible"
    res = options(api, plan, WEEK0, 5)
    assert res["kind"] == "capacity" and res["extension_suggested"]
    relaxed = [o for o in res["options"] if o["relaxed"]]
    assert relaxed and relaxed[0]["unmet"] < plan["unmet_minutes"]
    assert all(o["plan"]["status"] == "stale" for o in res["options"])  # nothing replaced until one is chosen


def test_manual_edit_refuses_hard_limits_and_asks_before_breaking_soft_rules(api, isolated):
    task = api.post("/api/demo/planning-scenario", {"effort_minutes": 360}).json()
    plan = preview(api, [task["id"]], WEEK0, 5)
    s0 = plan["sessions"][0]

    def edit(p, **kw):
        snap = snapshot(api, WEEK0, 5)
        return api.post(f"/api/plans/{p['id']}/edit-block", {"expected_revision": p["revision"], "snapshot_id": snap["id"],
                                                              "preferences_revision": rev(api), "task_id": s0["task_id"], **kw})

    r = edit(plan, start=s0["start"], new_start="2026-10-23T09:30:00+08:00")  # Friday 09:00-11:00 is a class
    assert r.status_code == 422 and "overlaps_calendar_event" in r.json()["error"]["details"]
    r = edit(plan, start=s0["start"], new_start="2026-10-23T16:00:00+08:00", minutes=120)
    assert r.status_code == 422 and "after_deadline" in r.json()["error"]["details"]

    moved = edit(plan, start=s0["start"], new_start="2026-10-23T11:15:00+08:00").json()
    blk = next(s for s in moved["sessions"] if s["start"] == "2026-10-23T11:15:00+08:00")
    assert blk["locked"] and moved["status"] == "feasible" and sum(s["minutes"] for s in moved["sessions"]) == 360

    r = edit(moved, start=blk["start"], minutes=100)  # longer than the 90-minute session maximum
    assert r.status_code == 409 and r.json()["error"]["code"] == "SOFT_RULES"
    soft = r.json()["error"]["details"]
    ok = edit(moved, start=blk["start"], minutes=100, acknowledge=soft).json()
    assert ok["status"] == "feasible" and ok["violations"] == soft and ok["inputs"]["overrides"] == soft
    assert sum(s["minutes"] for s in ok["sessions"]) == 360  # the extra time came off a later suggestion

    gone = edit(ok, start=blk["start"], remove=True).json()
    assert gone["status"] == "feasible" and gone["inputs"]["overrides"] == []
    assert sum(s["minutes"] for s in gone["sessions"]) == 360


def test_written_block_hit_by_a_meeting_is_moved_in_the_study_calendar(api, live):
    t0 = next_saturday()
    a = make_task(api, "A", 60, t0.date() + timedelta(days=4))
    first = preview(api, [a["id"]], t0, 3, "google")
    assert confirm(api, propose(api, first, "live"))["status"] == "executed"
    old_id, old = next(iter(live["study"].items()))
    live["primary"].append({"start": old["start"], "end": (datetime.fromisoformat(old["start"]) + timedelta(minutes=30)).isoformat()})

    again = preview(api, [a["id"]], t0, 3, "google")
    res = options(api, again, t0, 3, "google")
    best = res["options"][0]
    assert res["conflicts"][0]["written"] and best["moves_written"] == 1 and best["unmet"] == 0
    adopted = api.post(f"/api/plans/{best['plan']['id']}/adopt", {"expected_revision": best["plan"]["revision"]}).json()
    p = propose(api, adopted, "live")
    assert p["status"] == "pending_review" and p["payload"]["remove_events"][0]["event_id"] == old_id
    assert live["deletes"] == []  # nothing changes before the student confirms
    r = confirm(api, p)
    assert r["status"] == "executed", r
    assert live["deletes"] == [old_id] and old_id not in live["study"] and len(live["study"]) == 1
    final = preview(api, [a["id"]], t0, 3, "google")
    assert final["status"] == "feasible" and [s.get("kept") for s in final["sessions"]] == [True]


def test_past_written_blocks_get_one_check_in(api, live):
    a = make_task(api, "A", 120, (datetime.now(SGT) + timedelta(days=3)).date())
    end = datetime.now(SGT).replace(second=0, microsecond=0) - timedelta(hours=2)
    start = end - timedelta(minutes=60)
    with connect() as conn:  # a block written earlier that is over now
        conn.execute("""INSERT INTO proposals(id,session_id_hash,operation,mode,connection_id,source_kind,source_object_id,
                        source_revision,dependencies_json,payload_json,payload_hash,nonce_hash,expires_at,status,result_json,
                        created_at,updated_at) VALUES('prop_x','h','create_study_events','live',NULL,'plan','plan_x',1,'{}',?,?,?,?,?,?,?,?)""",
                     (dumps({"events": [{"task_id": a["id"], "title": "Study: A", "start": start.isoformat(), "end": end.isoformat()}]}),
                      "0" * 64, "0" * 64, now_iso(), "executed",
                      dumps({"events": [{"event_id": "ev_past", "status": "executed"}]}), now_iso(), now_iso()))
    items = api.get("/api/study-checkins").json()["items"]
    assert [x["key"] for x in items] == ["ev_past"]
    r = api.post("/api/study-checkins", {"key": "ev_past", "outcome": "partial", "minutes": 45}).json()
    assert r["task"]["completed_minutes"] == 45
    again = api.post("/api/study-checkins", {"key": "ev_past", "outcome": "done"}).json()
    assert again["replayed"] and again["task"]["completed_minutes"] == 45
    assert api.get("/api/study-checkins").json()["items"] == []
    c = api.get("/api/calibration").json()["completion"]  # the block's planned length is kept with the answer
    assert (c["checkins"], c["planned_minutes"], c["done_minutes"]) == (1, 60, 45)


def test_write_stopped_by_a_new_meeting_can_be_repaired_and_saved(api, live):
    t0 = next_saturday()
    a = make_task(api, "A", 60, t0.date() + timedelta(days=4))
    pl = preview(api, [a["id"]], t0, 3, "google")
    p = propose(api, pl, "live")
    s = datetime.fromisoformat(pl["sessions"][0]["start"])
    live["primary"].append({"start": (s + timedelta(minutes=30)).isoformat(), "end": (s + timedelta(minutes=60)).isoformat()})
    r = confirm(api, p)
    assert r["status"] == "invalidated" and r["result"]["reason"] == "calendar_conflict" and live["writes"] == []
    best = options(api, pl, t0, 3, "google")["options"][0]
    assert best["unmet"] == 0 and best["changed"] == 1
    adopted = api.post(f"/api/plans/{best['plan']['id']}/adopt", {"expected_revision": best["plan"]["revision"]}).json()
    p2 = propose(api, adopted, "live")
    assert p2["status"] == "pending_review", p2["blocking_fields"]
    assert confirm(api, p2)["status"] == "executed" and len(live["writes"]) == 1


def test_checks_reread_the_plans_own_calendar_and_days(api, live):
    t0 = next_saturday()
    a = make_task(api, "A", 60, t0.date() + timedelta(days=4))
    pl = preview(api, [a["id"]], t0, 3, "google")
    first = pl["sessions"][0]
    live["primary"].append({"start": first["start"], "end": (datetime.fromisoformat(first["start"]) + timedelta(minutes=30)).isoformat()})
    # The page may meanwhile show another source or start day for the next plan; checking this one ignores that.
    snap = api.post(f"/api/plans/{pl['id']}/fresh-snapshot", {})
    assert snap.status_code == 201, snap.text
    s = snap.json()
    assert (s["provider"], s["connection_id"], s["time_min"], s["time_max"]) == ("google", "conn_google", t0.isoformat(),
                                                                                (t0 + timedelta(days=3)).isoformat())
    chk = api.post(f"/api/plans/{pl['id']}/conflicts", {"snapshot_id": s["id"]}).json()
    assert chk["kind"] == "calendar" and len(chk["conflicts"]) == 1  # the meeting added after planning is found


def test_a_plan_whose_days_are_over_is_not_reread(api, live):
    past = next_saturday() - timedelta(days=14)
    a = make_task(api, "A", 60, past.date() + timedelta(days=2))
    pl = preview(api, [a["id"]], past, 2, "google")
    r = api.post(f"/api/plans/{pl['id']}/fresh-snapshot", {})
    assert r.status_code == 409 and r.json()["error"]["code"] == "PLAN_WINDOW_OVER"
    assert api.post("/api/plans/plan_missing/fresh-snapshot", {}).status_code == 404
