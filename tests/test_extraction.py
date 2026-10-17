from datetime import date

import pytest

from studyspace.extraction import extract, similar_titles
from studyspace.ingest import parse_eml, parse_text
from studyspace.models import DATE_CHANGED, MIDNIGHT_AMBIGUITY, MISSING_DUE_AT, NEEDS_CONFIRM, Source, Task
from studyspace.synthetic import build

from .conftest import sgt


@pytest.fixture(scope="module")
def synthetic_candidates():
    from studyspace.academic_calendar import AcademicCalendar
    from studyspace.config import load_settings

    data = build()
    sources = [parse_eml(raw, name).sources[0] for name, raw in data.emails]
    return extract(sources, AcademicCalendar.load(load_settings().calendar_path)), data.gold


def find(candidates, *source_ids):
    return [c for c in candidates if set(source_ids) <= set(c.source_ids)]


def test_three_step_change_keeps_history(synthetic_candidates):
    cands, _ = synthetic_candidates
    (essay,) = find(cands, "SYN-003")
    assert essay.source_ids == ["SYN-003", "SYN-004", "SYN-005"]
    assert essay.due_at == sgt("2026-10-15T17:00")
    assert DATE_CHANGED in essay.flags
    assert [h["due_date"] for h in essay.history] == ["2026-10-09", "2026-10-14"]


def test_duplicate_reminder_is_merged(synthetic_candidates):
    cands, _ = synthetic_candidates
    (midterm,) = find(cands, "SYN-010")
    assert midterm.source_ids == ["SYN-010", "SYN-011"] and midterm.kind == "event"
    assert midterm.due_at == sgt("2026-10-22T18:30")


def test_midnight_stays_unresolved(synthetic_candidates):
    cands, _ = synthetic_candidates
    (report,) = find(cands, "SYN-007")
    assert report.due_at is None and report.due_date == date(2026, 10, 23)
    assert MIDNIGHT_AMBIGUITY in report.flags and NEEDS_CONFIRM in report.flags


def test_later_message_fills_a_missing_date(synthetic_candidates):
    cands, _ = synthetic_candidates
    (lab,) = find(cands, "SYN-008", "SYN-009")
    assert lab.due_at == sgt("2026-10-12T23:00")
    assert MISSING_DUE_AT not in lab.flags


def test_no_date_is_flagged_not_invented(synthetic_candidates):
    cands, _ = synthetic_candidates
    (reflection,) = find(cands, "SYN-022")
    assert reflection.due_date is None and reflection.due_at is None and MISSING_DUE_AT in reflection.flags


def test_newsletters_and_recruiters_are_not_tasks(synthetic_candidates):
    cands, _ = synthetic_candidates
    used = {s for c in cands for s in c.source_ids}
    assert not used & {"SYN-016", "SYN-017", "SYN-018", "SYN-023", "SYN-025"}


def test_recall_on_synthetic_gold_does_not_regress(synthetic_candidates):
    """Development check only; the reported score comes from the held-out real set."""
    cands, gold = synthetic_candidates
    matched = 0
    for g in gold["tasks"]:
        for c in cands:
            if set(g["source_ids"]) & set(c.source_ids) and similar_titles(g["title"], c.title, 0.3):
                same_day = (c.due_date.isoformat() if c.due_date else None) == g["due_date"]
                matched += same_day
                break
    assert matched >= 12, f"only {matched} of {len(gold['tasks'])} gold tasks found with the right day"


def test_real_style_canvas_message():
    src = Source(record_id="S002", source_type="csv", course_code="QF5213",
                 subject="Assignment created - Assignment2 submission due 12 midnight Sept 28, QF5213 Financial Management [2610]",
                 received_at=sgt("2026-09-24T17:42"),
                 body_text="Assignment2 submission due 12 midnight Sept 28\ndue: 28 Sep at 23:59")
    (c,) = extract([src])
    assert c.title == "Assignment2" and c.due_at == sgt("2026-09-28T23:59")
    assert MIDNIGHT_AMBIGUITY in c.flags  # the conflict stays visible for the student to check


def test_candidate_points_at_the_task_it_updates():
    task = Task(task_id="T-1", title="Problem Set 2", course_code="MLX5204", due_at=sgt("2026-10-16T23:59"), remaining_minutes=120)
    src = parse_text("MLX5204: Problem Set 2 is now due on 19 Oct, 11:59pm.", received_at=sgt("2026-10-09T16:00")).sources[0]
    (c,) = extract([src], tasks=[task])
    assert c.related_task_id == "T-1" and DATE_CHANGED in c.flags


def test_title_similarity():
    assert similar_titles("Mid-term", "Mid-term exam")
    assert similar_titles("Assignment2", "Assignment 2")
    assert not similar_titles("Assignment 2", "Assignment 3")
    assert not similar_titles("Final exam", "Final report")
