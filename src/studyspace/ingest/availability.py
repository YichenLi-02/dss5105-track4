"""Free-time input: either explicit slots or a weekly template expanded over a date range.

{
  "from": "2026-10-12", "to": "2026-11-13",
  "weekly": [{"weekday": "monday", "start": "14:00", "end": "18:00"}],
  "slots":  [{"start": "2026-10-17T10:00:00+08:00", "end": "2026-10-17T12:00:00+08:00", "label": "Saturday"}],
  "exclude_dates": ["2026-10-20"]
}
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from ..academic_calendar import WEEKDAYS
from ..models import TimeSlot
from ..timeutil import at, require_aware
from .common import ImportResult


def expand_template(template: dict, kind: str = "available", origin: str = "manual") -> list[TimeSlot]:
    slots: list[TimeSlot] = []
    for s in template.get("slots", []):
        slots.append(
            TimeSlot(
                start=require_aware(datetime.fromisoformat(s["start"]), "start"),
                end=require_aware(datetime.fromisoformat(s["end"]), "end"),
                kind=s.get("kind", kind),
                label=s.get("label"),
                origin=origin,  # type: ignore[arg-type]
            )
        )
    weekly = template.get("weekly", [])
    if weekly:
        first, last = date.fromisoformat(template["from"]), date.fromisoformat(template["to"])
        excluded = {date.fromisoformat(d) for d in template.get("exclude_dates", [])}
        day = first
        while day <= last:
            if day not in excluded:
                for w in weekly:
                    if WEEKDAYS.index(w["weekday"].lower()) == day.weekday():
                        slots.append(
                            TimeSlot(
                                start=at(day, w["start"]),
                                end=at(day, w["end"]),
                                kind=w.get("kind", kind),
                                label=w.get("label"),
                                origin=origin,  # type: ignore[arg-type]
                            )
                        )
            day += timedelta(days=1)
    return sorted(slots, key=lambda s: s.start)


def parse_availability_json(data: bytes | str, origin: str = "manual") -> ImportResult:
    raw = json.loads(data.decode("utf-8") if isinstance(data, bytes) else data)
    return ImportResult(slots=expand_template(raw, origin=origin))
