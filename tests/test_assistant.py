from datetime import date

from studyspace.drafts import draft_reply, learn_style
from studyspace.extraction import extract
from studyspace.ingest import parse_eml
from studyspace.meetings import suggest_slots
from studyspace.models import Interval, Source
from studyspace.synthetic import DEMO_NOW, build
from studyspace.synthetic.generator import SENT_SAMPLES
from studyspace.triage import sender_kind, triage

from .conftest import sgt


def _inbox():
    data = build()
    sources = [parse_eml(raw, name).sources[0] for name, raw in data.emails]
    return sources, extract(sources)


def test_triage_labels():
    sources, candidates = _inbox()
    items = {t.record_id: t for t in triage(sources, candidates, "u.example.edu", DEMO_NOW)}
    assert items["SYN-018"].primary == "reply" and items["SYN-018"].sender_kind == "external"
    assert "reply" in items["SYN-019"].labels and "task" in items["SYN-019"].labels
    assert items["SYN-016"].primary == "newsletter"
    assert items["SYN-010"].labels == ["task", "event"]
    assert items["SYN-009"].urgent  # Lab 4 is due today


def test_sender_kinds():
    assert sender_kind("Daniel Koh (TA) <daniel.koh@u.example.edu>", "u.example.edu") == "staff"
    assert sender_kind("Priya Nair <priya.nair@u.example.edu>", "u.example.edu") == "peer"
    assert sender_kind("Canvas Notifications <notifications@canvas.example.edu>", "u.example.edu") == "system"
    assert sender_kind("Mei Ling Chua <meiling.chua@talent.example.com>", "u.example.edu") == "external"


def test_style_is_learned_from_sent_mail():
    style = learn_style([text for _, text in SENT_SAMPLES], "Jordan")
    assert (style.greeting, style.sign_off) == ("Hi", "Thanks")


def test_draft_for_a_recruiter_offers_times_and_warns():
    src = Source(record_id="R", source_type="eml", sender="Mei Ling Chua <meiling.chua@talent.example.com>",
                 subject="Coffee chat?", body_text="Hi Jordan, let me know your availability by Friday for a 20-minute call.")
    slot = {"start": "2026-10-13T14:00:00+08:00", "end": "2026-10-13T14:30:00+08:00"}
    d = draft_reply(src, learn_style([]), [slot], "u.example.edu")
    assert d.intent == "availability" and "Tue 13 Oct, 14:00–14:30" in d.body
    assert d.warnings[0]["code"] == "SENSITIVE_RECIPIENT" and d.sent is False
    assert d.subject == "Re: Coffee chat?"


def test_draft_for_a_groupmate_keeps_the_deadline():
    src = Source(record_id="G", source_type="eml", sender="Priya Nair <priya.nair@u.example.edu>", subject="data cleaning",
                 body_text="Hey Jordan,\n\nCould you finish the data cleaning section by Thursday night?\n\nThanks!\nPriya")
    d = draft_reply(src, learn_style([]), None, "u.example.edu")
    assert d.body.startswith("Hi Priya,") and "finish the data cleaning section by Thursday night" in d.body
    assert d.warnings == []


def test_meeting_slots_avoid_busy_and_spread_out():
    busy = [Interval(start=sgt("2026-10-13T09:00"), end=sgt("2026-10-13T12:00"))]
    soft = [Interval(start=sgt("2026-10-13T12:00"), end=sgt("2026-10-13T13:00"))]
    slots = suggest_slots(busy, date(2026, 10, 13), date(2026, 10, 14), 60, DEMO_NOW, ("09:00", "17:00"), soft_busy=soft)
    starts = [s["start"] for s in slots]
    assert starts[0] == "2026-10-13T13:00:00+08:00"                 # after the class and the planned session
    clean = [s for s in slots if "note" not in s]
    assert sum(s["start"].startswith("2026-10-13") for s in clean) <= 2   # at most two options per day
    assert slots[: len(clean)] == clean                                  # free options come before ones that move study


def test_meeting_slots_never_in_the_past():
    slots = suggest_slots([], date(2026, 10, 12), date(2026, 10, 12), 30, sgt("2026-10-12T15:10"), ("09:00", "18:00"))
    assert slots and all(s["start"] >= "2026-10-12T15:10" for s in slots)
