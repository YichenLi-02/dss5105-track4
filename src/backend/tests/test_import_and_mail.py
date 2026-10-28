"""T01, T02, T04-T07 and basic session/CSRF behaviour."""
from conftest import needs_samples


def test_health_reports_demo_without_keys(client):
    body = client.get("/api/health").json()
    assert body["mode"] == "demo"
    assert body["capabilities"]["model_configured"] is False
    assert body["capabilities"]["canvas_lms"] is False


def test_reads_need_session_and_writes_need_csrf(client, api):
    fresh = client.__class__(client.app)
    assert fresh.get("/api/messages").status_code == 401
    r = client.post("/api/imports", json={"source": "selected_50", "upload_id": None})
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_REJECTED"
    r = api.post("/api/imports", json={"source": "selected_50", "upload_id": None},
                 headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "ORIGIN_REJECTED"


@needs_samples
def test_t01_double_import_is_stable(api, imported):
    def samples():
        return [m for m in api.get("/api/messages?limit=500").json()["items"] if m["source_id"][:1] == "M"]
    first = samples()
    tasks_first = api.get("/api/tasks").json()["total"]
    r = api.post("/api/imports", json={"source": "selected_50", "upload_id": None})
    job = api.get(f"/api/jobs/{r.json()['id']}").json()
    assert job["result"]["messages_created"] == 0 and job["result"]["tasks_created"] == 0
    assert len(first) == len(samples()) == 40
    assert api.get("/api/messages?direction=outbound").json()["total"] == 10
    assert api.get("/api/tasks").json()["total"] == tasks_first


@needs_samples
def test_counts_and_filters_agree(api, imported):
    body = api.get("/api/messages").json()
    c = body["counts"]
    assert sum(c[k] for k in ("academic", "career", "events", "promotions", "other", "uncategorized")) == c["all"]
    assert c["needs_reply"] >= 5 and c["needs_action"] >= 19
    acad = api.get("/api/messages?category=academic").json()
    assert acad["total"] == c["academic"]
    both = api.get("/api/messages?needs_reply=true&needs_action=true").json()["items"]
    assert all(m["needs_reply"] and m["needs_action"] for m in both)
    assert api.get("/api/messages?q=M16").json()["total"] == 1


@needs_samples
def test_t02_reply_and_action_both_true(api, imported):
    m16 = api.get("/api/messages/M16").json()
    assert m16["needs_reply"] is True and m16["needs_action"] is True and m16["ignore"] is False
    assert m16["analysis_origin"] == "reference_annotation"


@needs_samples
def test_ignore_does_not_delete(api, imported):
    m23 = api.get("/api/messages/M23").json()
    assert m23["ignore"] is True and m23["body_view"]


def _task(api, key):
    return next(t for t in api.get("/api/tasks").json()["items"] if t["entity_key"] == key)


@needs_samples
def test_t03_conflict_keeps_all_sources(api, imported):
    t = _task(api, "cs4310_final_results")
    assert t["deadline_status"] == "conflict" and t["official_date"] is None
    assert {e["source_id"] for e in t["evidence"]} >= {"M01", "M03", "M04", "M05"}
    assert "resolve_date_conflict" in t["missing_fields"]


@needs_samples
def test_t04_2350_not_rounded(api, imported):
    t = _task(api, "cs4370_all_submissions")
    assert t["official_time"] == "23:50"


@needs_samples
def test_unknown_time_stays_null(api, imported):
    t = _task(api, "cs4310_quiz13")
    assert t["official_date"] == "2025-12-05" and t["official_time"] is None


@needs_samples
def test_t05_receipt_completes_report_not_results(api, imported):
    report = _task(api, "cs4310_final_report")
    results = _task(api, "cs4310_final_results")
    assert report["status"] == "completed"
    assert results["status"] != "completed"
    assert sum(1 for e in report["evidence"] if e["relation"] == "completion_receipt") == 2


@needs_samples
def test_t06_exam_window_single_task(api, imported):
    t = _task(api, "cs3120_final")
    assert len(t["evidence"]) == 2 and t["deliverable"] == "exam"
    assert {c["required_duration_minutes"] for c in t["date_candidates"]} == {75}


@needs_samples
def test_t07_non_task_times_never_become_required(api, imported):
    for key in ("onedrive_code", "retail_offer", "transcript_order"):
        t = _task(api, key)
        assert t["status"] == "ignored" and t["required"] is False


@needs_samples
def test_quotes_verified_against_body(api, imported):
    for t in api.get("/api/tasks").json()["items"]:
        for e in t["evidence"]:
            if e["start_char"] is not None and e["source_type"] == "email":
                body = api.get(f"/api/messages/{e['message_id']}").json()["body_view"]
                assert body[e["start_char"]:e["end_char"]] == e["quote"]


@needs_samples
def test_confirm_requires_complete_fields_and_revision(api, imported):
    t = _task(api, "cs3120_quiz4")
    r = api.patch(f"/api/tasks/{t['id']}", {"expected_revision": t["revision"], "status": "confirmed"})
    assert r.status_code == 422
    r = api.patch(f"/api/tasks/{t['id']}", {"expected_revision": t["revision"], "source_timezone": "America/Phoenix",
                                           "estimated_minutes": 60})
    assert r.status_code == 200, r.text
    t2 = r.json()
    assert t2["official_time"] == "23:59" and t2["planning_cutoff_utc"].startswith("2025-12-04T06:59")
    stale = api.patch(f"/api/tasks/{t['id']}", {"expected_revision": t["revision"], "status": "confirmed"})
    assert stale.status_code == 409
    ok = api.patch(f"/api/tasks/{t['id']}", {"expected_revision": t2["revision"], "status": "confirmed"})
    assert ok.status_code == 200 and ok.json()["status"] == "confirmed"
