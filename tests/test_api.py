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
    assert draft["engine_ready"] is False and len(draft["request"]["tasks"]) == 2
    client.patch(f"/api/tasks/{task['task_id']}", json={"remaining_minutes": 150})
    assert error(client.post(f"/api/plans/{draft['plan_id']}/adopt", json={"based_on": draft["based_on"]})) == "STALE_DRAFT"
    fresh = data(client.post("/api/plans/draft", json={}))
    adopted = data(client.post(f"/api/plans/{fresh['plan_id']}/adopt", json={"based_on": fresh["based_on"]}))
    assert adopted["status"] == "adopted"
    assert data(client.get("/api/plans/current"))["plan_id"] == fresh["plan_id"]

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
