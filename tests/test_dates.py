"""Date phrases taken from the real Sprint 1 emails (member 2's set) and the synthetic inbox."""

from datetime import date, time

import pytest

from studyspace.extraction.dates import DateResolver
from studyspace.models import MIDNIGHT_AMBIGUITY, NEEDS_CONFIRM

from .conftest import sgt

CASES = [
    # phrase, message received, expected day, expected time, flags that must be present
    ("due: 29 Aug at 23:59", "2026-08-11T21:18", date(2026, 8, 29), time(23, 59), set()),
    ("Due 05 October 2026, 9 pm.", "2026-09-16T11:31", date(2026, 10, 5), time(21, 0), set()),
    ("Deadline: Wednesday, 23 September 2026, 11:59 PM", "2026-09-17T20:55", date(2026, 9, 23), time(23, 59), set()),
    ("we are extending the deadline to 30 September.", "2026-09-25T21:40", date(2026, 9, 30), None, {NEEDS_CONFIRM}),
    ("Midterm This Friday: Be There by 7:00 PM", "2026-09-30T21:09", date(2026, 10, 2), time(19, 0), {NEEDS_CONFIRM}),
    ("our mid-term exam is on tonight in our usual lecture theatre at 7pm.", "2026-09-30T12:19", date(2026, 9, 30), time(19, 0), {NEEDS_CONFIRM}),
    ("Submit the proposal by Friday of Week 9.", "2026-10-02T12:00", date(2026, 10, 16), None, {NEEDS_CONFIRM}),
    ("due the Monday after recess week, by 9am", "2026-09-18T17:00", date(2026, 9, 28), time(9, 0), {NEEDS_CONFIRM}),
    ("Quiz 1 is due next Monday at 11:59pm.", "2026-10-07T13:30", date(2026, 10, 12), time(23, 59), {NEEDS_CONFIRM}),
    ("Due 30/9 at 2359", "2026-09-20T10:00", date(2026, 9, 30), time(23, 59), set()),
]


@pytest.mark.parametrize("phrase,received,day,clock,flags", CASES)
def test_phrases(calendar, phrase, received, day, clock, flags):
    hit = DateResolver(calendar).first(phrase, sgt(received))
    assert hit is not None
    assert hit.day == day
    assert hit.time == clock
    assert flags <= hit.flags


def test_midnight_is_never_guessed(calendar):
    hit = DateResolver(calendar).first("Assignment2 submission due 12 midnight Sept 28", sgt("2026-09-24T17:42"))
    assert hit.day == date(2026, 9, 28)
    assert hit.time is None
    assert MIDNIGHT_AMBIGUITY in hit.flags


def test_week_without_weekday_gives_no_day(calendar):
    hit = DateResolver(calendar).first("Final report due in Week 13", sgt("2026-10-07T10:00"))
    assert hit.day is None and NEEDS_CONFIRM in hit.flags


def test_old_date_in_an_extension_is_marked_old(calendar):
    hits = DateResolver(calendar).find("The deadline has been extended from Oct 16 to Oct 19, 11:59pm.", sgt("2026-10-09T16:00"))
    roles = {h.day: h.role for h in hits}
    assert roles == {date(2026, 10, 16): "old", date(2026, 10, 19): "due"}


def test_opening_time_is_not_a_deadline(calendar):
    hits = DateResolver(calendar).find(
        "DSS5105 2610 Midterm is available in Examplify from 6:00 AM on Friday, 2 October 2026.", sgt("2026-09-30T21:09")
    )
    assert [h.role for h in hits] == ["start"]


def test_year_follows_the_message_date(calendar):
    hit = DateResolver(calendar).first("due 5 Jan", sgt("2026-11-20T10:00"))
    assert hit.day == date(2027, 1, 5)


def test_the_verb_may_is_not_a_month(calendar):
    assert DateResolver(calendar).find("You may submit 2 files", sgt("2026-10-07T10:00")) == []


def test_ambiguous_numeric_date_needs_confirmation(calendar):
    hit = DateResolver(calendar).first("due 3/10", sgt("2026-09-20T10:00"))
    assert hit.day == date(2026, 10, 3) and NEEDS_CONFIRM in hit.flags
