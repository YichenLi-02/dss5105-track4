"""Inbox triage: what each message asks of the student.

Labels (a message can have several):
- task        extraction found at least one task in it
- reply       someone is waiting for an answer from the student
- event       it announces an exam, meeting or class change with a time
- info        worth knowing, nothing to do
- newsletter  bulk mail: newsletters, digests, careers mailers
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from email.utils import parseaddr

from .llm import clean_text
from .models import Candidate, Source

ASKS_REPLY = re.compile(
    r"\b(let me know|could you|can you|would you|are you (?:free|available)|your availability|please (?:reply|confirm|respond|rsvp)|"
    r"rsvp|get back to me|what do you think|does that work|is that ok|any thoughts)\b|\?\s*$",
    re.I | re.M,
)
BULK = re.compile(r"\b(newsletter|unsubscribe|digest|weekly report|notification preferences|mailing list|career fair|"
                  r"we are hiring|webinar)\b", re.I)
NO_REPLY_SENDER = re.compile(r"(no-?reply|notifications?|digest|newsletter|careers|registrar|library|announce)", re.I)
STAFF_HINT = re.compile(r"\b(prof\.?|professor|dr\.?|lecturer|ta|tutor|instructor|teaching assistant|department|office)\b", re.I)


@dataclass
class TriageItem:
    record_id: str
    labels: list[str] = field(default_factory=list)
    primary: str = "info"
    reasons: list[str] = field(default_factory=list)
    candidate_ids: list[str] = field(default_factory=list)
    sender_kind: str = "unknown"  # staff | peer | external | system | unknown
    urgent: bool = False


def sender_kind(sender: str | None, student_domain: str | None = None) -> str:
    display, address = parseaddr(sender or "")
    if not address:
        return "unknown"
    if NO_REPLY_SENDER.search(address) or NO_REPLY_SENDER.search(display):
        return "system"
    if STAFF_HINT.search(sender or ""):  # "Daniel Koh (TA) <...>": the comment is not part of the parsed name
        return "staff"
    domain = address.rsplit("@", 1)[-1].lower()
    if student_domain and not domain.endswith(student_domain):
        return "external"
    return "peer"


def triage(sources: list[Source], candidates: list[Candidate], student_domain: str | None = None, now=None) -> list[TriageItem]:
    by_source: dict[str, list[Candidate]] = {}
    for c in candidates:
        for sid in c.source_ids:
            by_source.setdefault(sid, []).append(c)

    items = []
    for s in sources:
        item = TriageItem(record_id=s.record_id, sender_kind=sender_kind(s.sender, student_domain))
        text = f"{s.subject or ''}\n{s.body_text}"
        mine = [c for c in by_source.get(s.record_id, []) if c.status != "dismissed"]
        if mine:
            item.labels.append("task")
            item.candidate_ids = [c.candidate_id for c in mine]
            item.reasons.append(f"{len(mine)} task(s) found")
            if any(c.kind == "event" for c in mine):
                item.labels.append("event")
        if BULK.search(text) or (item.sender_kind == "system" and not mine):
            item.labels.append("newsletter")
            item.reasons.append("bulk or automated mail")
        elif item.sender_kind != "system" and ASKS_REPLY.search(clean_text(s.body_text)):  # new text only, not quotes
            item.labels.append("reply")
            item.reasons.append("the sender asks you something")
        if not item.labels:
            item.labels.append("info")
        item.primary = next(label for label in ("reply", "task", "event", "info", "newsletter") if label in item.labels)
        if now is not None:
            soon = [c for c in mine if c.due_date and 0 <= (c.due_date - now.date()).days <= 2]
            item.urgent = bool(soon)
        items.append(item)
    return items

