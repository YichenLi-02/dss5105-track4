"""Read-only busy times. A failed or partial read is reported as such, never as free time."""
from __future__ import annotations

import sqlite3
from datetime import datetime

from ..errors import AppError
from . import net, oauth


def read_busy(conn: sqlite3.Connection, provider: str, connection_id: str | None, t0: datetime, t1: datetime,
              tz_name: str, calendar_ids: list[str]) -> dict:
    if provider not in ("google", "microsoft"):
        raise AppError(422, "UNKNOWN_PROVIDER", "provider must be mock, google or microsoft")
    if not oauth.has_scope(conn, provider, "read_busy"):
        return {"busy": [], "errors": [f"{provider}: not connected with read_busy permission"], "status": "failed",
                "version": "unavailable"}
    try:
        token = oauth.access_token(conn, provider)
    except AppError as e:
        return {"busy": [], "errors": [e.code], "status": "failed", "version": "unavailable"}
    busy, errors = [], []
    if provider == "google":
        r = net.request("POST", "https://www.googleapis.com/calendar/v3/freeBusy",
                        headers={"Authorization": f"Bearer {token}"},
                        json={"timeMin": t0.isoformat(), "timeMax": t1.isoformat(), "timeZone": tz_name,
                              "items": [{"id": c} for c in calendar_ids]})
        if r.status_code != 200:
            return {"busy": [], "errors": [f"freeBusy http {r.status_code}"], "status": "failed", "version": "unavailable"}
        for cal_id, cal in r.json().get("calendars", {}).items():
            if cal.get("errors"):
                errors += [f"{cal_id}: {e.get('reason')}" for e in cal["errors"]]
            for b in cal.get("busy", []):
                busy.append({"start": b["start"], "end": b["end"], "kind": "busy", "source_id": f"google:{cal_id}"})
        version = f"google:{datetime.now().isoformat(timespec='seconds')}"
    else:
        url = (f"https://graph.microsoft.com/v1.0/me/calendarView?startDateTime={t0.isoformat()}&endDateTime={t1.isoformat()}"
               "&$select=id,start,end,showAs,isCancelled&$top=100")
        while url:
            r = net.request("GET", url, headers={"Authorization": f"Bearer {token}", "Prefer": 'outlook.timezone="UTC"'})
            if r.status_code != 200:
                errors.append(f"calendarView http {r.status_code}")
                break
            data = r.json()
            for ev in data.get("value", []):
                if ev.get("isCancelled") or ev.get("showAs") == "free":
                    continue  # tentative and other states are kept as busy (conservative)
                busy.append({"start": ev["start"]["dateTime"][:19] + "+00:00", "end": ev["end"]["dateTime"][:19] + "+00:00",
                             "kind": "busy", "source_id": "microsoft:calendarView"})
            nxt = data.get("@odata.nextLink")
            url = nxt if nxt and nxt.startswith("https://graph.microsoft.com/") else None
        version = f"microsoft:{datetime.now().isoformat(timespec='seconds')}"
    status = "complete" if not errors else ("partial" if busy else "failed")
    return {"busy": busy, "errors": errors, "status": status, "version": version}
