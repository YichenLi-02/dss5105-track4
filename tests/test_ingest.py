from datetime import timedelta

from studyspace.ingest import expand_template, parse_csv, parse_eml, parse_file, parse_ics, parse_text
from studyspace.synthetic import build

from .conftest import sgt

CSV = (
    "﻿record_id,course_code,subject,posted_at,received_at,timezone,academic_context,body_text,body_text_type\n"
    'S001,DSS5101,"Assignment created - CA 1, DSS5101 Principles [2610]",,2026-08-11T21:18:18+08:00,Asia/Singapore,'
    'AY2026/27 Sem 1,"CA 1\ndue: 29 Aug at 23:59",excerpt\n'
    "S002,,No body,,2026-08-12T10:00:00+08:00,Asia/Singapore,,,\n"
)


def test_member2_csv_with_bom():
    result = parse_csv(CSV.encode("utf-8"))
    assert [s.record_id for s in result.sources] == ["S001"]
    s = result.sources[0]
    assert s.course_code == "DSS5101" and s.received_at == sgt("2026-08-11T21:18:18")
    assert s.meta["academic_context"] == "AY2026/27 Sem 1"
    assert result.skipped and "empty body_text" in result.skipped[0]


def test_eml_headers_and_body():
    name, raw = build().emails[8]  # SYN-009, a reply with a quoted message
    s = parse_eml(raw, name).sources[0]
    assert s.record_id == "SYN-009" and s.course_code == "MLX5204"
    assert s.received_at == sgt("2026-10-12T07:30")
    assert s.meta["in_reply_to"] == "SYN-008@synthetic.studyspace.local"


def test_html_only_email_is_converted_to_text():
    raw = (b"From: a@b.c\r\nSubject: HTML only\r\nDate: Mon, 12 Oct 2026 08:00:00 +0800\r\n"
           b"Content-Type: text/html; charset=utf-8\r\n\r\n<p>Submit <b>Lab 5</b> by 16 Oct.</p><style>x{}</style>")
    s = parse_eml(raw).sources[0]
    assert s.body_text == "Submit Lab 5 by 16 Oct."


def test_ics_weekly_with_recess_skipped():
    slots = parse_ics(build().timetable_ics).slots
    lecture = [s for s in slots if s.label.startswith("DSX5101")]
    assert len(lecture) == 13                      # 14 weeks minus recess
    assert lecture[0].start == sgt("2026-08-10T10:00")
    assert all(s.start.date().isoformat() != "2026-09-21" for s in lecture)
    assert all(s.end - s.start == timedelta(hours=2) for s in lecture)
    assert {s.kind for s in slots} == {"busy"}


def test_ics_utc_and_byday():
    ics = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Gym\nDTSTART:20261012T010000Z\nDTEND:20261012T020000Z\n"
           "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=4\nEND:VEVENT\nBEGIN:VEVENT\nSUMMARY:Holiday\n"
           "DTSTART;VALUE=DATE:20261020\nEND:VEVENT\nEND:VCALENDAR\n")
    result = parse_ics(ics)
    assert [s.start for s in result.slots] == [sgt("2026-10-12T09:00"), sgt("2026-10-14T09:00"), sgt("2026-10-19T09:00"), sgt("2026-10-21T09:00")]
    assert result.skipped == ["Holiday: all-day or undated event skipped"]


def test_free_time_template():
    slots = expand_template({"from": "2026-10-12", "to": "2026-10-18", "weekly": [{"weekday": "monday", "start": "13:00", "end": "18:00"}],
                             "exclude_dates": []})
    assert len(slots) == 1 and slots[0].start == sgt("2026-10-12T13:00") and slots[0].kind == "available"


def test_paste_and_dispatch():
    r = parse_text("MLX5204: please finish the slides by Friday")
    assert r.sources[0].course_code == "MLX5204" and r.sources[0].record_id.startswith("PASTE-")
    assert parse_file("notes.docx", b"x").skipped
