"""Single-user preferences (planning, UI language, style selection) with one shared revision."""
from __future__ import annotations

import hashlib
import json
import sqlite3

from ..db import audit, dumps, loads, now_iso
from ..errors import AppError, conflict

DEFAULTS = {
    "display_timezone": "Asia/Singapore",
    "day_start": "09:00",
    "day_end": "21:00",
    "daily_cap_minutes": 120,
    "session_min_minutes": 30,
    "session_target_minutes": 60,
    "session_max_minutes": 90,
    "break_minutes": 15,
    "deadline_buffer_minutes": 120,
    "weekly_flex_minutes": 120,
    "allow_model_processing": False,
    "enable_external_writes": False,
    "ui_language": "zh-CN",
    "large_amount_threshold": 200,
    "show_demo_data": None,  # None = automatic: shown until a real mailbox is connected
    "style": {"selected_reference_ids": None, "length_preference": "short"},
}
PLANNING_KEYS = ("display_timezone", "day_start", "day_end", "daily_cap_minutes", "session_min_minutes",
                 "session_target_minutes", "session_max_minutes", "break_minutes", "deadline_buffer_minutes",
                 "weekly_flex_minutes")


def _row(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM preferences WHERE owner_id='local_user'").fetchone()
    if row:
        return row
    conn.execute("INSERT OR IGNORE INTO preferences(owner_id,value_json,revision,updated_at) VALUES('local_user',?,1,?)",
                 (dumps(DEFAULTS), now_iso()))
    return conn.execute("SELECT * FROM preferences WHERE owner_id='local_user'").fetchone()


def get_raw(conn: sqlite3.Connection) -> tuple[dict, int]:
    row = _row(conn)
    value = {**DEFAULTS, **loads(row["value_json"], {})}
    value["style"] = {**DEFAULTS["style"], **(value.get("style") or {})}
    return value, row["revision"]


def real_mailbox_connected(conn: sqlite3.Connection) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM connections WHERE provider IN ('google','microsoft') AND status='connected' "
        "AND scopes_json LIKE '%mail%' LIMIT 1").fetchone()) or bool(conn.execute(
        "SELECT 1 FROM connections WHERE provider='microsoft' AND status='connected' AND scopes_json LIKE '%Mail.Read%'").fetchone())


def show_demo_data(conn: sqlite3.Connection) -> bool:
    value, _ = get_raw(conn)
    if value.get("show_demo_data") is not None:
        return bool(value["show_demo_data"])
    return not real_mailbox_connected(conn)


def view(conn: sqlite3.Connection) -> dict:
    value, rev = get_raw(conn)
    out = {k: value[k] for k in DEFAULTS if k != "style"}
    out["show_demo_data_effective"] = show_demo_data(conn)
    out["revision"] = rev
    out["planning_hash"] = planning_hash(value)
    return out


def planning_hash(value: dict) -> str:
    return hashlib.sha256(json.dumps({k: value[k] for k in PLANNING_KEYS}, sort_keys=True).encode()).hexdigest()[:16]


def _hm(v: str) -> int:
    h, m = v.split(":")
    return int(h) * 60 + int(m)


def validate(value: dict) -> None:
    errs = []
    try:
        start, end = _hm(value["day_start"]), _hm(value["day_end"])
        if not 0 <= start < end <= 24 * 60:
            errs.append("day_start must be before day_end")
        if start < 6 * 60:
            errs.append("day_start before 06:00 is outside the no-early-morning rule")
    except (ValueError, KeyError):
        errs.append("day_start/day_end must be HH:MM")
    mn, tg, mx = value["session_min_minutes"], value["session_target_minutes"], value["session_max_minutes"]
    if not (0 < mn <= tg <= mx):
        errs.append("need 0 < session_min <= session_target <= session_max")
    if value["daily_cap_minutes"] < 0 or value["break_minutes"] < 0:
        errs.append("caps and breaks cannot be negative")
    if errs:
        raise AppError(422, "INVALID_PREFERENCES", "Preferences rejected", errs)


def update(conn: sqlite3.Connection, patch: dict) -> dict:
    value, rev = get_raw(conn)
    if patch.get("expected_revision") != rev:
        raise conflict("REVISION_CONFLICT", "Preferences changed elsewhere; reload", [f"current_revision={rev}"])
    changes = {k: v for k, v in patch.items() if k in DEFAULTS and k != "style"}
    if patch.get("show_demo_data_auto"):
        changes["show_demo_data"] = None
    value.update(changes)
    validate(value)
    conn.execute("UPDATE preferences SET value_json=?, revision=revision+1, updated_at=? WHERE owner_id='local_user'",
                 (dumps(value), now_iso()))
    audit(conn, "preferences_updated", "preferences", "local_user", {"fields": sorted(changes)})
    return view(conn)


def update_style(conn: sqlite3.Connection, expected_revision: int, style_patch: dict) -> tuple[dict, int]:
    value, rev = get_raw(conn)
    if expected_revision != rev:
        raise conflict("REVISION_CONFLICT", "Style profile changed elsewhere; reload", [f"current_revision={rev}"])
    value["style"] = {**value["style"], **style_patch}
    conn.execute("UPDATE preferences SET value_json=?, revision=revision+1, updated_at=? WHERE owner_id='local_user'",
                 (dumps(value), now_iso()))
    return get_raw(conn)
