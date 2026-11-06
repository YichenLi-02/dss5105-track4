"""Calibration on top of the stored data: which suggestions to show, and applying the student's choice.

Reads tasks (first estimate, actual or logged minutes), answered study check-ins and the weekly flexible time.
Changes a task only when the student accepts a suggestion or answers an overrun question, through the normal
task update (revision checked, plans that used the old estimate become stale).
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from ..db import audit, dumps, loads, now_iso
from ..errors import AppError
from . import calibration as C
from . import preferences, ref_i18n
from .task_service import get_task, update_task

DEMO_KEY = "demo_calib_"  # synthetic history for the offline demo
WINDOW_DAYS = 28  # completion rate over the last four weeks


def _demo_shown(conn: sqlite3.Connection) -> bool:
    # Synthetic history counts only while demo data is shown, like the rest of the sample data; with demo data
    # off it never feeds a real student's suggestions.
    return preferences.show_demo_data(conn)


def _real_task_ids(conn: sqlite3.Connection) -> set[str]:
    """Match the task board's real-data view, including manual tasks and local user documents.
    Sample mail and synthetic planning tasks must not train the real student's estimates.
    """
    real_sources = {r[0] for r in conn.execute(
        "SELECT DISTINCT e.task_id FROM task_evidence e JOIN messages m ON m.id=e.message_id "
        "WHERE m.connection_id != 'conn_local_jsonl'")}
    with_evidence = {r[0] for r in conn.execute("SELECT DISTINCT task_id FROM task_evidence")}
    return {r["id"] for r in conn.execute("SELECT id,entity_key FROM tasks")
            if not (r["entity_key"] or "").startswith((DEMO_KEY, "synthetic_")) and
            (r["id"] in real_sources or ((r["entity_key"] or "").startswith("manual_") and r["id"] not in with_evidence))}


def _include(task_id: str, demo: bool, real_ids: set[str]) -> bool:
    return demo or task_id in real_ids


def samples(conn: sqlite3.Connection) -> list[C.Sample]:
    demo = _demo_shown(conn)
    real_ids = set() if demo else _real_task_ids(conn)
    out = []
    for r in conn.execute("SELECT * FROM tasks WHERE status='completed' AND first_estimate_minutes > 0"):
        actual = r["actual_minutes"] if r["actual_minutes"] is not None else r["completed_minutes"]
        if actual and actual > 0 and _include(r["id"], demo, real_ids):
            out.append(C.Sample(r["id"], r["title"], r["title_en"] or ref_i18n.task_title(r["entity_key"]), r["course"], r["deliverable"],
                                r["first_estimate_minutes"], actual, r["actual_minutes"] is not None))
    return out


def _view(s: C.Sample) -> dict:
    return {"task_id": s.task_id, "title": s.title, "title_en": s.title_en, "estimate": s.estimate,
            "actual": s.actual, "confirmed": s.confirmed}


def overview(conn: sqlite3.Connection) -> dict:
    history = samples(conn)
    demo = _demo_shown(conn)
    real_ids = set() if demo else _real_task_ids(conn)
    decided = {r["task_id"] for r in conn.execute("SELECT task_id FROM estimate_decisions")}
    suggestions, overruns = [], []
    for t in conn.execute("SELECT * FROM tasks WHERE status IN ('confirmed','in_progress') ORDER BY planning_cutoff_utc"):
        est, done = t["estimated_minutes"], t["completed_minutes"]
        if not est or not _include(t["id"], demo, real_ids):
            continue
        base = {"task_id": t["id"], "title": t["title"], "title_en": t["title_en"] or ref_i18n.task_title(t["entity_key"]), "revision": t["revision"]}
        if done >= est:
            overruns.append({**base, "estimate": est, "completed": done})
            continue
        if t["id"] in decided or t["first_estimate_minutes"] != est:
            continue  # already decided, or the student has already changed this estimate themselves
        bias = C.bias_for([s for s in history if s.task_id != t["id"]], t["course"], t["deliverable"])
        new = C.suggest_minutes(est, done, bias) if bias else None
        if new:
            suggestions.append({**base, "current": est, "suggested": new, "ratio": bias["ratio"], "group": bias["group"],
                                "group_value": bias["value"], "n": bias["n"],
                                "evidence": [_view(s) for s in bias["samples"]]})
    since = (datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)).isoformat()
    rows = conn.execute("""SELECT c.planned_minutes, c.minutes, c.created_at, c.task_id, t.entity_key FROM study_checkins c
                           LEFT JOIN tasks t ON t.id = c.task_id
                           WHERE c.planned_minutes > 0 AND c.created_at >= ? ORDER BY c.created_at""", (since,)).fetchall()
    rows = [r for r in rows if _include(r["task_id"], demo, real_ids)]
    span = 1.0
    if rows:
        first, last = datetime.fromisoformat(rows[0]["created_at"]), datetime.fromisoformat(rows[-1]["created_at"])
        span = max(1.0, (last - first).total_seconds() / (7 * 86400))
    prefs, _ = preferences.get_raw(conn)
    completion = C.completion([(r["planned_minutes"], r["minutes"]) for r in rows], span,
                              prefs.get("weekly_flex_minutes", 0))
    if rows and completion["flex_suggested"] is not None:
        # Applying slack must not prompt for another increase using the same answers.
        # A later check-in can justify a fresh suggestion; UI-language changes cannot.
        last_answer = max(datetime.fromisoformat(r["created_at"]) for r in rows).replace(microsecond=0)
        for event in conn.execute("SELECT created_at,summary_json FROM audit_events WHERE event_type='preferences_updated' ORDER BY created_at DESC,rowid DESC"):
            if "weekly_flex_minutes" in loads(event["summary_json"], {}).get("fields", []):
                if datetime.fromisoformat(event["created_at"]).replace(microsecond=0) >= last_answer:
                    completion["flex_suggested"] = None
                break
    return {"finished_tasks": len(history), "min_samples": C.MIN_SAMPLES, "suggestions": suggestions,
            "overruns": overruns,
            "completion": completion,
            "window_days": WINDOW_DAYS}


def decide(conn: sqlite3.Connection, body: dict) -> dict:
    """accept = set the estimate to the suggestion (recomputed here, never taken from the client); keep = leave it."""
    s = next((x for x in overview(conn)["suggestions"] if x["task_id"] == body["task_id"]), None)
    if not s:
        raise AppError(409, "NO_SUGGESTION", "There is no current suggestion for this task; reload")
    if body["decision"] == "accept":
        task = update_task(conn, s["task_id"], {"expected_revision": body["expected_revision"],
                                                "estimated_minutes": s["suggested"]})
    else:
        task = get_task(conn, s["task_id"])
        if task["revision"] != body["expected_revision"]:
            raise AppError(409, "REVISION_CONFLICT", "Task changed since it was loaded; reload")
    conn.execute("""INSERT OR REPLACE INTO estimate_decisions(task_id,decision,from_minutes,to_minutes,ratio,basis,created_at)
                    VALUES(?,?,?,?,?,?,?)""",
                 (s["task_id"], "accepted" if body["decision"] == "accept" else "kept", s["current"], s["suggested"],
                  s["ratio"], dumps({"group": s["group"], "n": s["n"]}), now_iso()))
    audit(conn, "estimate_calibration", "task", s["task_id"],
          {"decision": body["decision"], "from": s["current"], "to": s["suggested"], "n": s["n"]})
    return {"task": task, "decision": body["decision"]}


def answer_overrun(conn: sqlite3.Connection, body: dict) -> dict:
    """finished: mark completed with the logged time as actual; otherwise estimate = time spent + what is left."""
    t = get_task(conn, body["task_id"])
    est = t["estimated_minutes"]
    if t["status"] not in ("confirmed", "in_progress") or not est or t["completed_minutes"] < est:
        raise AppError(409, "NO_OVERRUN", "This task has not used up its estimate; reload")
    if body["finished"]:
        patch = {"status": "completed", "actual_minutes": t["completed_minutes"]}
    else:
        more = body.get("more_minutes")
        if not isinstance(more, int) or not 5 <= more <= 6000:
            raise AppError(422, "VALIDATION_FAILED", "Enter how many more minutes it needs (5-6000)")
        patch = {"estimated_minutes": t["completed_minutes"] + more}
    task = update_task(conn, t["id"], {"expected_revision": body["expected_revision"], **patch})
    audit(conn, "estimate_overrun_answered", "task", t["id"], {"finished": bool(body["finished"])})
    return {"task": task}


# ------------------------------------------------------------------ offline demo history

_DEMO_TASKS = [  # (title, title_en, first estimate, actual) - clearly synthetic
    ("示例：阅读报告（合成）", "Sample: reading report (synthetic)", 120, 160),
    ("示例：实验作业（合成）", "Sample: lab assignment (synthetic)", 180, 230),
    ("示例：小组提案（合成）", "Sample: group proposal (synthetic)", 240, 300),
    ("示例：练习题（合成）", "Sample: problem set (synthetic)", 90, 120),
]
_DEMO_CHECKINS = [60, 60, 60, 60, 60, 30, 0, 0]  # minutes done in eight past 60-minute blocks


def load_demo_history(conn: sqlite3.Connection) -> dict:
    if not _demo_shown(conn):
        raise AppError(409, "DEMO_ONLY", "Sample history can only be loaded while demo data is shown")
    now = datetime.now(timezone.utc)
    ids = []
    for i, (title, title_en, est, actual) in enumerate(_DEMO_TASKS):
        key = f"{DEMO_KEY}{i}"
        row = conn.execute("SELECT id FROM tasks WHERE entity_key=?", (key,)).fetchone()
        if row:
            ids.append(row["id"])
            continue
        tid = f"task_{key}"
        ts = (now - timedelta(days=21 - 4 * i)).replace(microsecond=0).isoformat()
        conn.execute(
            """INSERT INTO tasks(id,entity_key,title,title_en,course,term,deliverable,required,status,deadline_status,
               estimated_minutes,first_estimate_minutes,completed_minutes,actual_minutes,missing_fields_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tid, key, title, title_en, "DEMO5105", "Demo Term A (synthetic)", "submission", 1, "completed", "explicit",
             est, est, actual, actual, "[]", ts, ts))
        ids.append(tid)
    for i, done in enumerate(_DEMO_CHECKINS):
        at = (now - timedelta(days=14 - 2 * i)).replace(microsecond=0).isoformat()
        conn.execute("""INSERT OR IGNORE INTO study_checkins(block_key,task_id,outcome,minutes,planned_minutes,created_at)
                        VALUES(?,?,?,?,?,?)""",
                     (f"{DEMO_KEY}checkin_{i}", ids[i % len(ids)], "done" if done == 60 else "partial" if done else "missed",
                      done, 60, at))
    audit(conn, "demo_calibration_history_loaded", "task", None, {"tasks": len(ids)})
    return overview(conn)


def clear_demo_history(conn: sqlite3.Connection) -> dict:
    conn.execute("DELETE FROM study_checkins WHERE block_key LIKE ?", (DEMO_KEY + "%",))
    for r in conn.execute("SELECT id FROM tasks WHERE entity_key LIKE ?", (DEMO_KEY + "%",)).fetchall():
        conn.execute("DELETE FROM estimate_decisions WHERE task_id=?", (r["id"],))
        conn.execute("DELETE FROM tasks WHERE id=?", (r["id"],))
    audit(conn, "demo_calibration_history_cleared", "task", None, {})
    return overview(conn)
