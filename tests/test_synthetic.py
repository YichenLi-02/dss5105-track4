from studyspace.ingest import parse_csv, parse_eml
from studyspace.synthetic import DEMO_NOW, build, write


def test_build_is_deterministic():
    a, b = build(), build()
    assert a.emails == b.emails and a.timetable_ics == b.timetable_ics and a.emails_csv == b.emails_csv


def test_gold_refers_to_real_messages():
    from studyspace.ingest import pdf_record_id

    data = build()
    ids = {name.removesuffix(".eml") for name, _ in data.emails}
    assert len(ids) == 25
    ids |= {pdf_record_id(raw) for _, raw, _ in data.course_files}
    assert len(data.course_files) == 3
    gold_ids = [t["gold_id"] for t in data.gold["tasks"]]
    assert len(gold_ids) == len(set(gold_ids))
    for task in data.gold["tasks"]:
        assert set(task["source_ids"]) <= ids
    assert set(data.gold["non_task_sources"]) <= ids


def test_every_email_parses_and_csv_matches():
    data = build()
    eml = [parse_eml(raw, name).sources[0] for name, raw in data.emails]
    csv = parse_csv(data.emails_csv).sources
    assert [s.record_id for s in eml] == [s.record_id for s in csv]
    assert all(s.received_at < DEMO_NOW for s in eml)


def test_write(tmp_path):
    root = write(tmp_path / "syn")
    assert len(list((root / "emails").glob("*.eml"))) == 25
    assert len(list((root / "files").glob("*.pdf"))) == 3
    for name in ("timetable.ics", "free_time.json", "gold.json", "emails.csv"):
        assert (root / name).exists()
