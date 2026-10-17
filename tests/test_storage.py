import sqlite3

import pytest

from studyspace.models import Candidate, PlanRequest, PlanResult, PlanSettings, Progress, Source, Task
from studyspace.storage import Database
from studyspace.storage import repo

from .conftest import sgt


@pytest.fixture()
def conn(tmp_path):
    db = Database(tmp_path / "s.db")
    with db.connect() as c:
        yield c


def src(body="Lab 4 due Friday"):
    return Source(record_id="R1", source_type="paste", body_text=body, received_at=sgt("2026-10-12T08:00"))


def test_source_versions(conn):
    assert repo.upsert_source(conn, "w", src()) == "added"
    assert repo.upsert_source(conn, "w", src()) == "duplicate"
    assert repo.upsert_source(conn, "w", src("Lab 4 due Monday")) == "updated"
    (latest,) = repo.list_sources(conn, "w")
    assert latest.body_text == "Lab 4 due Monday" and latest.meta["version"] == 2


def test_workspaces_are_separate(conn):
    repo.upsert_source(conn, "a", src())
    assert repo.list_sources(conn, "b") == []


def test_handled_candidates_keep_their_status(conn):
    c = Candidate(candidate_id="C-1", source_ids=["R1"], title="Lab 4", evidence="Lab 4 due Friday")
    repo.save_candidates(conn, "w", [c])
    repo.set_candidate_status(conn, "w", "C-1", "dismissed")
    repo.save_candidates(conn, "w", [c.model_copy(update={"title": "Lab 4 notebook"})])
    (again,) = repo.list_candidates(conn, "w")
    assert again.status == "dismissed" and again.title == "Lab 4"


def test_progress_is_idempotent(conn):
    p = Progress(op_id="op-1", task_id="T1", start=sgt("2026-10-12T13:00"), end=sgt("2026-10-12T14:00"))
    assert repo.add_progress(conn, "w", p) is True
    assert repo.add_progress(conn, "w", p) is False
    assert len(repo.list_progress(conn, "w")) == 1


def test_input_version_changes_with_tasks(conn):
    s = PlanSettings()
    v1 = repo.input_version(conn, "w", s)
    repo.save_task(conn, "w", Task(task_id="T1", title="Essay", due_at=sgt("2026-10-15T17:00"), remaining_minutes=60))
    assert repo.input_version(conn, "w", s) != v1


def test_only_one_adopted_plan(conn):
    req = PlanRequest(now=sgt("2026-10-12T08:00"), tasks=[], availability=[])
    res = PlanResult(status="complete")
    repo.save_plan(conn, "w", "P1", "v", req, res)
    repo.save_plan(conn, "w", "P2", "v", req, res)
    repo.adopt_plan(conn, "w", "P1")
    repo.adopt_plan(conn, "w", "P2")
    assert repo.get_adopted_plan(conn, "w")["plan_id"] == "P2"
    assert repo.get_plan(conn, "w", "P1")["status"] == "superseded"


def test_failed_transaction_rolls_back(tmp_path):
    db = Database(tmp_path / "t.db")
    with pytest.raises(sqlite3.IntegrityError):
        with db.connect() as c:
            repo.upsert_source(c, "w", src())
            c.execute("INSERT INTO progress (workspace_id, op_id, body, created_at) VALUES ('w', 'x', '{}', 'now')")
            c.execute("INSERT INTO progress (workspace_id, op_id, body, created_at) VALUES ('w', 'x', '{}', 'now')")
    with db.connect() as c:
        assert repo.list_sources(c, "w") == []
