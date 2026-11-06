"""Prepare one labelled local test task, then READ BACK its confirmed Google event.

This script never confirms a proposal, sends mail, or creates an external event.
Use the normal planning screen and its final confirmation between prepare/verify.
Credentials stay in the OS credential store; the bootstrap code is never printed.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/backend"))
from app.db import connect, loads  # noqa: E402
from app.providers import net, oauth  # noqa: E402

REPORT = ROOT / "local-data/live-calendar-check.json"
BASE = "http://127.0.0.1:8000"


def require_json(response):
    response.raise_for_status()
    return response.json()


def session():
    client = httpx.Client(base_url=BASE, timeout=45, trust_env=False)
    health = require_json(client.get("/api/health"))
    if health["mode"] != "live" or not health["capabilities"]["external_writes_env_enabled"]:
        raise SystemExit("Real mode is not enabled.")
    codes = re.findall(rb"one-time local session code: ([0-9a-f]+)",
                       (ROOT / "local-data/logs/backend.stdout.log").read_bytes())
    if not codes:
        raise SystemExit("No local live-session code was found.")
    identity = require_json(client.post("/api/session", json={"bootstrap_code": codes[-1].decode("ascii")}))
    client.headers["X-CSRF-Token"] = identity["csrf_token"]
    prefs = require_json(client.get("/api/preferences"))
    if not prefs["enable_external_writes"]:
        raise SystemExit("The user's real-write setting is off.")
    google = next((c for c in require_json(client.get("/api/connections"))["items"]
                   if c["provider"] == "google"), None)
    if not google or google["status"] != "connected" or not google["capabilities"].get("study_calendar"):
        raise SystemExit("A connected Google account with the study-calendar scope is required.")
    with connect() as conn:
        row = conn.execute("SELECT cursor_json FROM connections WHERE id='conn_google'").fetchone()
        calendar_id = loads(row[0], {}).get("app_calendar_id") if row else None
        if not calendar_id:
            raise SystemExit("Create the dedicated study calendar first.")
        token = oauth.access_token(conn, "google")
    auth = {"Authorization": f"Bearer {token}"}
    url = f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}"
    return client, prefs, auth, url


def save(report):
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def prepare():
    if REPORT.exists():
        previous = json.loads(REPORT.read_text(encoding="utf-8"))
        if previous.get("task_id"):
            raise SystemExit("A labelled test task already exists. Reuse local-data/live-calendar-check.json.")
    client, prefs, auth, calendar_url = session()
    with closing(client):
        metadata = net.request("GET", calendar_url, headers=auth)
        if metadata.status_code != 200:
            raise SystemExit(f"Google calendar read failed (HTTP {metadata.status_code}); no test task was created.")
        tz = ZoneInfo(prefs["display_timezone"])
        now = datetime.now(tz)
        start = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        deadline = (start + timedelta(days=3)).date()
        title = f"[LIVE CHECK] Studyspace calendar integration {now.date().isoformat()}"
        task = require_json(client.post("/api/tasks", json={"title": title}))
        task = require_json(client.patch(f"/api/tasks/{task['id']}", json={
            "expected_revision": task["revision"], "official_date": deadline.isoformat(),
            "official_time": "18:00", "source_timezone": prefs["display_timezone"],
            "estimated_minutes": 30, "status": "confirmed"}))
        visible = require_json(client.get("/api/tasks?status=confirmed,in_progress"))["items"]
        assert task["id"] in {t["id"] for t in visible}, "The manual test task is not visible."
        report = {"status": "prepared", "task_id": task["id"], "task_title": title,
                  "planning_start_local": start.strftime("%Y-%m-%dT%H:%M"),
                  "planning_days": 7, "timezone": prefs["display_timezone"],
                  "calendar_title": metadata.json().get("summary"), "minutes": 30,
                  "calendar_read_confirmed": True, "external_event_created": False}
        save(report)
        print(json.dumps(report, ensure_ascii=True, indent=2))


def verify():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    client, _, auth, calendar_url = session()
    with closing(client):
        with connect() as conn:
            rows = conn.execute("SELECT * FROM proposals WHERE source_kind='plan' ORDER BY created_at DESC,rowid DESC").fetchall()
            row = next((r for r in rows if any(ev.get("task_id") == report["task_id"]
                         for ev in loads(r["payload_json"], {}).get("events", []))), None)
        if not row or row["mode"] != "live" or row["status"] != "executed":
            state = row["status"] if row else "no proposal"
            raise SystemExit(f"The normal UI has not completed a real calendar write ({state}).")
        payload, result = loads(row["payload_json"], {}), loads(row["result_json"], {})
        assert len(payload["events"]) == 1 and len(result["events"]) == 1
        entry, event_result = payload["events"][0], result["events"][0]
        assert entry["task_id"] == report["task_id"] and event_result["status"] == "executed"
        response = net.request("GET", f"{calendar_url}/events/{quote(event_result['event_id'], safe='')}", headers=auth)
        if response.status_code != 200:
            raise SystemExit(f"Google event read-back failed (HTTP {response.status_code}).")
        event = response.json()
        assert event["status"] == "confirmed" and event["summary"] == entry["title"]
        assert datetime.fromisoformat(event["start"]["dateTime"]) == datetime.fromisoformat(entry["start"])
        assert datetime.fromisoformat(event["end"]["dateTime"]) == datetime.fromisoformat(entry["end"])
        assert not event.get("attendees"), "Unexpected event attendees."
        listed = net.request("GET", calendar_url + "/events", headers=auth, params={
            "privateExtendedProperty": f"operation_id={result['operation_id']}", "maxResults": 20})
        if listed.status_code != 200:
            raise SystemExit(f"Google event count check failed (HTTP {listed.status_code}).")
        assert len(listed.json().get("items", [])) == 1, "The write did not produce exactly one event."
        report.update({"status": "verified", "external_event_created": True, "proposal_id": row["id"],
                       "mode": row["mode"], "proposal_status": row["status"],
                       "event_id": event["id"], "event_title": event["summary"],
                       "event_start": event["start"]["dateTime"], "event_end": event["end"]["dateTime"],
                       "google_event_status": event["status"], "google_readback_http": response.status_code,
                       "exactly_one_event": True, "attendees": [], "external_email_sent": False,
                       "event_url": event.get("htmlLink")})
        save(report)
        print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "prepare":
        prepare()
    elif action == "verify":
        verify()
    else:
        raise SystemExit("Usage: verify-live-calendar.py prepare|verify")
