"""Rule-based extraction (offline mode). Finds task mentions in one message.

A dated mention needs a reason to be a task: a deadline word or request ("due", "please submit"), an event
word ("exam", "presentation"), or a task noun right before the date ("Assignment 3 ... by Friday").
A mention with no date is kept only when it names a deliverable ("please complete the mock exam"); it gets
MISSING_DUE_AT so the student sees it instead of losing it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from ..llm import clean_text
from ..models import MIDNIGHT_AMBIGUITY, MISSING_DUE_AT, NEEDS_CONFIRM, Source
from ..timeutil import at, now as real_now
from .dates import DateHit, DateResolver, find_times

DELIVERABLE_TRIGGER = re.compile(
    r"\b(due|deadline|submit|submitted|submission|hand in|upload|turn in|fill (?:in|out)|complete|finish|"
    r"no later than|remember to|don'?t forget to|make sure to|need to|have to|must)\b",
    re.I,
)
REQUEST = re.compile(
    r"\b(?:please|pls|kindly|can you|could you|would you|you should|you need to|remember to|make sure to)\s+"
    r"(submit|complete|finish|prepare|read|upload|send|review|fill in|fill out|do|run|draft|write|watch|revise|update|share)\b",
    re.I,
)
EVENT_WORD = re.compile(
    r"\b(exam|midterm|mid-term|test|presentation|present|consultation|meeting|briefing|seminar|lecture|"
    r"tutorial|attendance|be seated|will be held|takes place)\b",
    re.I,
)
TASK_NOUN = (
    r"assignment|problem set|ps\d+|quiz|essay|report|project|proposal|survey|readings?|lab|homework|hw\d*|"
    r"presentation slides|slides|presentation|midterm|mid-term|final exam|mock exam|exam|reflection|draft|"
    r"milestone|deliverable|poster|peer review|mock|case study|worksheet|exercise"
)
DELIVERABLE_NOUN = re.compile(
    r"\b(assignment\w*|problem set|ps\d+|essay|report|proposal|survey|readings?|lab|homework|hw\d*|slides|"
    r"reflection|draft|milestone|deliverable|poster|peer review|mock|case study|worksheet|exercise|quiz)\b",
    re.I,
)
# up to three capitalised words or a week number in front of the noun, and a number after it
NOUN_PHRASE = re.compile(
    rf"(?:(?:Week\s+\d+|CA\s*\d+|Mid-?term|[A-Z][A-Za-z\-]+)\s+){{0,3}}(?i:{TASK_NOUN})\b(?:\s*#?\d+[A-Za-z]?\b)?"
)
LEAD_FILLER = re.compile(r"^(?:(?:Please|Kindly|Reminder|Note|Hi|Dear|The|Your|Our|This|Next|All|Just|And|Also)\s+)+")
VERB_OBJECT = re.compile(
    r"\b(?:please\s+|pls\s+|kindly\s+|can you\s+|could you\s+|remember to\s+|make sure to\s+|need to\s+)"
    r"(submit|complete|finish|prepare|read|upload|send|review|fill in|fill out|draft|write|watch|revise|update|share|run)"
    r"\s+(?P<obj>[^.,;!?\n]{3,60}?)(?=\s+(?:by|before|on|due|no later than|tonight|tomorrow|this|next|ahead|so)\b|[.,;!?\n]|$)",
    re.I,
)
PRONOUN_OBJECT = re.compile(r"(?:it|them|this|that|these|those|your|my|our|their)\b", re.I)
CANVAS_CREATED = re.compile(r"^Assignment created\s*-\s*(?P<t>.+?),\s*[A-Z]{2,4}\d{4}", re.I)
CANVAS_CHANGED = re.compile(r"Assignment due date changed:\s*(?P<t>.+?),\s*[A-Z]{2,4}\d{4}", re.I)
COURSE_TAIL = re.compile(r"\s*(?:[:,\-|]\s*)?\b[A-Z]{2,4}\d{4}[A-Z]?\b.*$")
DUE_TAIL = re.compile(r"\s+(?:submission\s+)?(?:is\s+)?(?:due|deadline)\b.*$", re.I)
WHEN_TAIL = re.compile(
    r"\s+(?:(?:on|this|next|by|is|due)\s+)*(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day|tonight|today|tomorrow|week\b(?!\s*\d)|"
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|(?:jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d)\b.*$",
    re.I,
)
STATUS_TAIL = re.compile(r"\s+(?:is\s+)?(?:now\s+)?(?:released|posted|published|available|out|created|reminder|updated?|extended|changed)$", re.I)
NON_TASK = re.compile(
    r"\b(career fair|newsletter|unsubscribe|webinar|talk series|seminar series|open house|"
    r"timetable (?:is |has been )?(?:released|published)|no action (?:is )?(?:required|needed)|for your information|fyi|"
    r"survey results|grades? (?:are|have been) released|internship opportunit\w*|we are hiring|job opening)\b",
    re.I,
)
SKIP_SENTENCE = re.compile(
    r"\b(week ending|weekly report|signed up to receive|click to view|replies to this email|notification preferences)\b", re.I
)
# preparation that belongs to an exam or class in the same message: "Download the paper beforehand"
PREP_ANCHOR = re.compile(
    r"\b(beforehand|(?:before|prior to|ahead of)\s+(?:you\s+come\s+to\s+|coming\s+to\s+|the\s+start\s+of\s+)?(?:the\s+)?"
    r"(?:exam|midterm|mid-term|test|quiz|lecture|seminar|class|venue|exam venue|presentation)\b)",
    re.I,
)
PREP_ACTION = re.compile(
    r"^(?:please\s+|pls\s+|remember to\s+|make sure (?:to|you)\s+)?(download|bring|write|run|install|print|register|read|"
    r"complete|submit|prepare|charge|check|fill in)\s+(?P<obj>.+?)(?=\s+(?:beforehand|before|prior to|ahead of)\b|[:.;!?]|$)",
    re.I,
)
START_WORD = re.compile(r"\b(start|starts|begin|begins|runs|commence\w*)\b", re.I)
NEAR_DATE = re.compile(r"\b(by|before|on|until|till)\s*$", re.I)
SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])|\n+")


@dataclass
class Mention:
    """One task mention inside one message, before merging."""

    source_id: str
    course_code: str | None
    title: str
    kind: str
    evidence: str
    hit: DateHit | None
    flags: set[str] = field(default_factory=set)
    old_hits: list[DateHit] = field(default_factory=list)
    received_at: datetime | None = None
    from_subject: bool = False
    anchored: bool = False  # due date borrowed from an exam or class in the same message
    options: list[datetime] = field(default_factory=list)  # suggested times the student can pick from

    @property
    def due_date(self) -> date | None:
        return self.hit.day if self.hit else None

    @property
    def due_at(self) -> datetime | None:
        if self.hit and self.hit.day and self.hit.time:
            return at(self.hit.day, self.hit.time)
        return None

    @property
    def due_text(self) -> str | None:
        return self.hit.text if self.hit else None

    @property
    def rank(self) -> tuple:
        """Which of two mentions of the same task says the most: time beats date, explicit beats inferred."""
        if not self.hit:
            return (-1, 0, 0)
        return (self.hit.specificity, 0 if self.hit.inferred else 1, 0 if self.from_subject else 1)


def tidy_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip(" -:,.;\"'")
    title = re.sub(r"^(?:the|a|an|your|our|this|that)\s+", "", title, flags=re.I)
    title = re.sub(r"\s*\[\d+\]$", "", title)
    return title[:1].upper() + title[1:] if title else title


def subject_title(subject: str | None) -> tuple[str | None, bool]:
    """Title taken from a subject line, and whether it is reliable (a Canvas 'Assignment created' line)."""
    if not subject:
        return None, False
    subject = re.sub(r"^(?:(?:re|fw|fwd)\s*:\s*)+", "", subject.strip(), flags=re.I)
    m = CANVAS_CREATED.search(subject)
    raw = m.group("t") if m else COURSE_TAIL.sub("", subject)
    raw = DUE_TAIL.sub("", raw)
    raw = WHEN_TAIL.sub("", raw)
    raw = STATUS_TAIL.sub("", raw)
    title = tidy_title(raw)
    return (title or None), bool(m)


def _short(title: str | None) -> bool:
    return bool(title) and len(title.split()) <= 6 and ":" not in title  # type: ignore[union-attr]


def noun_in(sentence: str, last: bool = False) -> tuple[str | None, int]:
    """The task named in a sentence and where it starts (-1 if none)."""
    m = CANVAS_CHANGED.search(sentence)
    if m:
        return tidy_title(m.group("t")), m.start("t")
    matches = list(NOUN_PHRASE.finditer(sentence))
    if matches:
        m2 = matches[-1] if last else matches[0]
        phrase = LEAD_FILLER.sub("", DUE_TAIL.sub("", m2.group(0)))
        return tidy_title(phrase), m2.start()
    m3 = VERB_OBJECT.search(sentence)
    if m3 and not PRONOUN_OBJECT.match(m3.group("obj")):
        return tidy_title(f"{m3.group(1)} {m3.group('obj')}"), m3.start()
    return None, -1  # "please upload it" / "submit your solutions": the task named earlier


def sentences(text: str) -> list[str]:
    return [s.strip(" \t*•-–") for s in SPLIT.split(text) if s and s.strip(" \t*•-–")]


class RuleExtractor:
    def __init__(self, resolver: DateResolver):
        self.resolver = resolver

    def mentions(self, source: Source, now: datetime | None = None) -> list[Mention]:
        ref = source.received_at or now or real_now()
        body = clean_text(source.body_text)
        subject = source.subject or ""
        all_text = f"{subject}\n{body}"
        strong = bool(re.search(r"\b(due|deadline|submit\w*)\b", all_text, re.I))
        if NON_TASK.search(all_text) and not strong:
            return []

        subj, subj_strong = subject_title(subject)
        start_time = self._start_time(body)
        units = [(s, True) for s in sentences(subject)] + [(s, False) for s in sentences(body)]
        found: list[Mention] = []
        recent: str | None = None

        preps: list[tuple[str, str]] = []
        for text, is_subject in units:
            if SKIP_SENTENCE.search(text):
                continue
            prep = PREP_ACTION.search(text) if not is_subject and PREP_ANCHOR.search(text) else None
            if prep:
                preps.append((tidy_title(f"{prep.group(1)} {prep.group('obj')}"), text))
                continue
            noun, _ = noun_in(text)
            last_noun, last_pos = noun_in(text, last=True)
            hits = self.resolver.find(text, ref)
            due_hits = [h for h in hits if h.role == "due"]
            old_hits = [h for h in hits if h.role == "old"]
            if any(h.day for h in due_hits):
                due_hits = [h for h in due_hits if h.day]  # a real date beats "in Week 9"
            trigger = bool(DELIVERABLE_TRIGGER.search(text) or REQUEST.search(text))
            event = bool(EVENT_WORD.search(text))
            title = self._title(noun, recent, subj, subj_strong)
            if last_noun and 0 <= last_pos < 60:
                recent = self._title(last_noun, None, subj, subj_strong)  # the task this part of the message is about

            if title is None:
                continue
            if not due_hits:
                if not hits and not is_subject and (trigger or REQUEST.search(text)) and DELIVERABLE_NOUN.search(title):
                    found.append(self._mention(source, title, "deliverable", text, None, {MISSING_DUE_AT, NEEDS_CONFIRM}, [], is_subject))
                continue
            hit = max(due_hits, key=lambda h: (h.specificity, -h.start))
            if hit.day is None and not trigger:
                continue  # "in the week 5 lecture" is not a deadline; "due in Week 9" is
            near = bool(NEAR_DATE.search(text[: hit.start]))
            if not (trigger or event or (noun and near)):
                continue
            kind = self._kind(text, title)
            flags = set(hit.flags)
            if kind == "event" and hit.day and hit.time is None and start_time is not None:
                hit.time = start_time  # "The exam will start at 7pm" elsewhere in the message
                if not hit.inferred:
                    flags.discard(NEEDS_CONFIRM)
            found.append(self._mention(source, title, kind, text, hit, flags, old_hits, is_subject))
        found = self._merge_within(found, subj)
        events = sorted((m for m in found if m.kind == "event" and m.hit and m.hit.day), key=lambda m: m.rank, reverse=True)
        if events:
            anchor = events[0].hit
            for title, text in preps:
                # "before the exam": the day is known, the exact time is the student's call (the exam start is offered)
                hit = DateHit(text=f"before {events[0].title}: {anchor.text}", start=0, end=0, day=anchor.day,
                              time=None, flags={NEEDS_CONFIRM}, inferred=True)
                m = self._mention(source, title, "deliverable", text, hit, {NEEDS_CONFIRM}, [], False)
                m.anchored = True
                m.options = [at(anchor.day, anchor.time)] if anchor.time else []
                found.append(m)
        return found

    # -- helpers --------------------------------------------------------------------------------
    @staticmethod
    def _title(noun: str | None, recent: str | None, subj: str | None, subj_strong: bool) -> str | None:
        if subj and subj_strong:
            return subj
        if noun and subj and noun.lower() in subj.lower() and _short(subj):
            return subj  # "survey" in the text, "Week 6 Learning Survey" in the subject
        if noun:
            return noun
        if recent:
            return recent
        return subj if subj and len(subj) <= 80 else None

    @staticmethod
    def _kind(text: str, title: str) -> str:
        if DELIVERABLE_NOUN.search(title):
            return "deliverable"
        if EVENT_WORD.search(title) or EVENT_WORD.search(text):
            if re.search(r"\b(due|deadline|submit\w*|submission|upload)\b", text, re.I):
                return "deliverable"
            return "event"
        return "deliverable"

    @staticmethod
    def _start_time(body: str):
        """Start time of an exam or event stated in its own sentence ("The exam will start at 7pm")."""
        for s in sentences(body):
            m = START_WORD.search(s)
            if m and EVENT_WORD.search(s):
                times = [t for t in find_times(s) if t.value and t.start >= m.start()]
                if times:
                    return times[0].value
        return None

    @staticmethod
    def _mention(source, title, kind, text, hit, flags, old_hits, is_subject) -> Mention:
        return Mention(
            source_id=source.record_id,
            course_code=source.course_code,
            title=title,
            kind=kind,
            evidence=re.sub(r"\s+", " ", text).strip()[:300],
            hit=hit,
            flags=set(flags),
            old_hits=list(old_hits),
            received_at=source.received_at,
            from_subject=is_subject,
        )

    @staticmethod
    def _merge_within(found: list[Mention], subj: str | None) -> list[Mention]:
        """One message often states the same deadline twice (subject and body). Keep one mention per task."""
        from .merge import similar_titles

        def same(a: Mention, b: Mention) -> bool:
            if a.anchored or b.anchored:
                return a.anchored == b.anchored and similar_titles(a.title, b.title)
            if a.due_date and b.due_date and a.due_date != b.due_date:
                return False
            if similar_titles(a.title, b.title):
                return True
            if a.due_date and a.due_date == b.due_date:
                return a.from_subject or b.from_subject or subj in (a.title, b.title)
            return False

        out: list[Mention] = []
        for m in found:
            twin = next((o for o in out if same(o, m)), None)
            if twin is None:
                out.append(m)
                continue
            best, other = (m, twin) if m.rank > twin.rank else (twin, m)
            if best.hit is not None:
                best.flags -= {MISSING_DUE_AT}
                best.flags |= other.flags & {MIDNIGHT_AMBIGUITY}
            best.old_hits.extend(other.old_hits)
            if best.from_subject and not other.from_subject:
                best.evidence = other.evidence  # the body sentence is better evidence than the subject line
            out[out.index(twin)] = best
        return out
