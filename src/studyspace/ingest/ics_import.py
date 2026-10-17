"""Timetable import from .ics files (NUSMods export, Outlook / Google calendar export).

A small parser that covers what timetables use: VEVENT with DTSTART/DTEND or DURATION, weekly RRULE with
COUNT / UNTIL / INTERVAL / BYDAY, and EXDATE. Every event becomes a busy TimeSlot. All-day events are skipped
because they mark days (public holidays, recess) rather than hours that are taken.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..models import TimeSlot
from ..timeutil import TZ
from .common import ImportResult

_DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_DURATION = re.compile(r"P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")
MAX_OCCURRENCES = 500


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _split(line: str) -> tuple[str, dict[str, str], str]:
    head, _, value = line.partition(":")
    name, *params = head.split(";")
    return name.upper(), dict(p.split("=", 1) for p in params if "=" in p), value


def _parse_dt(value: str, params: dict[str, str]) -> datetime | date:
    value = value.strip()
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value, "%Y%m%d").date()
    if value.endswith("Z"):
        return datetime.strptime(value[:-1], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc).astimezone(TZ)
    naive = datetime.strptime(value, "%Y%m%dT%H%M%S")
    try:
        zone = ZoneInfo(params["TZID"]) if "TZID" in params else TZ
    except ZoneInfoNotFoundError:
        zone = TZ
    return naive.replace(tzinfo=zone).astimezone(TZ)


def _parse_duration(value: str) -> timedelta:
    m = _DURATION.fullmatch(value.strip().lstrip("+"))
    if not m:
        raise ValueError(f"unsupported DURATION {value!r}")
    w, d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return timedelta(weeks=w, days=d, hours=h, minutes=mi, seconds=s)


def _occurrences(start: datetime, rule: str | None, exdates: set[datetime]) -> list[datetime]:
    if not rule:
        return [] if start in exdates else [start]
    parts = dict(p.split("=", 1) for p in rule.split(";") if "=" in p)
    if parts.get("FREQ") not in ("WEEKLY", "DAILY"):
        return [start]  # unsupported repeat rules fall back to the first occurrence
    interval = int(parts.get("INTERVAL", "1"))
    count = int(parts["COUNT"]) if "COUNT" in parts else None
    until = None
    if "UNTIL" in parts:
        u = _parse_dt(parts["UNTIL"], {})
        until = u if isinstance(u, datetime) else datetime.combine(u, datetime.max.time(), tzinfo=TZ)

    out: list[datetime] = []
    produced = 0
    if parts["FREQ"] == "DAILY":
        step, offsets = timedelta(days=interval), [0]
        anchor = start
    else:
        weekdays = sorted(_DAYS[d[-2:]] for d in parts.get("BYDAY", "").split(",") if d[-2:] in _DAYS) or [start.weekday()]
        step = timedelta(weeks=interval)
        anchor = start - timedelta(days=start.weekday())  # Monday of the first week, same wall-clock time
        offsets = weekdays
    cursor = anchor
    while produced < MAX_OCCURRENCES:
        for offset in offsets:
            occ = cursor + timedelta(days=offset)
            if occ < start:
                continue
            if until and occ > until:
                return out
            if count is not None and produced >= count:
                return out
            produced += 1
            if occ not in exdates:
                out.append(occ)
        if count is None and until is None and produced >= 1:
            # a repeat with no end: keep one semester's worth
            if cursor - anchor > timedelta(weeks=20):
                return out
        cursor += step
    return out


def parse_ics(data: bytes | str) -> ImportResult:
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data
    result = ImportResult()
    event: dict | None = None
    for line in _unfold(text):
        if line.strip() == "BEGIN:VEVENT":
            event = {"exdates": set()}
            continue
        if line.strip() == "END:VEVENT":
            if event is not None:
                _emit(event, result)
            event = None
            continue
        if event is None or ":" not in line:
            continue
        name, params, value = _split(line)
        if name in ("DTSTART", "DTEND"):
            event[name] = _parse_dt(value, params)
        elif name == "DURATION":
            event["DURATION"] = _parse_duration(value)
        elif name == "SUMMARY":
            event["SUMMARY"] = value.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").strip()
        elif name == "RRULE":
            event["RRULE"] = value
        elif name == "EXDATE":
            for v in value.split(","):
                ex = _parse_dt(v, params)
                if isinstance(ex, datetime):
                    event["exdates"].add(ex)
    return result


def _emit(event: dict, result: ImportResult) -> None:
    start = event.get("DTSTART")
    label = event.get("SUMMARY") or "Busy"
    if not isinstance(start, datetime):
        result.skipped.append(f"{label}: all-day or undated event skipped")
        return
    end = event.get("DTEND")
    duration = (end - start) if isinstance(end, datetime) else event.get("DURATION")
    if not duration or duration <= timedelta(0):
        result.skipped.append(f"{label}: no usable end time")
        return
    for occ in _occurrences(start, event.get("RRULE"), event["exdates"]):
        result.slots.append(TimeSlot(start=occ, end=occ + duration, kind="busy", label=label, origin="ics"))
