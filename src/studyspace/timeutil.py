"""Time helpers. Every stored time carries an offset; the student's time zone is Asia/Singapore."""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from .config import DEFAULT_TIMEZONE

TZ = ZoneInfo(DEFAULT_TIMEZONE)


def now() -> datetime:
    return datetime.now(TZ)


def require_aware(value: datetime, field: str = "time") -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must include a UTC offset, e.g. 2026-09-30T23:59:00+08:00")
    return value


def local(value: datetime) -> datetime:
    """Convert an aware datetime to Singapore time."""
    return require_aware(value).astimezone(TZ)


def at(day: date, hhmm: str | time) -> datetime:
    """Combine a calendar day with a local wall-clock time in Singapore."""
    t = hhmm if isinstance(hhmm, time) else time.fromisoformat(hhmm)
    return datetime.combine(day, t, tzinfo=TZ)


def iso(value: datetime) -> str:
    return local(value).isoformat(timespec="seconds")
