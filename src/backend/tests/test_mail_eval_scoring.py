"""The mail-evaluation scorer on hand-made predictions: no app, no model, no network."""
import json
from pathlib import Path

from evaluation import mail_eval as M

DATASET = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "mail_eval_v1"


def _task(date, time=None, quote=None, body="", state="pending", tz=None, title="t"):
    start = body.find(quote) if quote else -1
    return {"title": title, "title_en": None, "state": state, "status": "completed" if state == "done" else "needs_review",
            "date": date, "time": time, "timezone": tz, "field": "body_view", "quote": quote,
            "start": start if start >= 0 else None, "end": start + len(quote) if start >= 0 else None, "model_status": "pending"}


def _pred(sid, body, tasks, reply=False, action=False, category="academic", sent="2026-10-01T09:00:00+08:00"):
    return {"source_id": sid, "sent_at": sent, "subject": "s", "body_view": body, "sender_label": "x",
            "labels": {"needs_reply": reply, "needs_action": action, "category": category}, "tasks": tasks}


def _due(did, date, time=None, anchor="", current=True, also_dates=(), tz=None):
    return {"role": "deadline", "deadline_id": did, "date": date, "time": time, "timezone": tz,
            "accept_dates": [date, *also_dates], "accept_times": [time], "current": current, "anchors": [anchor]}


def _msg(items, reply=False, action=True, category="academic"):
    return {"category": category, "needs_reply": reply, "needs_action": action, "difficulty": "easy", "language": "en",
            "tags": [], "items": items, "secrets": []}


def test_outcomes_are_told_apart():
    b1 = "Report due 30 Oct at 23:59. Office hours Thursday 3pm."
    b2 = "Reminder: report due this Friday."
    b3 = "New deadline 2 Nov."
    b4 = "Receipt. Due date: 2 Nov 23:59. Paid on 1 Nov."
    b5 = "Apply by 20 Nov if interested. Sale ends 18 Oct."
    b6 = "Essay due Friday."
    key = {"messages": {
        "m1": _msg([_due("D1", "2026-10-30", "23:59", "due 30 Oct at 23:59", current=False),
                    {"role": "non_task", "kind": "event_time", "date": "2026-10-29", "time": "15:00", "anchors": ["Thursday 3pm"]}]),
        "m2": _msg([_due("D1", "2026-10-30", None, "due this Friday", current=False)]),
        "m3": _msg([_due("D1", "2026-11-02", None, "New deadline 2 Nov")]),
        "m4": _msg([{"role": "completed", "deadline_id": "D1", "date": "2026-11-02", "time": "23:59", "anchors": ["Due date: 2 Nov 23:59"]},
                    {"role": "non_task", "kind": "receipt_timestamp", "date": "2026-11-01", "time": None, "anchors": ["Paid on 1 Nov"]}],
                   action=False),
        "m5": _msg([{"role": "optional", "date": "2026-11-20", "time": None, "anchors": ["Apply by 20 Nov"]},
                    {"role": "non_task", "kind": "promotion_expiry", "date": "2026-10-18", "time": None, "anchors": ["Sale ends 18 Oct"]}],
                   action=False, category="promotions"),
        "m6": _msg([_due("D2", "2026-10-09", None, "due Friday")]),
        "m7": _msg([_due("D3", "2026-10-12", "17:00", "nothing here")]),
    }}
    preds = {
        "m1": _pred("m1", b1, [_task("2026-10-30", "23:59", "due 30 Oct at 23:59", b1),           # stale: later replaced
                               _task("2026-10-29", "15:00", "Thursday 3pm", b1)], action=True),    # office hours became a task
        "m2": _pred("m2", b2, [_task("2026-10-30", "23:59", "due this Friday", b2)], action=True,  # stale + time invented
                    sent="2026-10-28T09:00:00+08:00"),
        "m3": _pred("m3", b3, [_task("2026-11-02", None, "New deadline 2 Nov", b3),                 # correct
                               _task("2026-11-02", None, "New deadline 2 Nov", b3)], action=True,   # same thing twice in one mail
                    sent="2026-10-29T09:00:00+08:00"),
        "m4": _pred("m4", b4, [_task("2026-11-02", "23:59", "Due date: 2 Nov 23:59", b4, state="done"),  # fine: closed
                               _task("2026-11-01", None, "Paid on 1 Nov", b4)]),                         # payment stamp became a task
        "m5": _pred("m5", b5, [_task("2026-11-20", None, "Apply by 20 Nov", b5),                         # optional promoted
                               _task(None, None, "Sale ends", b5)], category="promotions"),              # pairs by words: promo promoted
        "m6": _pred("m6", b6, [_task("2026-10-10", None, "due Friday", b6),                              # wrong date
                               _task("2026-12-25", None, None, b6)], action=True),                       # invented
        # m7: nothing produced -> missed
    }
    d = M.score_deadlines(key, preds)
    assert d["open_task_outcomes"] == {"stale": 2, "non_task_promoted": 3, "correct": 1, "duplicate_in_mail": 1,
                                       "optional_promoted": 1, "wrong_date": 1, "invented": 1}
    assert d["closed_task_outcomes"] == {"not_open": 1}
    assert d["recall_per_mail"]["k"] == 3 and d["recall_per_mail"]["n"] == 5     # m1, m2, m3 hit; m6 wrong date; m7 missed
    assert d["recall_unique"]["k"] == 1 and d["recall_unique"]["n"] == 3         # only D1 found with its final date
    assert d["missed_breakdown"] == {"wrong_date": 1, "missed": 1}
    dated = d["system_output"]["open_with_date"]
    assert dated == 9 and d["precision_per_mail"]["k"] == 3 and d["precision_task_list"]["k"] == 1
    assert d["non_task"]["became_open_task"] == 3 and d["optional"]["became_open_task"] == 1
    assert d["completed"]["became_open_task"] == 0
    assert d["time_of_day"] == {"time_as_expected": 2, "time_invented": 1, "time_invented_2359": 1}
    kinds = sorted((f["kind"], f["detail"]) for f in d["failures"])
    assert ("missed_deadline", "missed") in kinds and ("false_task", "invented") in kinds and len(d["failures"]) == 11


def test_same_deadline_from_two_mails_is_a_duplicate_in_the_task_list():
    b = "Lab due 9 Nov."
    key = {"messages": {"a": _msg([_due("D9", "2026-11-09", None, "due 9 Nov")]), "b": _msg([_due("D9", "2026-11-09", None, "due 9 Nov")])}}
    preds = {"a": _pred("a", b, [_task("2026-11-09", None, "due 9 Nov", b)], action=True, sent="2026-11-01T09:00:00+08:00"),
             "b": _pred("b", b, [_task("2026-11-09", None, "due 9 Nov", b)], action=True, sent="2026-11-03T09:00:00+08:00")}
    d = M.score_deadlines(key, preds)
    assert d["open_task_outcomes"] == {"correct": 1, "duplicate_across_mails": 1}
    assert d["recall_per_mail"]["value"] == 1.0 and d["recall_unique"]["value"] == 1.0
    assert d["precision_per_mail"]["value"] == 1.0 and d["precision_task_list"]["value"] == 0.5
    dup = next(f for f in d["failures"] if f["detail"] == "duplicate_across_mails")
    assert dup["mail"] == "b" and dup["first_seen_in"] == "a"


def test_unknown_date_is_right_only_when_left_unknown():
    b = "Report due Thursday, 23 October at 6 pm."
    key = {"messages": {"x": _msg([{**_due("D4", None, "18:00", "due Thursday, 23 October at 6 pm"), "accept_times": ["18:00", None]}])}}
    left_open = M.score_deadlines(key, {"x": _pred("x", b, [_task(None, "18:00", "due Thursday, 23 October at 6 pm", b)], action=True)})
    guessed = M.score_deadlines(key, {"x": _pred("x", b, [_task("2026-10-23", "18:00", "due Thursday, 23 October at 6 pm", b)], action=True)})
    assert left_open["recall_per_mail"]["value"] == 1.0 and left_open["open_task_outcomes"] == {"correct": 1}
    assert guessed["recall_per_mail"]["value"] == 0.0 and guessed["open_task_outcomes"] == {"wrong_date": 1}


def test_triage_counts_and_missing_output():
    key = {"messages": {"a": _msg([], reply=True, action=False), "b": _msg([], reply=True, action=True),
                        "c": _msg([], reply=False, action=False, category="promotions"), "d": _msg([], reply=False, action=True),
                        "e": _msg([], reply=False, action=True)}}
    preds = {"a": _pred("a", "", [], reply=True, action=False), "b": _pred("b", "", [], reply=False, action=True),
             "c": _pred("c", "", [], reply=False, action=True, category="other"), "d": _pred("d", "", [], reply=False, action=True),
             "e": {"source_id": "e", "labels": None, "tasks": [], "error": "MODEL_EVIDENCE_INVALID"}}
    t = M.score_triage(key, preds)
    assert t["labels"]["needs_reply"] | {} and (t["labels"]["needs_reply"]["TP"], t["labels"]["needs_reply"]["FN"]) == (1, 1)
    a = t["labels"]["needs_action"]
    assert (a["TP"], a["FP"], a["FN"], a["TN"]) == (2, 1, 1, 1)            # e has no output -> counted as not flagged
    assert t["exact_match"]["k"] == 2 and t["exact_match"]["n"] == 5 and t["no_output"] == ["e"]
    assert t["confusion"]["action"] == {"action": 1, "no output": 1} and t["confusion"]["ignore"] == {"action": 1}
    assert t["category_accuracy"]["k"] == 3 and t["category_accuracy"]["n"] == 5
    assert {w["mail"] for w in t["wrong"]} == {"b", "c", "e"}


def test_privacy_and_wilson():
    key = {"messages": {"a": {**_msg([]), "secrets": ["x@y.example", "https://z.example/a", "482913"]}}}
    p = M.score_privacy(key, {"a": _pred("a", "code 482913 and [EMAIL_1] and [LINK_2]", [])})
    assert p["planted"] == 3 and p["removed"]["k"] == 2 and p["still_present"] == [{"mail": "a", "kind": "number or code"}]
    lo, hi = M.wilson(8, 10)
    assert 0.44 < lo < 0.50 and 0.94 < hi < 0.98 and M.wilson(0, 0) is None


def _oracle(messages, key, include_superseded=True):
    out = {}
    for m in messages:
        gt, tasks = key["messages"][m["id"]], []
        for it in gt["items"]:
            if it["role"] == "deadline" and (include_superseded or it["current"]):
                tasks.append(_task(it["date"], it["time"], it["anchors"][0], m["body"], tz=it.get("timezone")))
        out[m["id"]] = _pred(m["id"], m["body"], tasks, gt["needs_reply"], gt["needs_action"], gt["category"], sent=m["sent_at"])
        out[m["id"]]["subject"] = m["subject"]
    return out


def test_perfect_answers_on_the_real_dataset_score_perfectly():
    messages, key = M.load_synthetic(DATASET)
    assert json.loads((DATASET / "MANIFEST.json").read_text())["messages"] == len(messages) == 80
    rep = M.build_report(key, _oracle(messages, key))
    t, d = rep["triage"], rep["deadlines"]
    assert t["exact_match"]["value"] == 1.0 and t["category_accuracy"]["value"] == 1.0 and t["wrong"] == []
    assert d["recall_per_mail"]["value"] == 1.0 and d["recall_unique"]["value"] == 1.0
    assert d["precision_per_mail"]["value"] == 1.0
    assert d["open_task_outcomes"].get("stale") == 2                      # the two mentions replaced by the extension
    assert d["non_task"]["became_open_task"] == 0 and d["optional"]["became_open_task"] == 0
    assert set(d["time_of_day"]) == {"time_as_expected"} and "stated_but_wrong" not in d["timezone"]
    only_final = M.score_deadlines(key, _oracle(messages, key, include_superseded=False))
    assert only_final["precision_task_list"]["value"] == 1.0 and only_final["recall_unique"]["value"] == 1.0
    assert M.markdown("oracle", rep).startswith("# Mail evaluation - oracle")


def test_no_output_scores_zero_without_crashing():
    messages, key = M.load_synthetic(DATASET)
    empty = {m["id"]: {"source_id": m["id"], "sent_at": m["sent_at"], "subject": m["subject"], "body_view": m["body"],
                       "labels": None, "tasks": [], "error": "MODEL_UNREACHABLE"} for m in messages}
    rep = M.build_report(key, empty)
    assert rep["deadlines"]["recall_per_mail"]["k"] == 0 and rep["deadlines"]["system_output"]["tasks"] == 0
    assert len(rep["triage"]["no_output"]) == 80 and rep["triage"]["labels"]["needs_reply"]["TP"] == 0
    assert rep["triage"]["exact_match"]["k"] == 0                        # even true "ignore" mails are not counted as right
    assert rep["baseline"]["recall_per_mail"]["n"] == 41                  # the baseline runs on the same text


def test_task_evidence_from_the_subject_still_pairs_through_the_other_quotes():
    """The task row keeps only the model's first quote (here the subject); the candidate's other quotes locate it."""
    body = "As discussed, the final report is due the Friday after reading week, 5 pm. One submission per team."
    item = {**_due("D5", None, "17:00", "due the Friday after reading week, 5 pm"), "accept_times": ["17:00", None]}
    key = {"messages": {"x": _msg([item, {"role": "non_task", "kind": "event_time", "date": "2026-11-05", "time": None,
                                          "anchors": ["One submission per team"]}])}}
    task = {**_task(None, None, None, body), "field": "subject", "quote": "s", "start": 0, "end": 1, "candidate_index": 0}
    pred = _pred("x", body, [task], action=True)
    pred["candidates"] = [{"evidence": [{"field": "subject", "quote": "s"},
                                        {"field": "body", "quote": "the final report is due the Friday after reading week, 5 pm."}]}]
    d = M.score_deadlines(key, {"x": pred})
    assert d["recall_per_mail"]["value"] == 1.0 and d["open_task_outcomes"] == {"correct": 1}
    assert d["non_task"]["became_open_task"] == 0


def test_the_only_open_task_and_the_only_deadline_of_a_mail_are_paired():
    body = "Please complete the reviews within 5 days of this email."
    item = _due("D7", "2026-11-09", None, "within 5 days of this email", also_dates=(None,))
    key = {"messages": {"x": _msg([item]), "y": _msg([item | {"deadline_id": "D8"}]), "z": _msg([item | {"deadline_id": "D9"}])}}
    no_quote = {**_task(None), "candidate_index": None}
    wrong = {**_task("2026-11-30"), "candidate_index": None}
    d = M.score_deadlines(key, {"x": _pred("x", body, [no_quote], action=True),                 # left unknown: accepted
                                "y": _pred("y", body, [wrong], action=True),                    # one task, wrong date
                                "z": _pred("z", body, [no_quote, dict(no_quote)], action=True)})  # two tasks: not guessed
    assert d["open_task_outcomes"] == {"correct": 1, "wrong_date": 1, "undated_extra": 2}
    assert d["missed_breakdown"] == {"wrong_date": 1, "missed": 1}
