"""Calendar snapshots, plan previews and re-planning. Plans are suggestions; nothing is written."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..db import audit, dumps, loads, new_id, now_iso
from ..errors import AppError, not_found
from . import planner, preferences
from .task_service import get_task

# Synthetic busy pattern (weekday -> [(start, end, label)]), same as the prototype week.
# Labels are keys the UI translates (busy.class / busy.project_meeting).
MOCK_BUSY = {0: [("10:00", "12:00", "class")], 1: [("14:00", "16:00", "project_meeting")],
             3: [("10:00", "12:00", "class")], 4: [("09:00", "11:00", "class")]}
SYNTHETIC_TASK_KEY = "synthetic_demo5105_report"


def _aware(s: str) -> datetime:
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        raise AppError(422, "TIME_NEEDS_OFFSET", "Times must include a UTC offset", [s])
    return dt


def create_snapshot(conn: sqlite3.Connection, body: dict) -> dict:
    t0, t1 = _aware(body["time_min"]), _aware(body["time_max"])
    if not t0 < t1 or (t1 - t0) > timedelta(days=31):
        raise AppError(422, "INVALID_RANGE", "time_min must be before time_max, at most 31 days")
    tz_name = body.get("display_timezone") or "Asia/Singapore"
    tz = ZoneInfo(tz_name)
    provider = body["provider"]
    busy, errors, status, version = [], [], "complete", "mock-v1"
    if provider == "mock":
        d = t0.astimezone(tz).date()
        while d <= t1.astimezone(tz).date():
            for s, e, label in MOCK_BUSY.get(d.weekday(), []):
                bs = datetime.combine(d, datetime.strptime(s, "%H:%M").time(), tz)
                be = datetime.combine(d, datetime.strptime(e, "%H:%M").time(), tz)
                if be > t0 and bs < t1:
                    busy.append({"start": bs.isoformat(), "end": be.isoformat(), "kind": "busy",
                                 "source_id": "synthetic_calendar", "label_key": label})
            d += timedelta(days=1)
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
    else:
        from ..providers import calendars
        res = calendars.read_busy(conn, provider, body.get("connection_id"), t0, t1, tz_name,
                                  body.get("calendar_ids") or ["primary"])
        busy, errors, status, version = res["busy"], res["errors"], res["status"], res["version"]
        expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    sid = new_id("snap")
    conn.execute(
        """INSERT INTO calendar_snapshots(id,connection_id,provider,source_version,display_timezone,time_min,time_max,
           selected_calendars_json,busy_json,errors_json,status,fetched_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sid, body.get("connection_id"), provider, version, tz_name, t0.isoformat(), t1.isoformat(),
         dumps(body.get("calendar_ids") or []), dumps(busy), dumps(errors), status, now_iso(),
         expires.replace(microsecond=0).isoformat()))
    return get_snapshot(conn, sid)


def get_snapshot(conn: sqlite3.Connection, sid: str) -> dict:
    row = conn.execute("SELECT * FROM calendar_snapshots WHERE id=?", (sid,)).fetchone()
    if not row:
        raise not_found("calendar snapshot")
    status = row["status"]
    if status == "complete" and datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        status = "expired"
    return {"id": row["id"], "provider": row["provider"], "source_version": row["source_version"],
            "time_min": row["time_min"], "time_max": row["time_max"], "display_timezone": row["display_timezone"],
            "busy": loads(row["busy_json"], []), "status": status, "errors": loads(row["errors_json"], []),
            "expires_at": row["expires_at"], "synthetic": row["provider"] == "mock"}


def _completed_by_day(task: dict, tz: ZoneInfo) -> dict[date, int]:
    out: dict[date, int] = {}
    for p in task["progress"]:
        d = datetime.fromisoformat(p["occurred_at"]).astimezone(tz).date()
        out[d] = out.get(d, 0) + p["minutes"]
    return out


def _kept_from_previous(conn: sqlite3.Connection, previous_plan_id: str | None, now: datetime) -> list[dict]:
    """Future study blocks really written by an executed live proposal stay fixed (simulated ones do not)."""
    if not previous_plan_id:
        return []
    kept = []
    for row in conn.execute("SELECT payload_json FROM proposals WHERE source_kind='plan' AND source_object_id=? "
                            "AND status='executed'", (previous_plan_id,)).fetchall():
        for ev in loads(row[0], {}).get("events", []):
            s, e = datetime.fromisoformat(ev["start"]), datetime.fromisoformat(ev["end"])
            if s > now:
                kept.append({"task_id": ev["task_id"], "task_title": ev["title"], "phase": "study", "start": s, "end": e,
                             "minutes": int((e - s).total_seconds() // 60)})
    return kept


def build_plan(conn: sqlite3.Connection, task_ids: list[str], snapshot_id: str, prefs_revision: int,
               previous_plan_id: str | None = None) -> dict:
    prefs_value, rev = preferences.get_raw(conn)
    if prefs_revision != rev:
        raise AppError(409, "PREFERENCES_CHANGED", "Preferences changed; reload before planning", [f"current={rev}"])
    snap = get_snapshot(conn, snapshot_id)
    tz = ZoneInfo(prefs_value["display_timezone"])
    p = planner.Prefs(prefs_value["display_timezone"], prefs_value["day_start"], prefs_value["day_end"],
                      prefs_value["daily_cap_minutes"], prefs_value["session_min_minutes"],
                      prefs_value["session_target_minutes"], prefs_value["session_max_minutes"],
                      prefs_value["break_minutes"], prefs_value["deadline_buffer_minutes"],
                      prefs_value["weekly_flex_minutes"])
    missing, tasks_in, revisions, completed = [], [], {}, {}
    for tid in task_ids:
        t = get_task(conn, tid)
        revisions[tid] = t["revision"]
        if t["status"] not in ("confirmed", "in_progress"):
            missing.append(f"{t['title']}: task_not_confirmed")
            continue
        if not t["planning_cutoff_utc"] or t["estimated_minutes"] is None:
            missing.append(f"{t['title']}: needs_cutoff_and_estimate")
            continue
        remaining = max(0, t["estimated_minutes"] - t["completed_minutes"])
        for d, m in _completed_by_day(t, tz).items():
            completed[d] = completed.get(d, 0) + m
        if remaining > 0:
            tasks_in.append(planner.TaskIn(t["id"], t["title"], remaining, datetime.fromisoformat(t["planning_cutoff_utc"])))
    t0, t1 = datetime.fromisoformat(snap["time_min"]), datetime.fromisoformat(snap["time_max"])
    binding = []
    if snap["status"] != "complete":
        # A failed or partial calendar read is never treated as free time (T11).
        missing.append(f"calendar_snapshot_{snap['status']}")
        result = planner.Result()
        status = "needs_information"
    else:
        busy = [(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])) for b in snap["busy"]]
        kept = _kept_from_previous(conn, previous_plan_id, datetime.now(timezone.utc))
        result = planner.plan(tasks_in, busy, p, t0, t1, completed, kept)
        binding = result.binding
        if result.violations:
            status = "needs_adjustment"
        elif missing and not tasks_in:
            status = "needs_information"
        elif result.unmet == 0:
            status = "feasible" if not missing else "needs_information"
        elif result.infeasible_proven:
            status = "infeasible"
        else:
            status = "needs_adjustment"
    crunch = _crunch_warnings(conn, task_ids, p)
    plan_id = new_id("plan")
    changes = _diff(conn, previous_plan_id, result.sessions) if previous_plan_id else []
    inputs = {"task_ids": task_ids, "task_revisions": revisions, "preferences_revision": rev,
              "planning_hash": preferences.planning_hash(prefs_value), "snapshot_id": snapshot_id,
              "display_timezone": p.tz, "time_min": snap["time_min"], "time_max": snap["time_max"],
              "synthetic": snap["synthetic"]}
    validation = {"violations": result.violations, "per_task": result.per_task, "demand": result.demand,
                  "capacity_upper_bound": result.capacity_upper_bound, "binding": binding + crunch,
                  "missing": missing, "busy": snap["busy"], "days": result.days}
    conn.execute(
        """INSERT INTO plans(id,previous_plan_id,snapshot_id,inputs_json,sessions_json,reserved_flex_json,changes_json,
           validation_json,unmet_minutes,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (plan_id, previous_plan_id, snapshot_id, dumps(inputs), dumps(result.sessions), dumps(result.flex),
         dumps(changes), dumps(validation), result.unmet, status, now_iso()))
    audit(conn, "plan_previewed", "plan", plan_id, {"status": status, "sessions": len(result.sessions),
                                                    "unmet": result.unmet})
    return get_plan(conn, plan_id)


def _crunch_warnings(conn, task_ids, p) -> list[str]:
    """48-hour concentration: work due inside any 48h window above two days of cap."""
    items = []
    for tid in task_ids:
        t = get_task(conn, tid)
        if t["planning_cutoff_utc"] and t["estimated_minutes"]:
            items.append((datetime.fromisoformat(t["planning_cutoff_utc"]), max(0, t["estimated_minutes"] - t["completed_minutes"]), t["title"]))
    items.sort()
    out = []
    for i, (c, _, title) in enumerate(items):
        window = [x for x in items if c <= x[0] < c + timedelta(hours=48)]
        total = sum(x[1] for x in window)
        if len(window) > 1 and total > 2 * p.daily_cap:
            out.append(f"crunch_48h:{c.isoformat()}:{total}min:{len(window)}tasks")
    return sorted(set(out))


def _diff(conn, previous_plan_id: str, new_sessions: list[dict]) -> list[dict]:
    prev = conn.execute("SELECT sessions_json FROM plans WHERE id=?", (previous_plan_id,)).fetchone()
    old = loads(prev[0], []) if prev else []
    key = lambda s: (s["task_id"], s["start"], s["end"])  # noqa: E731
    old_k, new_k = {key(s): s for s in old}, {key(s): s for s in new_sessions}
    out = [{"change": "kept", **s} for k, s in new_k.items() if k in old_k]
    out += [{"change": "new", **s} for k, s in new_k.items() if k not in old_k]
    out += [{"change": "removed_suggestion", **s} for k, s in old_k.items() if k not in new_k]
    return sorted(out, key=lambda s: s["start"])


def stale_reasons(conn: sqlite3.Connection, inputs: dict) -> list[str]:
    reasons = []
    for tid, rev in inputs.get("task_revisions", {}).items():
        row = conn.execute("SELECT revision FROM tasks WHERE id=?", (tid,)).fetchone()
        if not row or row[0] != rev:
            reasons.append(f"task_changed:{tid}")
    value, _ = preferences.get_raw(conn)
    if preferences.planning_hash(value) != inputs.get("planning_hash"):
        reasons.append("preferences_changed")
    snap = conn.execute("SELECT expires_at FROM calendar_snapshots WHERE id=?", (inputs.get("snapshot_id"),)).fetchone()
    if not snap or datetime.fromisoformat(snap[0]) <= datetime.now(timezone.utc):
        reasons.append("calendar_snapshot_expired")
    return reasons


def get_plan(conn: sqlite3.Connection, plan_id: str) -> dict:
    row = conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        raise not_found("plan")
    inputs, val = loads(row["inputs_json"], {}), loads(row["validation_json"], {})
    reasons = stale_reasons(conn, inputs)
    newer = conn.execute("SELECT id FROM plans WHERE previous_plan_id=?", (plan_id,)).fetchone()
    if newer:
        reasons.append(f"replaced_by:{newer[0]}")
    status = "stale" if reasons else row["status"]
    return {"id": row["id"], "status": status, "computed_status": row["status"], "revision": row["revision"],
            "sessions": loads(row["sessions_json"], []), "reserved_flex": loads(row["reserved_flex_json"], []),
            "unmet_minutes": row["unmet_minutes"], "capacity_upper_bound_minutes": val.get("capacity_upper_bound"),
            "demand_minutes": val.get("demand", 0), "missing_fields": val.get("missing", []),
            "binding_constraints": val.get("binding", []), "changes": loads(row["changes_json"], []),
            "violations": val.get("violations", []), "inputs": inputs, "per_task": val.get("per_task", []),
            "busy": val.get("busy", []), "days": val.get("days", []), "stale_reasons": reasons,
            "previous_plan_id": row["previous_plan_id"], "synthetic": bool(inputs.get("synthetic")),
            "created_at": row["created_at"]}


def replan(conn: sqlite3.Connection, plan_id: str, body: dict) -> dict:
    old = get_plan(conn, plan_id)
    if old["revision"] != body["expected_revision"]:
        raise AppError(409, "REVISION_CONFLICT", "Plan changed")
    new = build_plan(conn, old["inputs"]["task_ids"], body["snapshot_id"], body["preferences_revision"], plan_id)
    from .proposal_service import invalidate_for_source
    invalidate_for_source(conn, "plan", plan_id, "replanned")
    return new


def load_synthetic_scenario(conn: sqlite3.Connection, effort_minutes: int = 360) -> dict:
    """A clearly synthetic report (due Fri 2026-10-23 17:00 SGT) for the planning demo."""
    row = conn.execute("SELECT id FROM tasks WHERE entity_key=?", (SYNTHETIC_TASK_KEY,)).fetchone()
    ts = now_iso()
    if row:
        conn.execute("UPDATE tasks SET estimated_minutes=?, revision=revision+1, updated_at=? WHERE id=?",
                     (effort_minutes, ts, row[0]))
        task_id = row[0]
    else:
        task_id = new_id("task")
        conn.execute(
            """INSERT INTO tasks(id,entity_key,title,course,term,deliverable,required,status,official_date,official_time,
               source_timezone,deadline_status,date_candidates_json,estimated_minutes,missing_fields_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (task_id, SYNTHETIC_TASK_KEY, "DEMO5105 报告（合成）", "DEMO5105",
             "Demo Term A (synthetic)", "submission", 1, "confirmed", "2026-10-23", "17:00", "Asia/Singapore",
             "explicit", dumps([{"source_id": "synthetic", "origin": "synthetic_fixture"}]), effort_minutes, "[]", ts, ts))
    from .task_service import _refresh_derived
    _refresh_derived(conn, task_id)
    audit(conn, "synthetic_scenario_loaded", "task", task_id, {"effort": effort_minutes})
    return get_task(conn, task_id)
