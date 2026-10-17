"""Find deadline dates and times in a sentence and turn them into calendar values.

Handles explicit dates ("29 Aug at 23:59", "Wednesday, 23 September 2026, 11:59 PM", "Sept 28"),
relative dates ("tonight", "tomorrow", "this Friday", "next Monday", "by Thursday"), and academic weeks
("Friday of Week 9", "the Monday after recess week"). Rules that keep uncertain values visible:
- a relative or week-based date is flagged NEEDS_CONFIRM, so is a date with no time
- "midnight" / "12am" is flagged MIDNIGHT_AMBIGUITY and its time is left empty
- "in Week 9" with no weekday gives no day at all, only the text; nothing is filled in by default
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from ..academic_calendar import AcademicCalendar
from ..models import MIDNIGHT_AMBIGUITY, NEEDS_CONFIRM
from ..timeutil import local

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3, "apr": 4, "april": 4, "may": 5,
    "jun": 6, "june": 6, "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
WEEKDAY_NUM = {
    "mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "wednesday": 2, "thu": 3, "thur": 3,
    "thurs": 3, "thursday": 3, "fri": 4, "friday": 4, "sat": 5, "saturday": 5, "sun": 6, "sunday": 6,
}

_MON = r"(?P<m>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
_WD_ANY = r"(?P<wd>mon(?:day)?|tue(?:s(?:day)?)?|wed(?:nesday)?|thu(?:r(?:s(?:day)?)?)?|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
_WD_FULL = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
_ORD = r"(?:st|nd|rd|th)?"

DAY_MONTH = re.compile(rf"\b(?:{_WD_ANY}\.?,?\s+)?(?:the\s+)?(?P<d>\d{{1,2}}){_ORD}\s+(?:of\s+)?{_MON}\b\.?(?:,?\s+(?P<y>20\d\d))?", re.I)
MONTH_DAY = re.compile(rf"\b(?:{_WD_ANY}\.?,?\s+)?{_MON}\.?\s+(?P<d>\d{{1,2}}){_ORD}\b(?:,?\s+(?P<y>20\d\d))?", re.I)
ISO_DATE = re.compile(r"\b(?P<y>20\d\d)-(?P<m>\d{2})-(?P<d>\d{2})(?:[T ](?P<h>\d{2}):(?P<mi>\d{2}))?\b")
NUMERIC = re.compile(r"(?<![\d/])(?P<a>\d{1,2})/(?P<b>\d{1,2})(?:/(?P<y>(?:20)?\d\d))?(?![\d/])")

WEEKDAY_OF_WEEK = re.compile(rf"\b(?:on\s+)?(?:the\s+)?{_WD_FULL}\s+(?:of|in)\s+week\s*(\d{{1,2}})\b", re.I)
WEEK_WEEKDAY = re.compile(rf"\bweek\s*(\d{{1,2}})\s*,?\s+{_WD_FULL}\b", re.I)
AFTER_PERIOD = re.compile(rf"\b(?:the\s+)?{_WD_FULL}\s+after\s+(?:the\s+)?(recess|reading)(?:\s+week)?\b", re.I)
BARE_WEEK = re.compile(r"\b(?:in|by|during|before|end of|due)\s+(?:the\s+)?(?:end\s+of\s+)?week\s*(\d{1,2})\b", re.I)

RELATIVE_DAY = re.compile(r"\b(today|tonight|this evening|this afternoon|tomorrow(?:\s+(?:morning|night|evening))?|tmr)\b", re.I)
RELATIVE_WD = re.compile(rf"\b(this|next|coming|by|on|before|until|due)?\s*(?:the\s+)?{_WD_FULL}\b(\s+(?:night|evening|morning|afternoon))?", re.I)
IN_N_DAYS = re.compile(r"\bin\s+(\d+|one|two|three|four|five|six|seven)\s+(day|week)s?\b", re.I)
_NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}

TIME_AMPM = re.compile(r"\b(?P<h>\d{1,2})(?:[:.](?P<mi>[0-5]\d))?\s*(?P<ap>a\.?m\.?|p\.?m\.?)(?![a-z])", re.I)
TIME_24H = re.compile(r"\b(?P<h>[01]?\d|2[0-3])[:.](?P<mi>[0-5]\d)\b(?!\s*(?:a\.?m|p\.?m))", re.I)
TIME_HRS = re.compile(r"\b(?P<h>[01]\d|2[0-3])(?P<mi>[0-5]\d)\s*(?:h|hrs?|hours)\b", re.I)
TIME_COMPACT = re.compile(r"(?:(?<=\bat )|(?<=\bby ))(?P<h>[01]\d|2[0-3])(?P<mi>[0-5]\d)\b|\b(?P<h2>23)(?P<mi2>59)\b")
TIME_WORD = re.compile(r"\b(?:(?P<twelve>12\s*)?(?P<word>midnight|noon|midday))\b", re.I)

CHANGE_VERBS = re.compile(r"\b(extend\w*|postpon\w*|mov(?:e|ed|ing)|chang\w*|push\w*|shift\w*|reschedul\w*|brought forward|delay\w*)\b", re.I)
_OLD_MARK = re.compile(r"(?:\bfrom|\bwas|\binstead of|\boriginally|\bpreviously)\s*(?:the\s+)?$", re.I)
_NEW_MARK = re.compile(r"\b(?:to|until|till|now)\s*(?:the\s+)?$", re.I)
# "available from 6:00 AM on ..." / "opens on ..." : the date says when something starts, not a deadline
_START_MARK = re.compile(r"\b(?:available|opens?|released?|starting|from)\b(?:(?!\b(?:due|deadline|by|submit|until)\b)[^.;]){0,25}$", re.I)


@dataclass
class TimeToken:
    start: int
    end: int
    value: time | None
    flags: set[str] = field(default_factory=set)


@dataclass
class DateHit:
    text: str
    start: int
    end: int
    day: date | None
    time: time | None = None
    flags: set[str] = field(default_factory=set)
    role: str = "due"            # due | old (the date a change replaces) | start (when something opens)
    inferred: bool = False       # relative or week-based

    @property
    def specificity(self) -> int:
        return (2 if self.time else 0) + (1 if self.day else 0)


def _infer_year(month: int, day: int, ref: date) -> date | None:
    """A date without a year is taken as the occurrence closest to the message date."""
    best = None
    for year in (ref.year - 1, ref.year, ref.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if best is None or abs((d - ref).days) < abs((best - ref).days):
            best = d
    return best


def find_times(text: str) -> list[TimeToken]:
    tokens: list[TimeToken] = []
    taken: list[tuple[int, int]] = []

    def free(a: int, b: int) -> bool:
        return all(b <= s or a >= e for s, e in taken)

    for m in TIME_WORD.finditer(text):
        word = m.group("word").lower()
        if word == "midnight":
            tokens.append(TimeToken(m.start(), m.end(), None, {MIDNIGHT_AMBIGUITY}))
        else:
            tokens.append(TimeToken(m.start(), m.end(), time(12, 0)))
        taken.append((m.start(), m.end()))
    for m in TIME_AMPM.finditer(text):
        if not free(m.start(), m.end()):
            continue
        h, mi = int(m.group("h")), int(m.group("mi") or 0)
        if not 1 <= h <= 12:
            continue
        pm = m.group("ap").lower().startswith("p")
        if h == 12 and not pm and mi == 0:
            tokens.append(TimeToken(m.start(), m.end(), None, {MIDNIGHT_AMBIGUITY}))
        else:
            hour = (h % 12) + (12 if pm else 0)
            tokens.append(TimeToken(m.start(), m.end(), time(hour, mi)))
        taken.append((m.start(), m.end()))
    for pattern in (TIME_24H, TIME_HRS, TIME_COMPACT):
        for m in pattern.finditer(text):
            if not free(m.start(), m.end()):
                continue
            groups = m.groupdict()
            h, mi = int(groups.get("h") or groups["h2"]), int(groups.get("mi") or groups["mi2"])
            if h == 0 and mi == 0:
                tokens.append(TimeToken(m.start(), m.end(), None, {MIDNIGHT_AMBIGUITY}))
            else:
                tokens.append(TimeToken(m.start(), m.end(), time(h, mi)))
            taken.append((m.start(), m.end()))
    return sorted(tokens, key=lambda t: t.start)


class DateResolver:
    def __init__(self, calendar: AcademicCalendar | None = None):
        self.calendar = calendar

    # -- public ---------------------------------------------------------------------------------
    def find(self, sentence: str, ref: datetime) -> list[DateHit]:
        """All date mentions in one sentence, each paired with the nearest time and given a role."""
        ref_day = local(ref).date()
        hits: list[DateHit] = []
        masked = sentence

        def take(hit: DateHit) -> None:
            nonlocal masked
            hits.append(hit)
            masked = masked[: hit.start] + " " * (hit.end - hit.start) + masked[hit.end :]

        for hit in self._explicit(sentence, ref_day):
            take(hit)
        for hit in self._academic(masked, sentence):
            take(hit)
        for hit in self._relative(masked, sentence, ref_day):
            take(hit)

        hits.sort(key=lambda h: h.start)
        self._attach_times(sentence, hits)
        self._assign_roles(sentence, hits)
        for h in hits:
            if h.inferred or (h.day and not h.time and MIDNIGHT_AMBIGUITY not in h.flags) or not h.day:
                h.flags.add(NEEDS_CONFIRM)
        return hits

    def first(self, phrase: str, ref: datetime) -> DateHit | None:
        hits = [h for h in self.find(phrase, ref) if h.role == "due"]
        return hits[0] if hits else None

    # -- explicit calendar dates ----------------------------------------------------------------
    def _explicit(self, s: str, ref: date) -> list[DateHit]:
        out: list[DateHit] = []
        spans: list[tuple[int, int]] = []

        def overlaps(a: int, b: int) -> bool:
            return any(not (b <= x or a >= y) for x, y in spans)

        for m in ISO_DATE.finditer(s):
            try:
                d = date(int(m["y"]), int(m["m"]), int(m["d"]))
            except ValueError:
                continue
            t = time(int(m["h"]), int(m["mi"])) if m["h"] else None
            out.append(DateHit(m.group(0), m.start(), m.end(), d, t))
            spans.append((m.start(), m.end()))

        for pattern in (DAY_MONTH, MONTH_DAY):
            for m in pattern.finditer(s):
                if overlaps(m.start(), m.end()):
                    continue
                if m["m"] == "may":
                    continue  # the verb "may", not the month
                month, day = MONTHS[m["m"].lower().rstrip(".")], int(m["d"])
                if m["y"]:
                    try:
                        d = date(int(m["y"]), month, day)
                    except ValueError:
                        continue
                else:
                    d = _infer_year(month, day, ref)
                    if d is None:
                        continue
                hit = DateHit(m.group(0).strip(), m.start(), m.end(), d)
                if m["wd"] and WEEKDAY_NUM[m["wd"].lower()] != d.weekday():
                    hit.flags.add(NEEDS_CONFIRM)  # weekday and date disagree
                out.append(hit)
                spans.append((m.start(), m.end()))

        for m in NUMERIC.finditer(s):
            if overlaps(m.start(), m.end()):
                continue
            a, b = int(m["a"]), int(m["b"])
            day, month = (a, b) if a > 12 or b <= 12 else (b, a)  # Singapore writes day/month
            if not (1 <= month <= 12 and 1 <= day <= 31):
                continue
            try:
                if m["y"]:
                    y = int(m["y"])
                    d = date(y + 2000 if y < 100 else y, month, day)
                else:
                    d = _infer_year(month, day, ref)
            except ValueError:
                continue
            if d is None:
                continue
            hit = DateHit(m.group(0), m.start(), m.end(), d)
            if a <= 12 and b <= 12 and a != b:
                hit.flags.add(NEEDS_CONFIRM)  # 3/10 could be 3 Oct or 10 Mar
            out.append(hit)
            spans.append((m.start(), m.end()))
        return out

    # -- academic weeks -------------------------------------------------------------------------
    def _academic(self, masked: str, original: str) -> list[DateHit]:
        out: list[DateHit] = []
        cal = self.calendar
        for m in WEEKDAY_OF_WEEK.finditer(masked):
            d = cal.weekday_in_week(int(m.group(2)), WEEKDAY_NUM[m.group(1).lower()]) if cal else None
            out.append(DateHit(original[m.start() : m.end()], m.start(), m.end(), d, inferred=True))
        for m in WEEK_WEEKDAY.finditer(masked):
            d = cal.weekday_in_week(int(m.group(1)), WEEKDAY_NUM[m.group(2).lower()]) if cal else None
            out.append(DateHit(original[m.start() : m.end()], m.start(), m.end(), d, inferred=True))
        for m in AFTER_PERIOD.finditer(masked):
            d = cal.weekday_after(m.group(2).lower(), WEEKDAY_NUM[m.group(1).lower()]) if cal else None
            out.append(DateHit(original[m.start() : m.end()], m.start(), m.end(), d, inferred=True))
        taken = [(h.start, h.end) for h in out]
        for m in BARE_WEEK.finditer(masked):
            if any(not (m.end() <= a or m.start() >= b) for a, b in taken):
                continue
            out.append(DateHit(original[m.start() : m.end()], m.start(), m.end(), None, inferred=True))
        return out

    # -- relative dates -------------------------------------------------------------------------
    def _relative(self, masked: str, original: str, ref: date) -> list[DateHit]:
        out: list[DateHit] = []
        for m in RELATIVE_DAY.finditer(masked):
            word = m.group(1).lower()
            d = ref + timedelta(days=1) if word.startswith(("tomorrow", "tmr")) else ref
            out.append(DateHit(original[m.start() : m.end()], m.start(), m.end(), d, inferred=True))
        taken = [(h.start, h.end) for h in out]
        for m in IN_N_DAYS.finditer(masked):
            n = m.group(1).lower()
            n_val = int(n) if n.isdigit() else _NUM_WORDS[n]
            days = n_val * (7 if m.group(2).lower() == "week" else 1)
            out.append(DateHit(original[m.start() : m.end()], m.start(), m.end(), ref + timedelta(days=days), inferred=True))
            taken.append((m.start(), m.end()))
        for m in RELATIVE_WD.finditer(masked):
            if any(not (m.end() <= a or m.start() >= b) for a, b in taken):
                continue
            mod = (m.group(1) or "").lower()
            target = WEEKDAY_NUM[m.group(2).lower()]
            if mod == "next":
                monday_next = ref - timedelta(days=ref.weekday()) + timedelta(weeks=1)
                d = monday_next + timedelta(days=target)
            else:
                d = ref + timedelta(days=(target - ref.weekday()) % 7)
            start = m.start() + (len(m.group(0)) - len(m.group(0).lstrip()))
            out.append(DateHit(original[start : m.end()].strip(), start, m.end(), d, inferred=True))
        return out

    # -- time pairing and roles -----------------------------------------------------------------
    @staticmethod
    def _attach_times(s: str, hits: list[DateHit]) -> None:
        if not hits:
            return
        tokens = [t for t in find_times(s) if not any(h.start <= t.start < h.end for h in hits if h.time)]
        used: set[int] = set()
        for h in hits:
            if h.time is not None:
                continue
            best, best_gap = None, None
            for i, t in enumerate(tokens):
                if i in used:
                    continue
                if t.start >= h.end:
                    lo, hi, limit = h.end, t.start, 45   # time after the date: "29 Aug at 23:59"
                elif t.end <= h.start:
                    lo, hi, limit = t.end, h.start, 25   # time before the date: "12 midnight Sept 28"
                else:
                    continue
                gap = hi - lo
                if gap > limit or re.search(r"[;\n]", s[lo:hi]):
                    continue
                if any(o is not h and o.start >= lo and o.end <= hi for o in hits):
                    continue  # another date sits between them and owns this time
                if best_gap is None or gap < best_gap:
                    best, best_gap = i, gap
            if best is not None:
                used.add(best)
                tok = tokens[best]
                h.time = tok.value
                h.flags |= tok.flags
                h.start, h.end = min(h.start, tok.start), max(h.end, tok.end)
                h.text = s[h.start : h.end].strip()
        for h in hits:
            h.text = h.text.rstrip(" .,")

    @staticmethod
    def _assign_roles(s: str, hits: list[DateHit]) -> None:
        changes = bool(CHANGE_VERBS.search(s))
        for h in hits:
            before = s[max(0, h.start - 40) : h.start]
            if changes and _OLD_MARK.search(before):
                h.role = "old"
            elif changes and _NEW_MARK.search(before):
                h.role = "due"
            elif _START_MARK.search(before):
                h.role = "start"
