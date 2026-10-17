"""Academic calendar lookups, used to resolve phrases such as "Friday of Week 9"."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


@dataclass(frozen=True)
class Period:
    label: str
    start: date  # inclusive
    end: date    # inclusive
    week: int | None = None
    key: str | None = None


class AcademicCalendar:
    def __init__(self, name: str, periods: list[Period]):
        self.name = name
        self.periods = sorted(periods, key=lambda p: p.start)

    @classmethod
    def load(cls, path: str | Path) -> "AcademicCalendar":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        periods = [
            Period(
                label=p["label"],
                start=date.fromisoformat(p["start"]),
                end=date.fromisoformat(p["end"]),
                week=p.get("week"),
                key=p.get("key"),
            )
            for p in raw["periods"]
        ]
        return cls(raw.get("name", ""), periods)

    def period_of(self, day: date) -> Period | None:
        return next((p for p in self.periods if p.start <= day <= p.end), None)

    def week(self, number: int) -> Period | None:
        return next((p for p in self.periods if p.week == number), None)

    def named(self, key: str) -> Period | None:
        return next((p for p in self.periods if p.key == key), None)

    def weekday_in_week(self, number: int, weekday: int) -> date | None:
        """The given weekday (0 = Monday) of teaching week `number`."""
        period = self.week(number)
        if period is None:
            return None
        monday = period.start - timedelta(days=period.start.weekday())
        return monday + timedelta(days=weekday)

    def weekday_after(self, key: str, weekday: int) -> date | None:
        """The first given weekday after a named period ends, e.g. the Monday after recess week."""
        period = self.named(key)
        if period is None:
            return None
        day = period.end + timedelta(days=1)
        while day.weekday() != weekday:
            day += timedelta(days=1)
        return day
