"""Task extraction (member 3's area): messages in, candidate tasks out. Pure functions, no database."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ..academic_calendar import AcademicCalendar
from ..models import Candidate, Source, Task
from .dates import DateHit, DateResolver
from .merge import link_to_tasks, merge_mentions, similar_titles
from .rules import Mention, RuleExtractor


def extract(
    sources: Iterable[Source],
    calendar: AcademicCalendar | None = None,
    now: datetime | None = None,
    tasks: list[Task] | None = None,
) -> list[Candidate]:
    """Offline extraction: rules per message, then merging across messages."""
    extractor = RuleExtractor(DateResolver(calendar))
    mentions: list[Mention] = []
    for source in sources:
        mentions.extend(extractor.mentions(source, now))
    candidates = merge_mentions(mentions)
    if tasks:
        link_to_tasks(candidates, tasks)
    return candidates


__all__ = ["DateHit", "DateResolver", "Mention", "RuleExtractor", "extract", "link_to_tasks", "similar_titles"]
