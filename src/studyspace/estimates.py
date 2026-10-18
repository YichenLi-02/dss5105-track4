"""Suggested effort for a new task, so confirming is one click instead of typing a number.

A suggestion is only a starting value shown as "suggested"; the student still confirms or changes it (gate 1).
It comes from the student's own past estimates for similar tasks when there are any, otherwise from the kind of
work the title names.
"""

from __future__ import annotations

import re

from .extraction.merge import similar_titles
from .models import Candidate, Task

# (pattern in the title, minutes), first match wins; ordered from specific to general
TYPICAL = [
    (r"\b(download|bring|write your|fill in|form|survey|register|sign up)\b", 15),
    (r"\bquiz\b", 60),
    (r"\b(mock|practice) exam\b", 90),
    (r"\b(read|reading|chapters?)\b", 90),
    (r"\b(reflection|peer review|feedback)\b", 45),
    (r"\b(lab|notebook|worksheet|exercise)\b", 120),
    (r"\b(problem set|ps\s?\d|homework|hw\d*|assignment)\b", 180),
    (r"\b(proposal|storyboard|outline)\b", 180),
    (r"\b(slides|presentation|poster)\b", 180),
    (r"\b(draft|essay|case report|case study)\b", 300),
    (r"\b(final report|report|project|thesis)\b", 480),
    (r"\b(data cleaning|section|analysis)\b", 120),
]
EVENT_DEFAULT = 60
FALLBACK = 120


def suggest_minutes(c: Candidate, history: list[Task] | None = None) -> int:
    if c.kind == "event":
        return EVENT_DEFAULT
    for t in history or []:
        if t.kind == "deliverable" and similar_titles(t.title, c.title) and t.course_code == c.course_code:
            return max(15, t.remaining_minutes)
    title = c.title.lower()
    for pattern, minutes in TYPICAL:
        if re.search(pattern, title):
            return minutes
    return FALLBACK
