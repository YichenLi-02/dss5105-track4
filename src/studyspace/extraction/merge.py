"""Merge mentions of the same task across messages, oldest first.

A later message about the same task either repeats it (duplicate: sources are combined), fills in a
missing date or time, or moves the deadline (DATE_CHANGED, the old value kept in history).
"""

from __future__ import annotations

import re

from typing import Iterable

from ..ingest.common import short_hash
from ..models import DATE_CHANGED, MIDNIGHT_AMBIGUITY, MISSING_DUE_AT, NEEDS_CONFIRM, Candidate, Task
from .rules import Mention

_STOP = {"the", "a", "an", "of", "for", "on", "in", "to", "and", "your", "our", "submission", "due", "deadline",
         "group", "individual", "please", "reminder", "update", "updated", "new"}
_ALIASES = [(re.compile(r"\bmid[\s-]?terms?\b"), "midterm"), (re.compile(r"\bproblem sets?\b"), "ps"),
            (re.compile(r"\bhomework\b"), "hw"), (re.compile(r"\bassignments?\b"), "assignment")]


def title_tokens(title: str) -> set[str]:
    t = title.lower()
    for pattern, repl in _ALIASES:
        t = pattern.sub(repl, t)
    t = re.sub(r"(?<=[a-z])(?=\d)|(?<=\d)(?=[a-z])", " ", t)  # assignment2 -> assignment 2, ps2 -> ps 2
    return {w for w in re.findall(r"[a-z0-9]+", t) if w not in _STOP}


def similar_titles(a: str, b: str, threshold: float = 0.5) -> bool:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return False
    na, nb = {w for w in ta if w.isdigit()}, {w for w in tb if w.isdigit()}
    if na and nb and na != nb:
        return False  # Assignment 2 is not Assignment 3
    if ta <= tb or tb <= ta:
        return True
    return len(ta & tb) / len(ta | tb) >= threshold


def _same_course(a: str | None, b: str | None) -> bool:
    return a == b or a is None or b is None


def _snapshot(m: Mention) -> dict:
    return {
        "source_id": m.source_id,
        "due_text": m.due_text,
        "due_date": m.due_date.isoformat() if m.due_date else None,
        "due_at": m.due_at.isoformat() if m.due_at else None,
    }


def merge_mentions(mentions: Iterable[Mention]) -> list[Candidate]:
    # undated messages (pasted text) count as the newest
    ordered = sorted(
        mentions, key=lambda m: (m.received_at is None, m.received_at.timestamp() if m.received_at else 0.0, m.source_id)
    )
    groups: list[dict] = []
    for m in ordered:
        group = next(
            (g for g in groups if _same_course(g["course"], m.course_code) and similar_titles(g["title"], m.title)
             and (g["course"] == m.course_code or similar_titles(g["title"], m.title, 0.8))),
            None,
        )
        if group is None:
            groups.append({
                "course": m.course_code, "title": m.title, "kind": m.kind, "best": m, "sources": [m.source_id],
                "history": [], "changed": False, "first_source": m.source_id,
            })
            continue
        if m.source_id not in group["sources"]:
            group["sources"].append(m.source_id)
        if m.course_code and not group["course"]:
            group["course"] = m.course_code
        best: Mention = group["best"]
        if m.hit is None or m.due_date is None:
            continue  # a reminder without a date changes nothing
        if best.due_date is None:
            group["history"].append(_snapshot(best) | {"note": "no date"})
            group["best"] = m
        elif m.due_date != best.due_date or (m.due_at and best.due_at and m.due_at != best.due_at):
            group["history"].append(_snapshot(best))
            group["best"] = m
            group["changed"] = True
        elif m.rank > best.rank:
            group["best"] = m  # same day, now with a time or stated explicitly

    return [_to_candidate(g) for g in groups]


def _to_candidate(g: dict) -> Candidate:
    best: Mention = g["best"]
    flags = set(best.flags)
    if g["changed"]:
        flags.add(DATE_CHANGED)
    if best.due_date is None:
        flags.add(NEEDS_CONFIRM)
        if not best.due_text:
            flags.add(MISSING_DUE_AT)
    else:
        flags.discard(MISSING_DUE_AT)
        if best.due_at and best.hit and not best.hit.inferred:
            flags.discard(NEEDS_CONFIRM)
    if MIDNIGHT_AMBIGUITY in flags and best.due_at is None:
        flags.add(NEEDS_CONFIRM)
    order = [DATE_CHANGED, MISSING_DUE_AT, MIDNIGHT_AMBIGUITY, NEEDS_CONFIRM]
    return Candidate(
        candidate_id=f"C-{short_hash(g['course'] or '', ' '.join(sorted(title_tokens(g['title']))), g['first_source'])}",
        source_ids=g["sources"],
        title=g["title"],
        course_code=g["course"],
        kind=best.kind,  # type: ignore[arg-type]
        due_text=best.due_text,
        due_date=best.due_date,
        due_at=best.due_at,
        evidence=best.evidence,
        flags=sorted(flags, key=lambda f: order.index(f) if f in order else len(order)),
        history=g["history"],
    )


def link_to_tasks(candidates: list[Candidate], tasks: list[Task]) -> None:
    """Point a candidate at the confirmed task it updates, so the student can apply the change in one click."""
    for c in candidates:
        for t in tasks:
            if _same_course(c.course_code, t.course_code) and similar_titles(c.title, t.title):
                c.related_task_id = t.task_id
                if c.due_at and c.due_at != t.due_at and DATE_CHANGED not in c.flags:
                    c.flags.insert(0, DATE_CHANGED)
                break
