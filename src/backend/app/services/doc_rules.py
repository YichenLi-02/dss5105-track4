"""Limited local rules for course documents (no model, nothing leaves the machine).

Finds lines that look like deliverables with a date, keeps the exact quote and offsets,
and only resolves relative phrases ("the Friday after reading week") against an academic
calendar document of the *same term*. Anything ambiguous stays a candidate for review.
A time is recorded only when the line states it - never a default 23:59.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
            "mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3, "thurs": 3, "fri": 4, "sat": 5, "sun": 6}
ZH_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

KEYWORDS = re.compile(r"(?i)\b(due|deadline|submit|submission|hand[- ]in|exam|quiz|presentation|test)\b|截止|提交|考试|测验|展示")
ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
MONTH_DAY = re.compile(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b")
DAY_MONTH = re.compile(r"(?i)\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?(?:,?\s+(\d{4}))?\b")
NUMERIC = re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?(?![\d/])")
ZH_DATE = re.compile(r"(?:(\d{4})\s*年\s*)?(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]")
TIME_12 = re.compile(r"(?i)\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)(?![a-z])")
TIME_24 = re.compile(r"(?<![\d:])([01]?\d|2[0-3]):([0-5]\d)(?![\d:])")
NOON = re.compile(r"(?i)\bnoon\b|中午12点")
WEEKDAY_WORD = re.compile(r"(?i)\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues?|wed|thu(?:rs?)?|fri|sat|sun)\b")
ZH_WEEKDAY_WORD = re.compile(r"(?:周|星期)([一二三四五六日天])")
AFTER_READING = re.compile(r"(?i)\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+after\s+(?:the\s+)?(?:recess|reading)\s+week")
ZH_AFTER_READING = re.compile(r"(?:阅读周|reading week)\s*(?:之)?后的?\s*(?:周|星期)([一二三四五六日天])", re.I)
WEEK_N = re.compile(r"(?i)\bweek\s+(\d{1,2})\s*(?:,\s*)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)?")
READING_RANGE = re.compile(r"(?i)(?:reading|recess)\s+week[^\n\d]{0,20}(\d{4}-\d{2}-\d{2})\s*(?:to|–|-|—|至|~)\s*(\d{4}-\d{2}-\d{2})")
WEEK1 = re.compile(r"(?i)week\s*1\s*(?:begins|starts|commences|:)?[^\n\d]{0,12}(\d{4}-\d{2}-\d{2})")


@dataclass
class CalendarFacts:
    document_id: str
    term: str
    reading_week: tuple[date, date] | None = None
    week1_start: date | None = None
    quotes: dict = field(default_factory=dict)


def calendar_facts(document_id: str, term: str, text: str) -> CalendarFacts:
    f = CalendarFacts(document_id, term)
    m = READING_RANGE.search(text)
    if m:
        f.reading_week = (date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2)))
        f.quotes["reading_week"] = (m.group(0), m.start(), m.end())
    m = WEEK1.search(text)
    if m:
        f.week1_start = date.fromisoformat(m.group(1))
        f.quotes["week1"] = (m.group(0), m.start(), m.end())
    return f


def _year_hint(term: str | None) -> int | None:
    m = re.search(r"(20\d{2})", term or "")
    return int(m.group(1)) if m else None


def _safe_date(y: int | None, mo: int, d: int) -> date | None:
    if y is None:
        return None
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _find_time(line: str) -> str | None:
    m = TIME_12.search(line)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        pm = m.group(3).lower().startswith("p")
        if 1 <= h <= 12:
            h = (h % 12) + (12 if pm else 0)
            return f"{h:02d}:{mi:02d}"
    m = TIME_24.search(line)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    if NOON.search(line):
        return "12:00"
    return None


def _lines(text: str):
    pos = 0
    for raw in text.split("\n"):
        yield raw, pos
        pos += len(raw) + 1


def _title(line: str) -> str:
    cut = re.split(r"(?i)\b(?:is|are)?\s*(?:due|deadline)\b|截止|提交", line)[0].strip(" :-–—,.")
    cut = re.sub(r"(?i)^(the|a|an)\s+", "", cut).strip()
    base = cut if len(cut) >= 4 else line.strip()
    return base[:90]


def extract(text: str, *, document_id: str, term: str, timezone: str | None, course: str | None,
            calendars: list[CalendarFacts], page_of) -> list[dict]:
    """Return candidate dicts compatible with task_service.merge_candidates."""
    out: list[dict] = []
    year = _year_hint(term)
    same_term = [c for c in calendars if c.term.strip().lower() == (term or "").strip().lower()]
    other_term = [c for c in calendars if c not in same_term]
    for line, offset in _lines(text):
        stripped = line.strip()
        if not stripped or not KEYWORDS.search(stripped):
            continue
        lead = len(line) - len(line.lstrip())
        start, end = offset + lead, offset + lead + len(stripped)
        date_val, status, notes = None, "candidate_needs_review", []
        explicit = None
        if (m := ISO.search(stripped)):
            explicit = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif (m := MONTH_DAY.search(stripped)):
            explicit = _safe_date(int(m.group(3)) if m.group(3) else year, MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
            if not m.group(3):
                notes.append("year_from_term" if year else "year_missing")
        elif (m := DAY_MONTH.search(stripped)):
            explicit = _safe_date(int(m.group(3)) if m.group(3) else year, MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
            if not m.group(3):
                notes.append("year_from_term" if year else "year_missing")
        elif (m := ZH_DATE.search(stripped)):
            explicit = _safe_date(int(m.group(1)) if m.group(1) else year, int(m.group(2)), int(m.group(3)))
            if not m.group(1):
                notes.append("year_from_term" if year else "year_missing")
        elif (m := NUMERIC.search(stripped)):
            a, b = int(m.group(1)), int(m.group(2))
            y = int(m.group(3)) if m.group(3) else year
            if y and y < 100:
                y += 2000
            if a > 12 and b <= 12:
                explicit = _safe_date(y, b, a)
            elif b > 12 and a <= 12:
                explicit = _safe_date(y, a, b)
            else:
                notes.append("ambiguous_numeric_date_dd_mm_or_mm_dd")
                status = "ambiguous_numeric_date"

        if explicit:
            date_val = explicit.isoformat()
            wd = WEEKDAY_WORD.search(stripped) or None
            zh_wd = ZH_WEEKDAY_WORD.search(stripped)
            stated = WEEKDAYS[wd.group(1).lower()] if wd else (ZH_WEEKDAYS[zh_wd.group(1)] if zh_wd else None)
            if stated is not None and stated != explicit.weekday():
                status = "conflict_weekday_date"
                notes.append(f"weekday_mismatch: {explicit.isoformat()} is {explicit.strftime('%A')}")
        else:
            rel = AFTER_READING.search(stripped)
            zh_rel = ZH_AFTER_READING.search(stripped)
            wk = WEEK_N.search(stripped)
            if rel or zh_rel:
                target = WEEKDAYS[rel.group(1).lower()] if rel else ZH_WEEKDAYS[zh_rel.group(1)]
                cal = next((c for c in same_term if c.reading_week), None)
                if cal:
                    d = cal.reading_week[1] + timedelta(days=1)
                    while d.weekday() != target:
                        d += timedelta(days=1)
                    date_val, status = d.isoformat(), "resolved_from_calendar"
                    notes.append(f"resolved_with_calendar:{cal.document_id} reading_week_end={cal.reading_week[1]}")
                else:
                    status = "relative_semantics_need_confirmation"
                    notes.append("needs_same_term_academic_calendar" + (" (only other terms selected)" if other_term else ""))
            elif wk:
                cal = next((c for c in same_term if c.week1_start), None)
                if cal:
                    target = WEEKDAYS[wk.group(2).lower()] if wk.group(2) else 0
                    d = cal.week1_start + timedelta(weeks=int(wk.group(1)) - 1)
                    d += timedelta(days=(target - d.weekday()) % 7)
                    date_val, status = d.isoformat(), "resolved_from_calendar"
                    notes.append(f"resolved_with_calendar:{cal.document_id} week1={cal.week1_start}")
                else:
                    status = "relative_semantics_need_confirmation"
                    notes.append("needs_same_term_academic_calendar")
            elif status == "candidate_needs_review":
                continue  # keyword without any date expression ("submission time is not stated")
        time_val = _find_time(stripped)
        if time_val is None:
            notes.append("time_not_stated")
        out.append({
            "candidate_id": f"{document_id}:{start}",
            "kind": "document_deadline",
            "title": _title(stripped),
            "official_date_candidate": date_val,
            "official_time_candidate": time_val,
            "timezone": timezone,
            "status": status,
            "interpretation_note": "; ".join(notes),
            "evidence": {"quote": stripped, "start_char": start, "end_char": end, "field": "body"},
            "page": page_of(start),
            "origin": "rule",
            "course": course,
        })
    return out
