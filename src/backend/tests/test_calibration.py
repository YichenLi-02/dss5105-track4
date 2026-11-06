"""Estimate calibration: suggestions from finished tasks, overrun questions, completion rate. Suggestions only -
nothing changes until the student accepts. Isolated database."""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.db import connect, init_db
from app.services import calibration as C


@pytest.fixture
def isolated(api, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "calibration.sqlite3")
    init_db()
    yield


def S(i, est, actual, course="CS1010", deliverable="submission"):
    return C.Sample(f"t{i}", f"T{i}", None, course, deliverable, est, actual, True)


# ------------------------------------------------------------------ the rules

def test_most_specific_group_with_enough_tasks_is_used():
    hist = [S(1, 100, 150), S(2, 100, 140), S(3, 100, 130), S(4, 100, 100, course="MA1521"),
            S(5, 100, 90, course="MA1521")]
    b = C.bias_for(hist, "CS1010", "submission")
    assert (b["group"], b["n"], b["ratio"]) == ("course", 3, 1.4)
    b = C.bias_for(hist, "MA1521", "submission")  # only 2 tasks in that course: falls back to the deliverable type
    assert (b["group"], b["n"], b["ratio"]) == ("deliverable", 5, 1.3)
    assert C.bias_for(hist[:2], "CS1010", None) is None  # fewer than 3 finished tasks: no suggestion at all


def test_suggestions_need_a_real_effect_and_more_evidence_to_shorten():
    assert C.suggest_minutes(200, 0, {"ratio": 1.4, "n": 3}) == 285  # 280 -> nearest quarter hour
    assert C.suggest_minutes(200, 0, {"ratio": 1.1, "n": 9}) is None  # under 15%: noise
    assert C.suggest_minutes(200, 0, {"ratio": 0.7, "n": 3}) is None  # shortening needs 5 finished tasks
    assert C.suggest_minutes(200, 0, {"ratio": 0.7, "n": 5}) == 165  # shortening goes only half the way (x0.85)
    assert C.suggest_minutes(100, 0, {"ratio": 3.5, "n": 5}) == 195  # capped at double (200), in quarter hours
    assert C.suggest_minutes(200, 180, {"ratio": 0.5, "n": 6}) == 195  # never below the time already spent


def test_completion_rate_and_weekly_slack():
    rows = [(60, 60)] * 5 + [(60, 30), (60, 0), (60, 0)]
    c = C.completion(rows, weeks=2, flex_now=60)
    assert c["rate"] == 0.69 and c["enough"] and c["flex_suggested"] == 60 + 90  # 75 missed min/week -> +90
    assert C.completion(rows[:4], weeks=1, flex_now=60)["flex_suggested"] is None  # too few check-ins
    assert C.completion([(60, 60)] * 6, weeks=1, flex_now=60)["flex_suggested"] is None  # doing fine
    assert C.completion([(60, 120)] * 3 + [(60, 0)] * 3, weeks=1, flex_now=0)["rate"] == 0.5  # extra does not cancel missed


# ------------------------------------------------------------------ through the API

def task(api, title, est=None, course="CS1010", due_days=10):
    t = api.post("/api/tasks", {"title": title, "course": course}).json()
    due = (datetime.now(timezone.utc) + timedelta(days=due_days)).date().isoformat()
    body = {"expected_revision": t["revision"], "official_date": due, "official_time": "18:00",
            "source_timezone": "Asia/Singapore", "status": "confirmed"}
    if est:
        body["estimated_minutes"] = est
    r = api.patch(f"/api/tasks/{t['id']}", body)
    assert r.status_code == 200, r.text
    return r.json()


def finish(api, t, actual):
    r = api.patch(f"/api/tasks/{t['id']}", {"expected_revision": t["revision"], "status": "completed", "actual_minutes": actual})
    assert r.status_code == 200, r.text
    return r.json()


def edit(api, t, **kw):
    r = api.patch(f"/api/tasks/{t['id']}", {"expected_revision": t["revision"], **kw})
    assert r.status_code == 200, r.text
    return r.json()


def cal(api):
    return api.get("/api/calibration").json()


def test_first_estimate_is_kept_when_the_estimate_changes(api, isolated):
    t = task(api, "Essay", 120)
    assert t["first_estimate_minutes"] == 120
    t = edit(api, t, estimated_minutes=150)
    assert (t["estimated_minutes"], t["first_estimate_minutes"]) == (150, 120)
    r = api.patch(f"/api/tasks/{t['id']}", {"expected_revision": t["revision"], "actual_minutes": 0})
    assert r.status_code == 422


def test_estimate_suggestion_from_finished_tasks_is_applied_only_when_accepted(api, isolated):
    for i, (est, actual) in enumerate([(100, 150), (120, 170), (200, 260)]):
        finish(api, task(api, f"Done {i}", est), actual)  # ratios 1.5, 1.42, 1.3 -> median 1.42
    other = task(api, "Other course", 100, course="MA1521")
    open_ = task(api, "Report", 200)
    changed = edit(api, task(api, "Already adjusted", 100), estimated_minutes=130)  # student changed it already
    c = cal(api)
    assert c["finished_tasks"] == 3
    by = {s["task_id"]: s for s in c["suggestions"]}
    s = by[open_["id"]]
    assert (s["current"], s["suggested"], s["ratio"], s["group"], s["n"]) == (200, 285, 1.42, "course", 3)
    assert {e["actual"] for e in s["evidence"]} == {150, 170, 260}
    assert by[other["id"]]["group"] == "deliverable"  # no MA1521 history yet: falls back to the deliverable type
    assert changed["id"] not in by
    assert api.get(f"/api/tasks/{open_['id']}").json()["estimated_minutes"] == 200  # nothing changed yet

    r = api.post("/api/calibration/decide", {"task_id": open_["id"], "expected_revision": open_["revision"], "decision": "accept"})
    assert r.status_code == 200, r.text
    assert r.json()["task"]["estimated_minutes"] == 285 and r.json()["task"]["first_estimate_minutes"] == 200
    again = api.post("/api/calibration/decide", {"task_id": open_["id"], "expected_revision": r.json()["task"]["revision"],
                                                  "decision": "accept"})
    assert again.status_code == 409 and again.json()["error"]["code"] == "NO_SUGGESTION"

    r = api.post("/api/calibration/decide", {"task_id": other["id"], "expected_revision": other["revision"], "decision": "keep"})
    assert r.status_code == 200 and r.json()["task"]["estimated_minutes"] == 100
    assert cal(api)["suggestions"] == []  # both answered once; never asked again


def test_stale_revision_is_refused(api, isolated):
    for i in range(3):
        finish(api, task(api, f"Done {i}", 100), 150)
    t = task(api, "Report", 100)
    edit(api, t, title="Report (renamed)")
    r = api.post("/api/calibration/decide", {"task_id": t["id"], "expected_revision": t["revision"], "decision": "accept"})
    assert r.status_code == 409


def test_a_task_that_used_up_its_estimate_asks_finished_or_how_much_more(api, isolated):
    a = task(api, "A", 60)
    a = api.post(f"/api/tasks/{a['id']}/progress", {"expected_revision": a["revision"], "client_event_id": "p1",
                                                    "minutes": 60, "occurred_at": datetime.now(timezone.utc).isoformat()}).json()
    over = cal(api)["overruns"]
    assert [(o["task_id"], o["estimate"], o["completed"]) for o in over] == [(a["id"], 60, 60)]
    r = api.post("/api/calibration/overrun", {"task_id": a["id"], "expected_revision": a["revision"], "finished": False,
                                              "more_minutes": 45})
    assert r.status_code == 200 and r.json()["task"]["estimated_minutes"] == 105
    assert cal(api)["overruns"] == []
    b = task(api, "B", 30)
    b = api.post(f"/api/tasks/{b['id']}/progress", {"expected_revision": b["revision"], "client_event_id": "p2",
                                                    "minutes": 40, "occurred_at": datetime.now(timezone.utc).isoformat()}).json()
    r = api.post("/api/calibration/overrun", {"task_id": b["id"], "expected_revision": b["revision"], "finished": True})
    t = r.json()["task"]
    assert (t["status"], t["actual_minutes"]) == ("completed", 40)
    bad = api.post("/api/calibration/overrun", {"task_id": a["id"], "expected_revision": 99, "finished": True})
    assert bad.status_code == 409 and bad.json()["error"]["code"] == "NO_OVERRUN"


def test_completion_rate_from_check_ins(api, isolated):
    t = task(api, "A", 600)
    now = datetime.now(timezone.utc)
    with connect() as conn:
        for i, done in enumerate([60, 60, 60, 60, 30, 0]):
            conn.execute("INSERT INTO study_checkins(block_key,task_id,outcome,minutes,planned_minutes,created_at) VALUES(?,?,?,?,?,?)",
                         (f"ev{i}", t["id"], "done" if done == 60 else "partial" if done else "missed", done, 60,
                          (now - timedelta(days=7 - i)).isoformat()))
        conn.execute("INSERT INTO study_checkins(block_key,task_id,outcome,minutes,planned_minutes,created_at) VALUES(?,?,?,?,?,?)",
                     ("old", t["id"], "missed", 0, 60, (now - timedelta(days=60)).isoformat()))  # outside the 4 weeks
    c = cal(api)["completion"]
    assert (c["checkins"], c["planned_minutes"], c["done_minutes"], c["rate"]) == (6, 360, 270, 0.75)
    assert c["flex_suggested"] == c["flex_now"] + 90


def test_demo_history_drives_the_sample_report_and_can_be_cleared(api, isolated):
    report = api.post("/api/demo/planning-scenario", {"effort_minutes": 360}).json()
    c = api.post("/api/demo/calibration-history", {}).json()
    s = next(x for x in c["suggestions"] if x["task_id"] == report["id"])
    assert (s["current"], s["suggested"], s["group"], s["n"]) == (360, 465, "course", 4)
    assert s["title_en"] == "DEMO5105 report (synthetic)"  # same fallback as the task board
    assert all(e["title_en"] and e["title_en"].startswith("Sample:") for e in s["evidence"])
    assert c["completion"]["rate"] == 0.69 and c["completion"]["flex_suggested"]
    assert api.post("/api/demo/calibration-history", {}).json()["finished_tasks"] == 4  # loading twice adds nothing
    api.post("/api/calibration/decide", {"task_id": report["id"], "expected_revision": report["revision"], "decision": "accept"})
    again = api.post("/api/demo/planning-scenario", {"effort_minutes": 360}).json()  # a fresh demo run asks again
    assert any(x["task_id"] == again["id"] for x in cal(api)["suggestions"])
    cleared = api.delete("/api/demo/calibration-history").json()
    assert cleared["finished_tasks"] == 0 and cleared["suggestions"] == [] and cleared["completion"]["checkins"] == 0


def test_demo_history_counts_only_while_demo_data_is_shown(api, isolated):
    api.post("/api/demo/calibration-history", {})
    prefs = api.get("/api/preferences").json()
    assert api.patch("/api/preferences", {"expected_revision": prefs["revision"], "show_demo_data": False}).status_code == 200
    assert api.post("/api/demo/calibration-history", {}).json()["error"]["code"] == "DEMO_ONLY"
    t = task(api, "Real task", 200, course="DEMO5105")
    c = cal(api)
    assert c["finished_tasks"] == 0 and c["completion"]["checkins"] == 0
    assert all(x["task_id"] != t["id"] for x in c["suggestions"])


def test_finished_synthetic_report_and_checkins_never_feed_real_calibration(api, isolated):
    report = api.post("/api/demo/planning-scenario", {"effort_minutes": 360}).json()
    finish(api, report, 510)
    api.post("/api/demo/calibration-history", {})
    with connect() as conn:
        conn.execute("INSERT INTO study_checkins(block_key,task_id,outcome,minutes,planned_minutes,created_at) VALUES(?,?,?,?,?,?)",
                     ("synthetic_report_checkin", report["id"], "missed", 0, 60, datetime.now(timezone.utc).isoformat()))
    assert cal(api)["finished_tasks"] == 5
    prefs = api.get("/api/preferences").json()
    api.patch("/api/preferences", {"expected_revision": prefs["revision"], "show_demo_data": False})
    real = task(api, "Real task", 100, course="DEMO5105")
    c = cal(api)
    assert c["finished_tasks"] == 0 and c["completion"]["checkins"] == 0
    assert c["suggestions"] == []
    assert all(t["id"] != report["id"] for t in api.get("/api/tasks").json()["items"])
    assert any(t["id"] == real["id"] for t in api.get("/api/tasks").json()["items"])


def test_weekly_flex_advice_waits_for_new_checkins_after_a_change(api, isolated):
    t = task(api, "A", 600)
    now = datetime.now(timezone.utc)
    with connect() as conn:
        for i, done in enumerate([60, 60, 60, 60, 30, 0]):
            conn.execute("INSERT INTO study_checkins(block_key,task_id,outcome,minutes,planned_minutes,created_at) VALUES(?,?,?,?,?,?)",
                         (f"flex{i}", t["id"], "done" if done == 60 else "partial" if done else "missed", done, 60,
                          (now - timedelta(days=7 - i)).isoformat()))
    completion = cal(api)["completion"]
    assert completion["flex_suggested"] > completion["flex_now"]
    prefs = api.get("/api/preferences").json()
    changed = api.patch("/api/preferences", {"expected_revision": prefs["revision"],
                         "weekly_flex_minutes": completion["flex_suggested"]}).json()
    assert cal(api)["completion"]["flex_suggested"] is None
    api.patch("/api/preferences", {"expected_revision": changed["revision"], "ui_language": "en"})
    assert cal(api)["completion"]["flex_suggested"] is None
    with connect() as conn:
        conn.execute("INSERT INTO study_checkins(block_key,task_id,outcome,minutes,planned_minutes,created_at) VALUES(?,?,?,?,?,?)",
                     ("new_flex_answer", t["id"], "missed", 0, 60, (now + timedelta(seconds=2)).isoformat()))
    assert cal(api)["completion"]["flex_suggested"] > changed["weekly_flex_minutes"]


def test_completed_demo_report_can_start_again_without_old_actual_time(api, isolated):
    report = api.post("/api/demo/planning-scenario", {"effort_minutes": 360}).json()
    finished = finish(api, report, 510)
    again = api.post("/api/demo/planning-scenario", {"effort_minutes": 360}).json()
    assert again["id"] == finished["id"] and again["status"] == "confirmed"
    assert (again["estimated_minutes"], again["first_estimate_minutes"], again["actual_minutes"], again["completed_minutes"]) == (360, 360, None, 0)
    api.post("/api/demo/calibration-history", {})
    assert any(s["task_id"] == again["id"] for s in cal(api)["suggestions"])
    progressed = api.post(f"/api/tasks/{again['id']}/progress", {"expected_revision": again["revision"],
                         "client_event_id": "ongoing_demo", "minutes": 30,
                         "occurred_at": datetime.now(timezone.utc).isoformat()}).json()
    adjusted = api.post("/api/demo/planning-scenario", {"effort_minutes": 180}).json()
    assert progressed["status"] == adjusted["status"] == "in_progress" and adjusted["completed_minutes"] == 30
