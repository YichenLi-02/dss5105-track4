from studyspace.estimates import suggest_minutes
from studyspace.models import Candidate, Task

from .conftest import sgt


def cand(title, kind="deliverable", course="MLX5204"):
    return Candidate(candidate_id="C-1", source_ids=["X"], title=title, course_code=course, kind=kind, evidence=title)


def test_typical_effort_by_kind_of_work():
    assert suggest_minutes(cand("Quiz 1")) == 60
    assert suggest_minutes(cand("Problem Set 3")) == 180
    assert suggest_minutes(cand("Final report")) == 480
    assert suggest_minutes(cand("Download the paper")) == 15
    assert suggest_minutes(cand("Midterm", kind="event")) == 60
    assert suggest_minutes(cand("Something unusual")) == 120


def test_own_history_wins():
    past = Task(task_id="T1", title="Problem Set 2", course_code="MLX5204", due_at=sgt("2026-10-01T23:59"), remaining_minutes=240)
    assert suggest_minutes(cand("Problem Set 2"), [past]) == 240
    assert suggest_minutes(cand("Problem Set 3"), [past]) == 180  # a different set is not the same task
