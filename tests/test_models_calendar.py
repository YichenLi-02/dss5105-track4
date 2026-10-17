import json
from datetime import date, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from studyspace.models import Interval, PlanRequest, Progress, Task

from .conftest import sgt


def test_times_must_carry_an_offset():
    with pytest.raises(ValidationError):
        Task(task_id="T1", title="Essay", due_at=datetime(2026, 10, 15, 17, 0), remaining_minutes=60)
    Task(task_id="T1", title="Essay", due_at=sgt("2026-10-15T17:00"), remaining_minutes=60)


def test_interval_end_after_start():
    with pytest.raises(ValidationError):
        Interval(start=sgt("2026-10-12T10:00"), end=sgt("2026-10-12T10:00"))


def test_effort_in_minutes_cannot_be_negative():
    with pytest.raises(ValidationError):
        Task(task_id="T1", title="Essay", due_at=sgt("2026-10-15T17:00"), remaining_minutes=-5)


def test_progress_minutes():
    p = Progress(op_id="op1", task_id="T1", start=sgt("2026-10-12T13:00"), end=sgt("2026-10-12T14:30"))
    assert p.minutes == 90


def test_member4_reference_cases_fit_the_shared_request_format():
    raw = json.loads((Path(__file__).parent / "fixtures" / "reference_cases.json").read_text())
    for case in raw["cases"]:
        request = PlanRequest.model_validate({**case["input"], "settings": raw["settings"]})
        assert request.tasks, case["id"]


def test_academic_weeks(calendar):
    assert calendar.week(9).start == date(2026, 10, 12)
    assert calendar.weekday_in_week(9, 4) == date(2026, 10, 16)       # Friday of Week 9
    assert calendar.weekday_after("recess", 0) == date(2026, 9, 28)   # Monday after recess week
    assert calendar.period_of(date(2026, 9, 23)).label == "Recess Week"
    assert calendar.period_of(date(2026, 12, 25)) is None
