"""Planner engine against member 4's reference cases, plus randomised rule checks."""

import json
import random
from datetime import timedelta
from pathlib import Path

import pytest

from studyspace.models import Interval, PlanBlock, PlanRequest, PlanTask
from studyspace.planner import check_plan, generate

from .conftest import sgt

RAW = json.loads((Path(__file__).parent / "fixtures" / "reference_cases.json").read_text())


@pytest.mark.parametrize("case", RAW["cases"], ids=[c["id"] for c in RAW["cases"]])
def test_reference_case(case):
    request = PlanRequest.model_validate({**case["input"], "settings": RAW["settings"]})
    result = generate(request)
    assert check_plan(request, result) == []                      # every hard rule holds
    ref = case["reference_plan"]
    assert result.status == ref["status"]
    scheduled = sum((b.end - b.start).total_seconds() / 60 for b in result.blocks)
    assert scheduled == case["expected"]["scheduled_minutes"]
    assert sum(u.minutes for u in result.unscheduled) == case["expected"]["unscheduled_minutes"]
    ours = {(w.code, w.task_id) for w in result.warnings}
    theirs = {(w["code"], w["task_id"]) for w in ref["warnings"]}
    assert theirs <= ours and {c for c, _ in ours - theirs} <= {"DEADLINE_CLUSTER"}
    assert result.retained_locked_blocks == request.locked_blocks
    if "minimum_buffer_hours" in case["expected"]:
        ends = {}
        for b in [*result.blocks, *request.locked_blocks]:
            ends[b.task_id] = max(ends.get(b.task_id, b.end), b.end)
        buffers = [(t.due_at - ends[t.id]).total_seconds() / 3600 for t in request.tasks if t.id in ends]
        assert min(buffers) >= case["expected"]["minimum_buffer_hours"] or result.warnings


def test_accounting_adds_up():
    case = next(c for c in RAW["cases"] if c["id"] == "meeting_replan")
    request = PlanRequest.model_validate({**case["input"], "settings": RAW["settings"]})
    (tr,) = generate(request).task_results
    assert (tr.reserved_minutes, tr.locked_future_minutes, tr.scheduled_minutes, tr.unscheduled_minutes) == (120, 60, 60, 0)


def test_effort_is_rounded_up_to_15_minutes():
    request = PlanRequest(now=sgt("2026-10-12T08:00"),
                          tasks=[PlanTask(id="A", title="Lab", due_at=sgt("2026-10-15T18:00"), remaining_minutes=50)],
                          availability=[Interval(start=sgt("2026-10-12T13:00"), end=sgt("2026-10-12T18:00"))])
    result = generate(request)
    assert [(b.end - b.start).seconds // 60 for b in result.blocks] == [60]


def test_never_plans_over_a_lock_conflict_silently():
    request = PlanRequest(
        now=sgt("2026-10-12T08:00"),
        tasks=[PlanTask(id="A", title="Essay", due_at=sgt("2026-10-16T18:00"), remaining_minutes=120)],
        availability=[Interval(start=sgt("2026-10-13T09:00"), end=sgt("2026-10-13T12:00"))],
        busy=[Interval(start=sgt("2026-10-13T09:00"), end=sgt("2026-10-13T10:00"))],
        locked_blocks=[PlanBlock(task_id="A", start=sgt("2026-10-13T09:00"), end=sgt("2026-10-13T10:00"))],
    )
    result = generate(request)
    assert result.status == "blocked" and any(w.code == "LOCK_CONFLICT" for w in result.warnings)
    assert result.retained_locked_blocks == request.locked_blocks  # the lock is not moved for the student


def _random_request(rng: random.Random) -> PlanRequest:
    now = sgt("2026-10-12T08:00") + timedelta(minutes=rng.choice([0, 7, 30, 95, 600]))
    tasks = [PlanTask(id=f"T{i}", title=f"Task {i}", due_at=sgt("2026-10-12T12:00") + timedelta(hours=rng.randint(4, 140)),
                      remaining_minutes=rng.choice([20, 45, 60, 90, 120, 200, 300]), priority=rng.choice(["high", "medium", "low"]),
                      confirmed=rng.random() > 0.1) for i in range(rng.randint(1, 6))]
    availability, busy = [], []
    for d in range(7):
        day = sgt("2026-10-12T00:00") + timedelta(days=d)
        for _ in range(rng.randint(0, 3)):
            start = day + timedelta(hours=rng.randint(6, 21), minutes=rng.choice([0, 10, 15, 30, 45]))
            availability.append(Interval(start=start, end=start + timedelta(minutes=rng.choice([45, 60, 120, 180, 300]))))
        if rng.random() < 0.6:
            start = day + timedelta(hours=rng.randint(9, 18), minutes=rng.choice([0, 20, 30]))
            busy.append(Interval(start=start, end=start + timedelta(minutes=rng.choice([60, 90, 120]))))
    completed = [PlanBlock(task_id="T0", start=sgt("2026-10-12T09:00"), end=sgt("2026-10-12T10:30"))] if rng.random() < 0.3 else []
    return PlanRequest(now=now, tasks=tasks, availability=availability, busy=busy, completed_blocks=completed)


def test_random_requests_never_break_a_hard_rule():
    rng = random.Random(5105)
    for _ in range(1000):
        request = _random_request(rng)
        result = generate(request)
        assert check_plan(request, result) == [], request.model_dump_json()
