"""Meeting time finder: free times that suit the student and, optionally, the other people.

Inputs are intervals only (no titles), so other people's calendars never need to be stored.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from .models import Interval
from .timeutil import TZ


def _overlaps(a_start: datetime, a_end: datetime, spans: list[Interval]) -> bool:
    return any(a_start < s.end and s.start < a_end for s in spans)


def suggest_slots(
    busy: list[Interval],
    start: date,
    end: date,
    duration_minutes: int,
    now: datetime,
    window: tuple[str, str] = ("09:00", "21:00"),
    step_minutes: int = 30,
    soft_busy: list[Interval] | None = None,
    allowed: list[Interval] | None = None,
    max_results: int = 6,
    per_day: int = 2,
    weekdays_only: bool = False,
) -> list[dict]:
    """Earliest free times of `duration_minutes`, at most `per_day` per day so the options are spread out.

    busy       hard conflicts: classes, exams, meetings, other people's busy times
    soft_busy  planned study blocks: avoided when possible, flagged when used
    allowed    if given, the meeting must fall inside one of these (e.g. everyone's stated free time)
    """
    soft_busy = soft_busy or []
    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=step_minutes)
    w_start, w_end = time.fromisoformat(window[0]), time.fromisoformat(window[1])
    clean: list[dict] = []
    fallback: list[dict] = []
    day = start
    while day <= end and len(clean) < max_results:
        if weekdays_only and day.weekday() >= 5:
            day += timedelta(days=1)
            continue
        t = datetime.combine(day, w_start, TZ)
        stop = datetime.combine(day, w_end, TZ)
        found_today = 0
        fallback_today = 0
        while t + duration <= stop and found_today < per_day:
            e = t + duration
            if t >= now and not _overlaps(t, e, busy) and (allowed is None or any(a.start <= t and e <= a.end for a in allowed)):
                slot = {"start": t.isoformat(), "end": e.isoformat()}
                if _overlaps(t, e, soft_busy):
                    if fallback_today < per_day:
                        fallback.append({**slot, "note": "moves a planned study session"})
                        fallback_today += 1
                else:
                    clean.append(slot)
                    found_today += 1
                    t = e + timedelta(minutes=60)  # leave room between options on the same day
                    continue
            t += step
        day += timedelta(days=1)
    return (clean + fallback)[:max_results]
