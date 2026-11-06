"""Calendar snapshots, plan previews and re-planning. Plans are suggestions; nothing is written."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from ..db import audit, dumps, loads, new_id, now_iso
from ..errors import AppError, not_found
from . import planner, preferences, repair
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
        # Meetings the student added to the sample timetable to try out conflict handling offline.
        for m in demo_meetings(conn):
            bs, be = datetime.fromisoformat(m["start"]), datetime.fromisoformat(m["end"])
            if be > t0 and bs < t1:
                busy.append({"start": m["start"], "end": m["end"], "kind": "busy", "source_id": "demo_meeting",
                             "label_key": "demo_meeting", "label": m["label"] or None})
        expires = datetime.now(timezone.utc) + timedelta(hours=24)
    else:
        from ..providers import calendars
        res = calendars.read_busy(conn, provider, body.get("connection_id"), t0, t1, tz_name,
                                  body.get("calendar_ids") or ["primary"])
        busy, errors, status, version = res["busy"], res["errors"], res["status"], res["version"]
        expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    extras = {"study_calendar": _read_study_calendar(conn, provider, t0, t1, tz_name, status)}
    busy += extras["study_calendar"].pop("busy", [])
    sid = new_id("snap")
    conn.execute(
        """INSERT INTO calendar_snapshots(id,connection_id,provider,source_version,display_timezone,time_min,time_max,
           selected_calendars_json,busy_json,errors_json,status,fetched_at,expires_at,extras_json)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sid, body.get("connection_id"), provider, version, tz_name, t0.isoformat(), t1.isoformat(),
         dumps(body.get("calendar_ids") or []), dumps(busy), dumps(errors), status, now_iso(),
         expires.replace(microsecond=0).isoformat(), dumps(extras)))
    return get_snapshot(conn, sid)


def _app_calendar_id(conn: sqlite3.Connection, provider: str = "google") -> str | None:
    from ..providers.writers import app_calendar_id
    return app_calendar_id(conn, provider)


STUDY_PROVIDERS = ("google", "microsoft")


def study_calendars(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    """(provider, calendar id) of every study calendar this app created and can still read."""
    from ..providers import oauth
    return [(p, cal) for p in STUDY_PROVIDERS
            if (cal := _app_calendar_id(conn, p)) and oauth.has_scope(conn, p, "read_busy")]


def study_calendar_target(conn: sqlite3.Connection, plan: dict) -> str:
    """Which account's study calendar a plan's new blocks go to: the account the plan's busy times came from, if it
    has a study calendar; otherwise the one that has; otherwise that account (the review then asks to create one)."""
    from ..providers import oauth
    source = get_snapshot(conn, plan["inputs"]["snapshot_id"])["provider"]
    ready = [p for p in STUDY_PROVIDERS if _app_calendar_id(conn, p) and oauth.has_scope(conn, p, "study_calendar")]
    if source in ready:
        return source
    if ready:
        return ready[0]
    return source if source in STUDY_PROVIDERS else "google"


def _read_study_calendar(conn: sqlite3.Connection, provider: str, t0: datetime, t1: datetime, tz_name: str,
                         main_status: str) -> dict:
    """Study blocks are written to the app's own study calendar (Google and/or Outlook), which the main busy read
    does not cover. Read them too, so blocks written earlier are seen when a plan is generated again. Best effort:
    if one cannot be read, the plan falls back to this app's own write records (never to 'free')."""
    if provider == "mock" or main_status != "complete":
        return {"status": "not_read"}
    cals = study_calendars(conn)
    if not cals:
        return {"status": "not_available"}
    from ..providers import calendars
    busy = []
    for prov, cal in cals:
        res = calendars.read_busy(conn, prov, f"conn_{prov}", t0, t1, tz_name, [cal])
        if res["status"] != "complete":
            return {"status": "failed", "errors": res["errors"], "provider": prov}
        busy += [{**b, "own_study": True, "study_provider": prov} for b in res["busy"]]
    return {"status": "complete", "busy": busy, "providers": [p for p, _ in cals]}


def get_snapshot(conn: sqlite3.Connection, sid: str) -> dict:
    row = conn.execute("SELECT * FROM calendar_snapshots WHERE id=?", (sid,)).fetchone()
    if not row:
        raise not_found("calendar snapshot")
    status = row["status"]
    if status == "complete" and datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        status = "expired"
    extras = loads(row["extras_json"], {}) if "extras_json" in row.keys() else {}
    return {"id": row["id"], "provider": row["provider"], "source_version": row["source_version"],
            "connection_id": row["connection_id"], "calendar_ids": loads(row["selected_calendars_json"], []),
            "time_min": row["time_min"], "time_max": row["time_max"], "display_timezone": row["display_timezone"],
            "busy": loads(row["busy_json"], []), "status": status, "errors": loads(row["errors_json"], []),
            "expires_at": row["expires_at"], "synthetic": row["provider"] == "mock",
            "study_calendar": extras.get("study_calendar", {"status": "not_read"})}


def completed_all_tasks(conn: sqlite3.Connection, tz: ZoneInfo) -> dict[date, int]:
    """Minutes already logged per day on EVERY task. The daily cap is a limit on the person's day, so work logged
    on a task that is not selected in this plan still uses it up (switching the selection cannot free it)."""
    out: dict[date, int] = {}
    for row in conn.execute("SELECT progress_json FROM tasks").fetchall():
        for p in loads(row[0], []):
            d = datetime.fromisoformat(p["occurred_at"]).astimezone(tz).date()
            out[d] = out.get(d, 0) + int(p["minutes"])
    return {d: m for d, m in out.items() if m > 0}  # an undo logged on another day never creates extra room


def completed_by_task(conn: sqlite3.Connection, tz: ZoneInfo) -> dict[tuple[str, date], int]:
    """Minutes logged per (task, day), for the per-task daily cap."""
    out: dict[tuple[str, date], int] = {}
    for row in conn.execute("SELECT id, progress_json FROM tasks").fetchall():
        for p in loads(row["progress_json"], []):
            k = (row["id"], datetime.fromisoformat(p["occurred_at"]).astimezone(tz).date())
            out[k] = out.get(k, 0) + int(p["minutes"])
    return {k: m for k, m in out.items() if m > 0}


def task_done(conn: sqlite3.Connection, tz: ZoneInfo, cal: dict) -> dict[tuple[str, date], int]:
    """Per (task, day): logged progress plus written blocks just before the planning window (the planner counts
    the blocks inside it itself)."""
    out = completed_by_task(conn, tz)
    for k, m in cal["committed_by_task"].items():
        out[k] = out.get(k, 0) + m
    return out


def written_blocks_all(conn: sqlite3.Connection) -> list[dict]:
    """Every study block this app really wrote to a calendar (live proposals), with its calendar event id when
    known. Partly finished writes keep the events that were created; an 'unknown' outcome keeps them all
    (conservative: possibly created events are never planned a second time). Events this app later removed
    (when a block was moved) are left out."""
    rows = conn.execute("SELECT status, payload_json, result_json FROM proposals WHERE operation='create_study_events' "
                        "AND mode='live' AND status IN ('executed','failed','unknown') ORDER BY created_at").fetchall()
    removed = set()
    for row in rows:
        for x in (loads(row["result_json"], {}) or {}).get("removed", []) or []:
            if x.get("status") in ("executed", "already_gone"):
                removed.add(x["event_id"])
    out, seen = [], set()
    for row in rows:
        payload = loads(row["payload_json"], {})
        events = payload.get("events", [])
        provider = (payload.get("connection_id") or "conn_google").split("_", 1)[1]  # older writes: Google only
        per_event = (loads(row["result_json"], {}) or {}).get("events")
        for i, ev in enumerate(events):
            if row["status"] != "executed" and per_event is not None:
                st = per_event[i]["status"] if i < len(per_event) else "not_attempted"
                if st not in ("executed", "unknown"):
                    continue
            elif row["status"] == "failed":
                continue  # failed before any event was attempted
            event_id = per_event[i].get("event_id") if per_event and i < len(per_event) else None
            if event_id and event_id in removed:
                continue
            s_, e_ = datetime.fromisoformat(ev["start"]), datetime.fromisoformat(ev["end"])
            key = (ev["task_id"], s_, e_)
            if key in seen:
                continue
            seen.add(key)
            out.append({"task_id": ev["task_id"], "task_title": ev.get("title", "").removeprefix("Study: "),
                        "phase": "study", "start": s_, "end": e_, "minutes": int((e_ - s_).total_seconds() // 60),
                        "written": True, "event_id": event_id, "provider": provider})
    return sorted(out, key=lambda k: k["start"])


def written_study_blocks(conn: sqlite3.Connection, t0: datetime, t1: datetime, now: datetime) -> list[dict]:
    """Written blocks that are not over yet and end inside the planning window."""
    return [b for b in written_blocks_all(conn) if now < b["end"] <= t1]


def _subtract_intervals(iv: tuple[datetime, datetime], blocks: list[tuple[datetime, datetime]]) -> list[tuple]:
    pieces = [iv]
    for bs, be in blocks:
        nxt = []
        for s, e in pieces:
            if be <= s or bs >= e:
                nxt.append((s, e))
                continue
            if bs > s:
                nxt.append((s, bs))
            if be < e:
                nxt.append((be, e))
        pieces = nxt
    return [(s, e) for s, e in pieces if (e - s) >= timedelta(minutes=1)]


def reconcile_study_blocks(written: list[dict], snap: dict) -> tuple[list[dict], list[dict], list[str]]:
    """-> (kept blocks, busy entries for the planner, notes).
    When the study calendar was read, a written block that is no longer there was removed by the person and is not
    kept; busy time on that calendar that no written block explains (e.g. an event added by hand) stays busy.
    When it could not be read, every written block is kept, so nothing is planned twice."""
    own = [b for b in snap["busy"] if b.get("own_study")]
    other = [b for b in snap["busy"] if not b.get("own_study")]
    notes: list[str] = []
    if snap.get("study_calendar", {}).get("status") != "complete":
        if written:
            notes.append(f"study_blocks_from_records:{len(written)}")
        return written, other + own, notes
    own_iv = [(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])) for b in own]
    own_prov = [b.get("study_provider", "google") for b in own]
    read = set(snap["study_calendar"].get("providers") or ["google"])
    # A block is still there if its own account's study calendar shows it. A block in an account whose study
    # calendar was not read this time is kept (it may well still be there).
    kept = [k for k in written if k.get("provider", "google") not in read
            or any(bs < k["end"] and k["start"] < be and p == k.get("provider", "google")
                   for (bs, be), p in zip(own_iv, own_prov))]
    for k in written:
        if k not in kept:
            notes.append(f"study_block_removed_in_calendar:{k['start'].isoformat()}")
    leftover = []
    for b, (bs, be) in zip(own, own_iv):
        same_provider = [(k["start"], k["end"]) for k in kept
                         if (k.get("provider") or "google") == (b.get("study_provider") or "google")]
        for s, e in _subtract_intervals((bs, be), same_provider):
            leftover.append({**b, "start": s.isoformat(), "end": e.isoformat(), "own_study": False,
                             "kind": "busy", "label_key": "study_calendar_other"})
    return kept, other + leftover, notes


plan_status = planner.plan_status  # kept here for existing imports


def _prefs(prefs_value: dict) -> planner.Prefs:
    return planner.Prefs(prefs_value["display_timezone"], prefs_value["day_start"], prefs_value["day_end"],
                         prefs_value["daily_cap_minutes"], prefs_value["session_min_minutes"],
                         prefs_value["session_target_minutes"], prefs_value["session_max_minutes"],
                         prefs_value["break_minutes"], prefs_value["deadline_buffer_minutes"],
                         prefs_value["weekly_flex_minutes"], prefs_value.get("task_daily_cap_minutes") or 0)


def _tasks_in(conn: sqlite3.Connection, task_ids: list[str]) -> tuple[list[planner.TaskIn], list[str], dict]:
    missing, tasks_in, revisions = [], [], {}
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
        if remaining > 0:
            tasks_in.append(planner.TaskIn(t["id"], t["title"], remaining, datetime.fromisoformat(t["planning_cutoff_utc"])))
    return tasks_in, missing, revisions


def _calendar_state(conn: sqlite3.Connection, snap: dict, tz: ZoneInfo) -> dict:
    """Busy time, written blocks and their reconciliation with the study calendar, for a complete snapshot."""
    t0, t1 = datetime.fromisoformat(snap["time_min"]), datetime.fromisoformat(snap["time_max"])
    written = written_study_blocks(conn, t0, t1, datetime.now(timezone.utc))
    # Blocks starting before the horizon (e.g. later this hour, or under way) are outside the planning window
    # but still use that day's cap.
    committed: dict[date, int] = {}
    committed_by_task: dict[tuple[str, date], int] = {}
    for k in written:
        if k["start"] < t0:
            d = k["start"].astimezone(tz).date()
            committed[d] = committed.get(d, 0) + k["minutes"]
            committed_by_task[(k["task_id"], d)] = committed_by_task.get((k["task_id"], d), 0) + k["minutes"]
    kept, busy_entries, notes = reconcile_study_blocks([k for k in written if k["start"] >= t0], snap)
    busy = [(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])) for b in busy_entries]
    return {"t0": t0, "t1": t1, "kept": kept, "committed": committed, "committed_by_task": committed_by_task,
            "busy_entries": busy_entries, "busy": busy, "notes": notes}


def _store_plan(conn: sqlite3.Connection, *, previous_plan_id: str | None, diff_against: str | None, snapshot_id: str,
                inputs: dict, result: planner.Result, status: str, busy_entries: list, binding: list[str],
                missing: list[str]) -> str:
    plan_id = new_id("plan")
    changes = _diff(conn, diff_against, result.sessions) if diff_against else []
    validation = {"violations": result.violations, "per_task": result.per_task, "demand": result.demand,
                  "capacity_upper_bound": result.capacity_upper_bound, "binding": binding,
                  "missing": missing, "busy": busy_entries, "days": result.days}
    conn.execute(
        """INSERT INTO plans(id,previous_plan_id,snapshot_id,inputs_json,sessions_json,reserved_flex_json,changes_json,
           validation_json,unmet_minutes,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (plan_id, previous_plan_id, snapshot_id, dumps(inputs), dumps(result.sessions), dumps(result.flex),
         dumps(changes), dumps(validation), result.unmet, status, now_iso()))
    return plan_id


def _base_inputs(task_ids, revisions, rev, prefs_value, p, snap) -> dict:
    return {"task_ids": task_ids, "task_revisions": revisions, "preferences_revision": rev,
            "planning_hash": preferences.planning_hash(prefs_value), "snapshot_id": snap["id"],
            "display_timezone": p.tz, "time_min": snap["time_min"], "time_max": snap["time_max"],
            "synthetic": snap["synthetic"]}


def reference_now(snap: dict) -> datetime:
    """'Now' for deciding which blocks are still ahead. The offline sample week has fixed (past) dates, so for a
    sample-timetable plan the moment just before its start plays the role of now; real calendars use real time."""
    now = datetime.now(timezone.utc)
    if snap.get("synthetic"):
        return min(now, datetime.fromisoformat(snap["time_min"]) - timedelta(minutes=1))
    return now


def _future_blocks(plan: dict, t0: datetime, t1: datetime, task_ids: set[str], locked_only: bool = False,
                   now: datetime | None = None) -> list[dict]:
    """Not-yet-written blocks of a plan that are still ahead and inside the window, as fixed-block inputs."""
    now = now or datetime.now(timezone.utc)
    out = []
    for x in plan["sessions"]:
        st, en = datetime.fromisoformat(x["start"]), datetime.fromisoformat(x["end"])
        if x.get("kept") or st <= now or st < t0 or en > t1 or x["task_id"] not in task_ids:
            continue
        if locked_only and not x.get("locked"):
            continue
        out.append({"task_id": x["task_id"], "task_title": x["task_title"], "phase": "study", "start": st, "end": en,
                    "minutes": x["minutes"], "locked": bool(x.get("locked")), "manual": bool(x.get("manual"))})
    return out


def build_plan(conn: sqlite3.Connection, task_ids: list[str], snapshot_id: str, prefs_revision: int,
               previous_plan_id: str | None = None) -> dict:
    prefs_value, rev = preferences.get_raw(conn)
    if prefs_revision != rev:
        raise AppError(409, "PREFERENCES_CHANGED", "Preferences changed; reload before planning", [f"current={rev}"])
    snap = get_snapshot(conn, snapshot_id)
    tz = ZoneInfo(prefs_value["display_timezone"])
    p = _prefs(prefs_value)
    tasks_in, missing, revisions = _tasks_in(conn, task_ids)
    completed = completed_all_tasks(conn, tz)
    binding: list[str] = []
    shown_busy = snap["busy"]
    overrides: list[str] = []
    if snap["status"] != "complete":
        # A failed or partial calendar read is never treated as free time (T11).
        missing.append(f"calendar_snapshot_{snap['status']}")
        result = planner.Result()
    else:
        cal = _calendar_state(conn, snap, tz)
        shown_busy = cal["busy_entries"]
        pins = []
        if previous_plan_id:
            # Blocks the student locked (edited by hand) stay where they are when re-planning.
            prev = get_plan(conn, previous_plan_id)
            pins = [{**x, "pinned": True} for x in _future_blocks(prev, cal["t0"], cal["t1"], {t.id for t in tasks_in}, True,
                                                                     reference_now(snap))]
            overrides = prev["inputs"].get("overrides", [])
        result = planner.plan(tasks_in, cal["busy"], p, cal["t0"], cal["t1"], completed, cal["kept"] + pins, cal["committed"],
                              task_done(conn, tz, cal))
        binding = result.binding + cal["notes"]
    status = plan_status(result, missing, bool(tasks_in), snap["status"] == "complete", overrides)
    inputs = {**_base_inputs(task_ids, revisions, rev, prefs_value, p, snap), "overrides": overrides}
    plan_id = _store_plan(conn, previous_plan_id=previous_plan_id, diff_against=previous_plan_id, snapshot_id=snapshot_id,
                          inputs=inputs, result=result, status=status, busy_entries=shown_busy,
                          binding=binding + _crunch_warnings(conn, task_ids, p), missing=missing)
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
    repair = inputs.get("repair")
    if repair and not repair.get("adopted"):
        reasons.append("repair_option_not_chosen")  # a candidate only becomes a plan when the student picks it
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
    status = "stale" if reasons else row["status"]  # stored status already ignores accepted exceptions
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
    row = conn.execute("SELECT id,status FROM tasks WHERE entity_key=?", (SYNTHETIC_TASK_KEY,)).fetchone()
    ts = now_iso()
    if row:
        # A fresh demo run: the chosen effort is the first estimate again, and any earlier calibration answer is gone.
        conn.execute("UPDATE tasks SET estimated_minutes=?, first_estimate_minutes=?, revision=revision+1, updated_at=? WHERE id=?",
                     (effort_minutes, effort_minutes, ts, row[0]))
        if row["status"] in ("completed", "ignored"):
            conn.execute("UPDATE tasks SET status='confirmed',completed_minutes=0,progress_json='[]',actual_minutes=NULL WHERE id=?",
                         (row[0],))
        conn.execute("DELETE FROM estimate_decisions WHERE task_id=?", (row[0],))
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



# ------------------------------------------------------------------ conflicts and repair

def latest_plan_id(conn: sqlite3.Connection) -> str | None:
    """Most recent plan the student is working with (candidate repair options that were not chosen are skipped)."""
    for row in conn.execute("SELECT id, inputs_json FROM plans ORDER BY created_at DESC, rowid DESC LIMIT 50"):
        repair = loads(row["inputs_json"], {}).get("repair")
        if not repair or repair.get("adopted"):
            return row["id"]
    return None


def fresh_snapshot(conn: sqlite3.Connection, plan_id: str) -> dict:
    """Read the calendar again exactly as this plan was made from it: same source, account, calendars and days.
    Everything that works on an existing plan (conflict check, fixes, edits) uses this, so a different calendar
    picked on the page for the next plan is never mixed in. A real-calendar plan whose days are over is not
    re-read: it has nothing left to check."""
    row = conn.execute("SELECT inputs_json FROM plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        raise not_found("plan")
    old = get_snapshot(conn, loads(row["inputs_json"], {})["snapshot_id"])
    if not old["synthetic"] and datetime.fromisoformat(old["time_max"]) <= datetime.now(timezone.utc):
        raise AppError(409, "PLAN_WINDOW_OVER", "The days this plan covers are over; generate a new plan")
    return create_snapshot(conn, {k: old[k] for k in ("provider", "connection_id", "time_min", "time_max",
                                                      "calendar_ids", "display_timezone")})


def _fresh(conn: sqlite3.Connection, snapshot_id: str) -> dict:
    snap = get_snapshot(conn, snapshot_id)
    if snap["status"] != "complete":
        raise AppError(409, "CALENDAR_NOT_READ", "The calendar could not be read completely; it is never treated as free",
                       [snap["status"]])
    return snap


def _repair_context(conn: sqlite3.Connection, plan_id: str, snapshot_id: str, prefs_revision: int | None):
    base = get_plan(conn, plan_id)
    repair = base["inputs"].get("repair")
    if repair and not repair.get("adopted"):
        raise AppError(409, "OPTION_NOT_CHOSEN", "Choose an option first; candidates cannot be repaired themselves")
    prefs_value, rev = preferences.get_raw(conn)
    if prefs_revision is not None and prefs_revision != rev:
        raise AppError(409, "PREFERENCES_CHANGED", "Preferences changed; reload before planning", [f"current={rev}"])
    snap = _fresh(conn, snapshot_id)
    tz = ZoneInfo(prefs_value["display_timezone"])
    p = _prefs(prefs_value)
    tasks_in, missing, revisions = _tasks_in(conn, base["inputs"]["task_ids"])
    cal = _calendar_state(conn, snap, tz)
    current = _future_blocks(base, cal["t0"], cal["t1"], {t.id for t in tasks_in}, now=reference_now(snap))
    return base, prefs_value, rev, snap, tz, p, tasks_in, missing, revisions, cal, current


def check_conflicts(conn: sqlite3.Connection, plan_id: str, snapshot_id: str) -> dict:
    """Read-only: which blocks of the plan now overlap busy time, and whether all work still fits."""
    base, prefs_value, rev, snap, tz, p, tasks_in, missing, revisions, cal, current = _repair_context(
        conn, plan_id, snapshot_id, None)
    conflicts = repair.find_conflicts([{**w, "written": True} for w in cal["kept"]] + current, cal["busy"])
    fit = planner.plan(tasks_in, cal["busy"], p, cal["t0"], cal["t1"], completed_all_tasks(conn, tz),
                       [w for w in cal["kept"] if not repair.overlapping(w["start"], w["end"], cal["busy"])]
                       + [{**s, "pinned": True} for s in current
                          if not repair.overlapping(s["start"], s["end"], cal["busy"])], cal["committed"],
                       task_done(conn, tz, cal))
    return {"plan_id": plan_id, "snapshot_id": snapshot_id, "conflicts": conflicts,
            "unplaced_minutes": fit.unmet if not conflicts else None,
            "needs_attention": bool(conflicts) or fit.unmet > 0 or base["status"] in ("infeasible", "needs_adjustment"),
            "kind": "calendar" if conflicts else ("capacity" if fit.unmet > 0 else None)}


def repair_options(conn: sqlite3.Connection, plan_id: str, snapshot_id: str, prefs_revision: int) -> dict:
    """Build up to three ranked candidate plans that resolve the conflicts. Nothing is written or replaced until
    the student adopts one (adopt_option) and then reviews it like any plan."""
    base, prefs_value, rev, snap, tz, p, tasks_in, missing, revisions, cal, current = _repair_context(
        conn, plan_id, snapshot_id, prefs_revision)
    overrides = base["inputs"].get("overrides", [])
    conflicts, options = repair.build_options(tasks_in, cal["busy"], p, cal["t0"], cal["t1"],
                                              completed_all_tasks(conn, tz), cal["committed"], cal["kept"], current,
                                              overrides, task_done(conn, tz, cal))
    out = []
    for i, o in enumerate(options):
        removals = {x["event_id"]: x for x in base["inputs"].get("remove_written", []) + o.remove_written}
        inputs = {**_base_inputs(base["inputs"]["task_ids"], revisions, rev, prefs_value, p, snap),
                  "overrides": overrides, "remove_written": list(removals.values()),
                  "repair": {"base_plan_id": plan_id, "strategy": o.strategy, "adopted": False, "relaxed": o.relaxed,
                             "changed": o.changed, "dropped": o.dropped}}
        if o.prefs is not None and o.prefs != p:
            inputs["relaxed_prefs"] = {"daily_cap_minutes": o.prefs.daily_cap, "weekly_flex_minutes": o.prefs.flex,
                                       "task_daily_cap_minutes": o.prefs.task_cap}
        oid = _store_plan(conn, previous_plan_id=None, diff_against=plan_id, snapshot_id=snapshot_id, inputs=inputs,
                          result=o.result, status=o.status, busy_entries=cal["busy_entries"],
                          binding=o.result.binding + cal["notes"], missing=missing)
        out.append({"plan": get_plan(conn, oid), "strategy": o.strategy, "changed": o.changed, "dropped": o.dropped,
                    "relaxed": o.relaxed, "unmet": o.result.unmet, "min_slack_minutes": o.min_slack_minutes,
                    "moves_written": len(o.remove_written), "recommended": i == 0})
    audit(conn, "repair_options_built", "plan", plan_id, {"conflicts": len(conflicts), "options": len(out)})
    return {"base_plan_id": plan_id, "conflicts": conflicts, "options": out,
            "kind": "calendar" if conflicts else ("capacity" if out else None),
            "extension_suggested": bool(out) and min(o["unmet"] for o in out) > 0}


def adopt_option(conn: sqlite3.Connection, plan_id: str, expected_revision: int) -> dict:
    """The student picks one candidate: it becomes the current plan (the others can no longer be saved)."""
    row = conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
    if not row:
        raise not_found("plan")
    if row["revision"] != expected_revision:
        raise AppError(409, "REVISION_CONFLICT", "Plan changed")
    inputs = loads(row["inputs_json"], {})
    rep = inputs.get("repair")
    if not rep or rep.get("adopted"):
        raise AppError(409, "NOT_A_PENDING_OPTION", "This plan is not a candidate waiting to be chosen")
    base_id = rep["base_plan_id"]
    if conn.execute("SELECT 1 FROM plans WHERE previous_plan_id=?", (base_id,)).fetchone():
        raise AppError(409, "BASE_REPLACED", "The plan this option was made for has already been replaced")
    other = [r for r in stale_reasons(conn, {**inputs, "repair": None}) if r != "repair_option_not_chosen"]
    if other:
        raise AppError(409, "OPTION_STALE", "Something changed since the options were made; check again", other)
    rep["adopted"] = True
    conn.execute("UPDATE plans SET inputs_json=?, previous_plan_id=?, revision=revision+1 WHERE id=?",
                 (dumps(inputs), base_id, plan_id))
    from .proposal_service import invalidate_for_source
    invalidate_for_source(conn, "plan", base_id, "replaced_by_repair")
    audit(conn, "repair_option_adopted", "plan", plan_id, {"strategy": rep["strategy"], "base": base_id})
    return get_plan(conn, plan_id)


def edit_block(conn: sqlite3.Connection, plan_id: str, body: dict) -> dict:
    """Move, resize, remove or unlock one block by hand. The edited block is locked so later re-planning keeps it.
    Hard limits are refused (EDIT_NOT_ALLOWED); soft rules (daily cap, deadline buffer, session length, break,
    day window, weekly flex) are returned as SOFT_RULES until the student explicitly accepts them."""
    base, prefs_value, rev, snap, tz, p, tasks_in, missing, revisions, cal, current = _repair_context(
        conn, plan_id, body["snapshot_id"], body["preferences_revision"])
    if base["revision"] != body["expected_revision"]:
        raise AppError(409, "REVISION_CONFLICT", "Plan changed")
    target_start = datetime.fromisoformat(body["start"])
    tasks = {t.id: t for t in tasks_in}
    if body["task_id"] not in tasks:
        raise AppError(422, "TASK_NOT_PLANNED", "This task has no remaining work in the plan")
    written = list(cal["kept"])
    removal = None
    hit = next((s for s in current if s["task_id"] == body["task_id"] and s["start"] == target_start), None)
    if hit:
        current.remove(hit)
    else:
        hit = next((w for w in written if w["task_id"] == body["task_id"] and w["start"] == target_start), None)
        if not hit:
            raise not_found("study block")
        if not hit.get("event_id"):
            raise AppError(422, "CANNOT_MOVE_WRITTEN", "This written block has no known calendar event id; change it in the calendar")
        written.remove(hit)
        removal = {"event_id": hit["event_id"], "task_id": hit["task_id"], "start": hit["start"].isoformat(),
                   "end": hit["end"].isoformat(), "provider": hit.get("provider", "google")}  # the account it lives in
    edited = None
    if not body.get("remove"):
        st = datetime.fromisoformat(body["new_start"]) if body.get("new_start") else hit["start"]
        if st.tzinfo is None:
            raise AppError(422, "TIME_NEEDS_OFFSET", "Times must include a UTC offset")
        minutes = int(body.get("minutes") or hit["minutes"])
        en = st + timedelta(minutes=minutes)
        errs = repair.edit_window_ok(st.astimezone(tz), en.astimezone(tz), cal["t0"], cal["t1"], reference_now(snap))
        if repair.overlapping(st, en, cal["busy"]):
            errs.append("overlaps_calendar_event")
        if repair.overlapping(st, en, [(x["start"], x["end"]) for x in current + written]):
            errs.append("overlaps_another_study_block")
        if en > tasks[body["task_id"]].cutoff:
            errs.append("after_deadline")
        if minutes < 5 or minutes > 240:
            errs.append("minutes_out_of_range")
        if errs:
            raise AppError(422, "EDIT_NOT_ALLOWED", "This change breaks a hard limit", errs)
        locked = not body.get("unlock")
        edited = {"task_id": hit["task_id"], "task_title": hit["task_title"], "phase": "study", "start": st, "end": en,
                  "minutes": minutes, "pinned": True, "locked": locked, "manual": locked}
        extra = minutes - hit["minutes"]  # a longer block takes the time from this task's latest unlocked suggestions
        for s in sorted((s for s in current if s["task_id"] == hit["task_id"] and not s.get("locked")),
                        key=lambda s: s["start"], reverse=True):
            if extra <= 0:
                break
            i = current.index(s)
            if extra >= s["minutes"]:
                current.pop(i)
                extra -= s["minutes"]
            elif s["minutes"] - extra >= p.s_min:  # shorten it, never below the minimum session length
                current[i] = {**s, "minutes": s["minutes"] - extra, "end": s["end"] - timedelta(minutes=extra)}
                extra = 0
            else:
                give = s["minutes"] - p.s_min
                if give > 0:
                    current[i] = {**s, "minutes": p.s_min, "end": s["end"] - timedelta(minutes=give)}
                    extra -= give
    # every other block stays where it is; the planner only places what the change freed up (or still needs)
    pins = [{**s, "pinned": True} for s in current] + ([edited] if edited else [])
    result = planner.plan(tasks_in, cal["busy"], p, cal["t0"], cal["t1"], completed_all_tasks(conn, tz),
                          written + pins, cal["committed"], task_done(conn, tz, cal))
    prev_overrides = base["inputs"].get("overrides", [])
    soft = [v for v in result.violations if v not in prev_overrides]
    unaccepted = [v for v in soft if v not in (body.get("acknowledge") or [])]
    if unaccepted:
        raise AppError(409, "SOFT_RULES", "This change goes past your planning rules; accept it explicitly", unaccepted)
    overrides = [v for v in prev_overrides if v in result.violations] + soft  # drop exceptions for blocks now gone
    removals = {x["event_id"]: x for x in base["inputs"].get("remove_written", []) + ([removal] if removal else [])}
    inputs = {**_base_inputs(base["inputs"]["task_ids"], revisions, rev, prefs_value, p, snap), "overrides": overrides,
              "remove_written": list(removals.values()), "manual": True}
    status = plan_status(result, missing, bool(tasks_in), True, overrides)
    new_id_ = _store_plan(conn, previous_plan_id=plan_id, diff_against=plan_id, snapshot_id=snap["id"], inputs=inputs,
                          result=result, status=status, busy_entries=cal["busy_entries"],
                          binding=result.binding + cal["notes"], missing=missing)
    from .proposal_service import invalidate_for_source
    invalidate_for_source(conn, "plan", plan_id, "edited")
    audit(conn, "plan_block_edited", "plan", new_id_, {"removed": bool(body.get("remove")), "moves_written": bool(removal),
                                                       "accepted_exceptions": len(soft)})
    return get_plan(conn, new_id_)


# ------------------------------------------------------------------ "did you do it?" check-ins

def _block_key(b: dict) -> str:
    return b["event_id"] or f"{b['task_id']}@{b['start'].isoformat()}"


def pending_checkins(conn: sqlite3.Connection, days: int = 7) -> list[dict]:
    """Written study blocks that ended in the last week and have not been answered yet."""
    now = datetime.now(timezone.utc)
    answered = {r[0] for r in conn.execute("SELECT block_key FROM study_checkins")}
    out = []
    for b in written_blocks_all(conn):
        if not (now - timedelta(days=days) < b["end"] <= now) or _block_key(b) in answered:
            continue
        t = conn.execute("SELECT title, status FROM tasks WHERE id=?", (b["task_id"],)).fetchone()
        if not t or t["status"] in ("completed", "ignored"):
            continue
        out.append({"key": _block_key(b), "task_id": b["task_id"], "task_title": t["title"],
                    "start": b["start"].isoformat(), "end": b["end"].isoformat(), "minutes": b["minutes"]})
    return out


def record_checkin(conn: sqlite3.Connection, body: dict) -> dict:
    """done = the block's minutes, partial = the minutes given, missed = nothing logged. Answering twice is a no-op."""
    prev = conn.execute("SELECT * FROM study_checkins WHERE block_key=?", (body["key"],)).fetchone()
    if prev:
        return {"key": prev["block_key"], "outcome": prev["outcome"], "minutes": prev["minutes"],
                "task": get_task(conn, prev["task_id"]), "replayed": True}
    block = next((b for b in written_blocks_all(conn) if _block_key(b) == body["key"]), None)
    if not block:
        raise not_found("study block")
    if block["end"] > datetime.now(timezone.utc):
        raise AppError(409, "BLOCK_NOT_OVER", "This study block has not ended yet")
    outcome = body["outcome"]
    minutes = block["minutes"] if outcome == "done" else int(body.get("minutes") or 0) if outcome == "partial" else 0
    if outcome == "partial" and not 5 <= minutes <= 600:
        raise AppError(422, "VALIDATION_FAILED", "Enter the minutes actually done (5-600)")
    conn.execute("INSERT INTO study_checkins(block_key,task_id,outcome,minutes,planned_minutes,created_at) VALUES(?,?,?,?,?,?)",
                 (body["key"], block["task_id"], outcome, minutes, block["minutes"], now_iso()))
    if minutes > 0:
        from .task_service import record_progress
        cur = get_task(conn, block["task_id"])
        record_progress(conn, block["task_id"], {"expected_revision": cur["revision"], "minutes": minutes,
                                                 "client_event_id": f"checkin:{body['key']}",
                                                 "occurred_at": block["end"].isoformat()})
    audit(conn, "study_checkin", "task", block["task_id"], {"outcome": outcome, "minutes": minutes})
    return {"key": body["key"], "outcome": outcome, "minutes": minutes, "task": get_task(conn, block["task_id"])}


# ------------------------------------------------------------------ demo: a meeting added to the sample timetable

def demo_meetings(conn: sqlite3.Connection) -> list[dict]:
    return [{"id": r["id"], "start": r["start_at"], "end": r["end_at"], "label": r["label"]}
            for r in conn.execute("SELECT id, start_at, end_at, label FROM demo_busy ORDER BY start_at")]


def add_demo_meeting(conn: sqlite3.Connection, body: dict) -> dict:
    st = _aware(body["start"])
    en = st + timedelta(minutes=int(body.get("minutes") or 60))
    mid = new_id("demo")
    conn.execute("INSERT INTO demo_busy(id,start_at,end_at,label,created_at) VALUES(?,?,?,?,?)",
                 (mid, st.isoformat(), en.isoformat(), (body.get("label") or "").strip()[:80], now_iso()))
    audit(conn, "demo_meeting_added", "calendar", mid, {})
    return {"items": demo_meetings(conn)}


def clear_demo_meetings(conn: sqlite3.Connection) -> dict:
    conn.execute("DELETE FROM demo_busy")
    return {"items": []}
