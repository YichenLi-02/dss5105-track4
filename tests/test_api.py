from studyspace.synthetic import build


def data(r):
    body = r.json()
    assert body["ok"], body
    return body["data"]


def error(r):
    body = r.json()
    assert body["ok"] is False
    return body["error"]["code"]


def candidate(client, title):
    return next(c for c in data(client.get("/api/candidates")) if c["title"] == title)


def test_health(client):
    d = data(client.get("/api/health"))
    assert d["llm_provider"] == "offline" and d["llm_online"] is False


def test_demo_flow_gate1_gate2_progress(client):
    loaded = data(client.post("/api/demo/load"))
    assert loaded["import"]["added"] == 25 and loaded["candidates"] >= 12
    assert data(client.get("/api/workspace"))["now"] == "2026-10-12T08:00:00+08:00"

    # gate 1: a candidate with an ambiguous time cannot be confirmed without a checked time
    report = candidate(client, "Portfolio Case Report")
    assert error(client.post(f"/api/candidates/{report['candidate_id']}/confirm", json={"remaining_minutes": 240})) == "NEEDS_DUE_AT"
    ok = data(client.post(f"/api/candidates/{report['candidate_id']}/confirm",
                          json={"remaining_minutes": 240, "due_at": "2026-10-23T23:59:00+08:00", "priority": "high"}))
    assert ok["task"]["due_at"] == "2026-10-23T23:59:00+08:00"
    assert error(client.post(f"/api/candidates/{report['candidate_id']}/confirm", json={"remaining_minutes": 240})) == "ALREADY_HANDLED"

    # an estimate is required for deliverables
    essay = candidate(client, "Reflective essay")
    assert error(client.post(f"/api/candidates/{essay['candidate_id']}/confirm", json={})) == "NEEDS_ESTIMATE"
    task = data(client.post(f"/api/candidates/{essay['candidate_id']}/confirm", json={"remaining_minutes": 180}))["task"]

    # gate 2: draft, then adopt; a change in between makes the draft stale
    draft = data(client.post("/api/plans/draft", json={}))
    assert draft["checked"] and len(draft["request"]["tasks"]) == 2
    assert draft["result"]["status"] == "complete" and draft["result"]["blocks"]
    client.patch(f"/api/tasks/{task['task_id']}", json={"remaining_minutes": 150})
    assert error(client.post(f"/api/plans/{draft['plan_id']}/adopt", json={"based_on": draft["based_on"]})) == "STALE_DRAFT"
    fresh = data(client.post("/api/plans/draft", json={}))
    adopted = data(client.post(f"/api/plans/{fresh['plan_id']}/adopt", json={"based_on": fresh["based_on"]}))
    assert adopted["status"] == "adopted"
    current = data(client.get("/api/plans/current"))
    assert current["plan_id"] == fresh["plan_id"] and current["replan_reasons"] == []

    # progress: the same op_id twice counts once
    body = {"op_id": "op-1", "task_id": task["task_id"], "start": "2026-10-12T13:00:00+08:00", "end": "2026-10-12T14:00:00+08:00"}
    first = data(client.post("/api/progress", json=body))
    second = data(client.post("/api/progress", json=body))
    assert first["recorded"] and not second["recorded"]
    assert second["task"]["remaining_minutes"] == 90


def test_dismiss(client):
    client.post("/api/demo/load")
    c = candidate(client, "Weekly reflection")
    assert data(client.post(f"/api/candidates/{c['candidate_id']}/dismiss"))["status"] == "dismissed"
    assert all(x["candidate_id"] != c["candidate_id"] for x in data(client.get("/api/candidates?status=pending")))


def test_workspaces_do_not_mix(client):
    client.post("/api/demo/load", headers={"X-Workspace": "visitor-1"})
    assert data(client.get("/api/sources", headers={"X-Workspace": "visitor-2"})) == []
    assert error(client.get("/api/sources", headers={"X-Workspace": "bad id!"})) == "INVALID_WORKSPACE"


def test_upload_files(client):
    ds = build()
    files = [("files", (name, raw, "message/rfc822")) for name, raw in ds.emails[:3]]
    files.append(("files", ("timetable.ics", ds.timetable_ics.encode(), "text/calendar")))
    files.append(("files", ("emails.csv", ds.emails_csv.encode(), "text/csv")))
    report = data(client.post("/api/import", files=files))["files"]
    assert [f["added"] for f in report[:3]] == [1, 1, 1]
    assert report[3]["slots"] == 65
    assert report[4]["duplicate"] == 3 and report[4]["added"] == 22  # same three emails, now as CSV rows


def test_paste_text_then_extract(client):
    d = data(client.post("/api/import/text", json={"text": "MLX5204 groupmate: please finish the slides by 20 Oct, 6pm", "received_at": "2026-10-12T09:00:00+08:00"}))
    assert d["added"] == 1
    cands = data(client.post("/api/extract"))["candidates"]
    assert cands and cands[0]["due_at"] == "2026-10-20T18:00:00+08:00"


def test_calendar_template(client):
    slots = data(client.put("/api/calendar", json={"template": {"from": "2026-10-12", "to": "2026-10-18",
                                                                   "weekly": [{"weekday": "monday", "start": "13:00", "end": "18:00"}]}}))
    assert len(slots) == 1 and slots[0]["origin"] == "manual"


def test_privacy_preview(client):
    client.post("/api/demo/load")
    d = data(client.post("/api/privacy/preview", json={"record_id": "SYN-019"}))
    assert "9876" not in d["would_send"] and "Priya" not in d["would_send"] and d["sent"] is False


def test_validation_errors_use_the_envelope(client):
    r = client.post("/api/progress", json={"op_id": "x"})
    assert r.status_code == 422 and error(r) == "INVALID_INPUT"


def confirm_all(client, minutes=120):
    """Confirm every pending candidate the way a student would: pick a time where one is needed."""
    for c in data(client.get("/api/candidates?status=pending")):
        body = {"remaining_minutes": minutes}
        if c["due_at"] is None:
            if c["due_options"]:
                body["due_at"] = c["due_options"][0]
            elif c["due_date"]:
                body["due_at"] = f"{c['due_date']}T23:59:00+08:00"
            else:
                client.post(f"/api/candidates/{c['candidate_id']}/dismiss")
                continue
        client.post(f"/api/candidates/{c['candidate_id']}/confirm", json=body)


def test_full_demo_week_plans_without_breaking_rules(client):
    client.post("/api/demo/load")
    confirm_all(client)
    draft = data(client.post("/api/plans/draft", json={}))
    assert draft["checked"] and draft["result"]["blocks"]
    assert draft["result"]["status"] in ("complete", "partial")
    assert any(w["code"] == "PAST_DEADLINE" for w in draft["result"]["warnings"])  # the peer review was due in September


def test_in05_draft_does_not_replace_the_saved_plan(client):
    client.post("/api/demo/load")
    confirm_all(client)
    first = data(client.post("/api/plans/draft", json={}))
    data(client.post(f"/api/plans/{first['plan_id']}/adopt", json={"based_on": first["based_on"]}))
    second = data(client.post("/api/plans/draft", json={}))
    assert second["changes"]["had_saved_plan"]
    assert data(client.get("/api/plans/current"))["plan_id"] == first["plan_id"]


def test_in06_lock_and_progress_then_replan(client):
    client.post("/api/demo/load")
    confirm_all(client)
    first = data(client.post("/api/plans/draft", json={}))
    plan = data(client.post(f"/api/plans/{first['plan_id']}/adopt", json={"based_on": first["based_on"]}))
    block_a, block_b = [b for b in plan["blocks"] if not b["locked"]][:2]
    locked = data(client.post("/api/plans/lock", json={**{k: block_b[k] for k in ("task_id", "start", "end")}, "locked": True}))
    assert any(b["locked"] for b in locked["blocks"]) and locked["replan_reasons"] == []
    op = {"op_id": "done-1", "task_id": block_a["task_id"], "start": block_a["start"], "end": block_a["end"]}
    left = data(client.post("/api/progress", json=op))["task"]["remaining_minutes"]
    assert data(client.post("/api/progress", json=op))["task"]["remaining_minutes"] == left  # no double counting
    again = data(client.post("/api/plans/draft", json={}))
    retained = again["result"]["retained_locked_blocks"]
    assert {(b["task_id"], b["start"]) for b in retained} >= {(block_b["task_id"], block_b["start"])}


def test_in07_failed_save_keeps_the_old_plan(client, monkeypatch):
    from studyspace.storage import repo

    client.post("/api/demo/load")
    confirm_all(client)
    first = data(client.post("/api/plans/draft", json={}))
    data(client.post(f"/api/plans/{first['plan_id']}/adopt", json={"based_on": first["based_on"]}))
    second = data(client.post("/api/plans/draft", json={}))
    real = repo.adopt_plan

    def broken(conn, ws, plan_id):
        real(conn, ws, plan_id)
        raise RuntimeError("disk full")

    monkeypatch.setattr(repo, "adopt_plan", broken)
    import pytest

    with pytest.raises(RuntimeError):
        client.post(f"/api/plans/{second['plan_id']}/adopt", json={"based_on": second["based_on"]})
    monkeypatch.setattr(repo, "adopt_plan", real)
    assert data(client.get("/api/plans/current"))["plan_id"] == first["plan_id"]  # rolled back


def test_in08_retry_does_not_duplicate(client):
    client.post("/api/demo/load")
    before = len(data(client.get("/api/candidates")))
    data(client.post("/api/extract"))
    data(client.post("/api/extract"))
    assert len(data(client.get("/api/candidates"))) == before
    ds = build()
    files = [("files", (ds.emails[0][0], ds.emails[0][1], "message/rfc822"))]
    assert data(client.post("/api/import", files=files))["files"][0]["duplicate"] == 1


def test_in09_everything_survives_a_restart(settings):
    from fastapi.testclient import TestClient

    from studyspace.api import create_app

    c1 = TestClient(create_app(settings))
    c1.post("/api/demo/load")
    confirm_all(c1)
    draft = data(c1.post("/api/plans/draft", json={}))
    data(c1.post(f"/api/plans/{draft['plan_id']}/adopt", json={"based_on": draft["based_on"]}))
    c2 = TestClient(create_app(settings))  # a new process on the same database
    ws = data(c2.get("/api/workspace"))
    assert ws["sources"] == 25 and ws["adopted_plan"] == draft["plan_id"] and ws["demo_clock"]
    assert data(c2.get("/api/tasks"))


def test_meeting_flow_and_ics_export(client):
    client.post("/api/demo/load")
    confirm_all(client)
    draft = data(client.post("/api/plans/draft", json={}))
    data(client.post(f"/api/plans/{draft['plan_id']}/adopt", json={"based_on": draft["based_on"]}))
    slots = data(client.post("/api/meetings/suggest", json={"duration_minutes": 60}))["slots"]
    assert slots
    first_block = data(client.get("/api/plans/current"))["blocks"][0]
    data(client.post("/api/calendar/busy", json={"start": first_block["start"], "end": first_block["end"], "label": "Team sync"}))
    current = data(client.get("/api/plans/current"))
    assert any("clashes" in r for r in current["replan_reasons"])
    ics = client.get("/api/plans/current/ics")
    assert ics.status_code == 200 and "BEGIN:VEVENT" in ics.text and "Study: " in ics.text


def test_reply_draft_gate3(client):
    client.post("/api/demo/load")
    d = data(client.get("/api/drafts/SYN-018"))
    assert d["status"] == "draft" and d["sent"] is False and d["warnings"]
    edited = data(client.put("/api/drafts/SYN-018", json={"body": "Hi Mei Ling, Tuesday 2pm works. Jordan"}))
    assert edited["status"] == "draft"
    reviewed = data(client.post("/api/drafts/SYN-018/reviewed"))
    assert reviewed["status"] == "reviewed" and reviewed["body"].startswith("Hi Mei Ling, Tuesday")
    inbox = data(client.get("/api/inbox"))
    assert next(i for i in inbox if i["record_id"] == "SYN-018")["draft_status"] == "reviewed"


def test_midnight_candidate_needs_a_choice(client):
    client.post("/api/demo/load")
    report = candidate(client, "Portfolio Case Report")
    err = client.post(f"/api/candidates/{report['candidate_id']}/confirm", json={"remaining_minutes": 60}).json()["error"]
    assert err["code"] == "NEEDS_DUE_AT" and len(err["details"]["options"]) == 2


def test_settings_and_manual_task(client):
    s = data(client.put("/api/settings", json={"name": "Alex", "plan": {"max_study_minutes_per_day": 120}}))
    assert s["plan"]["max_study_minutes_per_day"] == 120
    t = data(client.post("/api/tasks", json={"title": "Read paper", "due_at": "2026-10-20T18:00:00+08:00", "remaining_minutes": 45}))
    assert t["confirmed"] and t["task_id"].startswith("T-M")


def test_web_front_end_is_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "studyspace" in r.text.lower()
