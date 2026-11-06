"""Estimate calibration from the student's own history. Pure functions: no database, no network.

Everything here produces suggestions only; the student accepts or keeps them, and nothing is changed silently.

- Estimate bias. For finished tasks, actual time / the student's first estimate. The median ratio of the most
  specific group with enough finished tasks (same course, then same kind of deliverable, then all) is applied to
  tasks that are still at their first estimate. Shortening needs more evidence than lengthening and only goes
  half the way, because planning too little time is what makes a deadline slip (too much only wastes some).
  The simulation in evaluation/planner_eval.py (score_calibration) is how these choices were checked.
- Overrun. A task whose logged time has reached its estimate but is not finished has nothing left to schedule and
  silently drops out of the plan, so the student is asked: finished, or how much is left?
- Completion rate. Of the planned minutes of past study blocks, how many were actually done. A low rate means the
  week needs more slack, and the weekly flexible time is the setting for that.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

MIN_SAMPLES = 3                # finished tasks needed before any estimate is suggested
MIN_SAMPLES_TO_SHORTEN = 5     # more evidence before suggesting LESS time
MIN_EFFECT = 0.15              # a bias under 15% is noise, not worth a prompt
RATIO_CLIP = (0.25, 4.0)       # one odd task cannot dominate
APPLY_RANGE = (0.5, 2.0)       # never suggest more than doubling or halving an estimate
STEP = 15                      # suggestions in quarter hours
MIN_CHECKINS = 5               # answered check-ins before a completion rate is used
LOW_COMPLETION = 0.85          # below this, suggest more weekly slack
FLEX_STEP = 30
FLEX_MAX_EXTRA = 180


@dataclass(frozen=True)
class Sample:
    task_id: str
    title: str
    title_en: str | None
    course: str | None
    deliverable: str | None
    estimate: int  # the student's first estimate
    actual: int  # minutes the student said it took, else the logged minutes
    confirmed: bool  # actual given by the student when finishing (not only the logged time)

    @property
    def ratio(self) -> float:
        return min(max(self.actual / self.estimate, RATIO_CLIP[0]), RATIO_CLIP[1])


def median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def bias_for(samples: list[Sample], course: str | None, deliverable: str | None) -> dict | None:
    """The most specific group with enough finished tasks, and its median actual/estimate ratio."""
    groups = []
    if course:
        groups.append(("course", course, [s for s in samples if s.course == course]))
    if deliverable:
        groups.append(("deliverable", deliverable, [s for s in samples if s.deliverable == deliverable]))
    groups.append(("all", None, list(samples)))
    for kind, value, group in groups:
        if len(group) >= MIN_SAMPLES:
            return {"group": kind, "value": value, "n": len(group),
                    "ratio": round(median([s.ratio for s in group]), 2), "samples": group}
    return None


def suggest_minutes(estimate: int, completed: int, bias: dict) -> int | None:
    """New estimate for a task still at its first estimate, or None when the history does not justify one."""
    r = bias["ratio"]
    if abs(r - 1) < MIN_EFFECT:
        return None
    if r < 1:
        if bias["n"] < MIN_SAMPLES_TO_SHORTEN:
            return None
        r = 1 - (1 - r) / 2  # only half the way down
    r = min(max(r, APPLY_RANGE[0]), APPLY_RANGE[1])
    new = max(int(round(estimate * r / STEP)) * STEP, STEP)
    new = max(new, completed + STEP)  # never below the time already spent
    return new if new != estimate else None


def completion(rows: list[tuple[int, int]], weeks: float, flex_now: int) -> dict:
    """rows: (planned minutes, minutes actually done) per answered check-in."""
    planned = sum(p for p, _ in rows)
    done = sum(min(d, p) for p, d in rows)  # doing more than planned in one block does not cancel a missed one
    rate = round(done / planned, 2) if planned else None
    extra = 0
    if len(rows) >= MIN_CHECKINS and rate is not None and rate < LOW_COMPLETION:
        missed_per_week = (planned - done) / max(weeks, 1.0)
        extra = min(FLEX_MAX_EXTRA, math.ceil(missed_per_week / FLEX_STEP) * FLEX_STEP)
    return {"checkins": len(rows), "planned_minutes": planned, "done_minutes": done, "rate": rate,
            "enough": len(rows) >= MIN_CHECKINS, "flex_now": flex_now,
            "flex_suggested": flex_now + extra if extra else None}
