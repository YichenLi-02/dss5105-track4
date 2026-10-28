from app.services.importance import evaluate


def test_coursework_and_career_needing_work_are_important():
    assert evaluate({"category": "academic", "needs_reply": False, "needs_action": True})[:2] == (True, "academic_action")
    assert evaluate({"category": "career", "needs_reply": True, "needs_action": False})[:2] == (True, "career_reply")


def test_ignorable_promotions_and_notices_are_not_important():
    assert evaluate({"category": "career", "needs_reply": False, "needs_action": False})[0] is False  # job-board promo
    assert evaluate({"category": "promotions", "needs_reply": False, "needs_action": True})[0] is False
    assert evaluate({"category": "other", "needs_reply": False, "needs_action": False,
                     "attention_flags": ["security"]})[0] is False


def test_large_payment_by_threshold():
    big = {"category": "other", "needs_reply": False, "needs_action": False, "amount": 1200, "currency": "SGD"}
    ok, reason, params = evaluate(big, 200)
    assert ok and reason == "large_payment" and params["amount"] == "1,200"
    assert evaluate(dict(big, amount=50), 200)[0] is False
    assert evaluate(dict(big, amount=50), 40)[0] is True


def test_user_choice_wins():
    assert evaluate({"category": "academic", "needs_action": True, "important_override": False})[:2] == (False, "user_choice")
    assert evaluate({"category": "promotions", "important_override": True})[:2] == (True, "user_choice")


def test_account_security_needing_action_is_important():
    assert evaluate({"category": "other", "needs_action": True, "account_security": True})[:2] == (True, "account_action")
    assert evaluate({"category": "other", "needs_action": False, "account_security": True})[0] is False
    # older analyses without the flag fall back to keywords in the subject
    assert evaluate({"category": "other", "needs_action": True}, subject="Your account has been suspended")[0] is True
    assert evaluate({"category": "promotions", "needs_action": True}, subject="Log in to claim 20% off")[0] is False


def test_demo_data_hidden_when_switched_off(api, imported):
    def samples():
        return [m for m in api.get("/api/messages?limit=500").json()["items"] if m["source_id"][:1] == "M"]
    assert samples()
    prefs = api.get("/api/preferences").json()
    api.patch("/api/preferences", {"expected_revision": prefs["revision"], "show_demo_data": False})
    body = api.get("/api/messages?limit=500").json()
    assert samples() == [] and body["counts"]["all"] == body["total"] and all(not m["is_demo"] for m in body["items"])
    assert all(not t["entity_key"].startswith(("cs4310_", "synthetic_")) for t in api.get("/api/tasks").json()["items"])
    prefs = api.get("/api/preferences").json()
    api.patch("/api/preferences", {"expected_revision": prefs["revision"], "show_demo_data_auto": True})
    assert samples()


def test_remove_from_app_only_and_stays_removed(api, imported):
    items = api.get("/api/messages?limit=500").json()["items"]
    m01 = next(m for m in items if m["source_id"] == "M01")
    before_tasks = api.get("/api/tasks").json()["items"]
    linked = [t for t in before_tasks if any(e["message_id"] == m01["id"] for e in t["evidence"])]
    assert linked
    r = api.post("/api/messages/remove", {"message_ids": [m01["id"]]}).json()
    assert r["removed"] == 1 and r["source_mailbox_changed"] is False
    after = api.get("/api/messages?limit=500").json()
    assert all(m["id"] != m01["id"] for m in after["items"])
    for t in api.get("/api/tasks").json()["items"]:
        assert all(e["message_id"] != m01["id"] for e in t["evidence"])
    # Re-importing samples does not bring it back.
    job = api.post("/api/imports", {"source": "selected_50", "upload_id": None}).json()
    api.get(f"/api/jobs/{job['id']}")
    assert all(m["id"] != m01["id"] for m in api.get("/api/messages?limit=500").json()["items"])
    assert api.post("/api/messages/remove", {"message_ids": []}).status_code == 422
