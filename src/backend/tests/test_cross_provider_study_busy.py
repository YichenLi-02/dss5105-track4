"""Busy time from one provider must not be cancelled by a block in the other account.

Both accounts may contain events at the same time. Moving or keeping Google's event
does not explain Outlook's busy interval, and vice versa. No network access is used.
"""
from datetime import datetime

import pytest

from app.config import settings
from app.db import connect, init_db
from app.providers import calendars
from app.services import plan_service, proposal_service


START = "2026-11-07T09:30:00+08:00"
END = "2026-11-07T10:00:00+08:00"


@pytest.mark.parametrize("moving_provider,other_provider", [("google", "microsoft"), ("microsoft", "google")])
def test_move_recheck_preserves_other_provider_busy(tmp_path, monkeypatch, moving_provider, other_provider):
    monkeypatch.setattr(settings, "database_path", tmp_path / "cross-provider.sqlite3")
    init_db()
    snap = {"id": "test-snapshot", "provider": moving_provider,
            "connection_id": f"conn_{moving_provider}", "calendar_ids": ["primary"],
            "display_timezone": "Asia/Singapore", "study_calendar": {"status": "complete"}}
    monkeypatch.setattr(plan_service, "get_plan", lambda *_: {"inputs": {"snapshot_id": snap["id"]}})
    monkeypatch.setattr(plan_service, "get_snapshot", lambda *_: snap)
    monkeypatch.setattr(plan_service, "study_calendars", lambda *_: [(moving_provider, "study-a"), (other_provider, "study-b")])

    def read_busy(conn, provider, cid, t0, t1, tz, ids):
        busy = [] if ids == ["primary"] else [{"start": START, "end": END}]
        return {"status": "complete", "busy": busy, "errors": []}

    monkeypatch.setattr(calendars, "read_busy", read_busy)
    payload = {"plan_id": "test-plan", "timezone": "Asia/Singapore",
               "events": [{"start": "2026-11-07T09:45:00+08:00", "end": "2026-11-07T10:15:00+08:00"}],
               "remove_events": [{"provider": moving_provider, "start": START, "end": END, "event_id": "old"}]}
    with connect() as conn:
        result = proposal_service.recheck_busy_before_write(conn, payload)
    assert result is not None and result["reason"] == "calendar_conflict"


@pytest.mark.parametrize("kept_provider,other_provider", [("google", "microsoft"), ("microsoft", "google")])
def test_reconcile_preserves_unrelated_other_provider_busy(kept_provider, other_provider):
    written = [{"task_id": "a", "provider": kept_provider,
                "start": datetime.fromisoformat(START), "end": datetime.fromisoformat(END)}]
    snap = {"study_calendar": {"status": "complete", "providers": [kept_provider, other_provider]},
            "busy": [{"start": START, "end": END, "own_study": True, "study_provider": p}
                     for p in (kept_provider, other_provider)]}
    kept, busy, notes = plan_service.reconcile_study_blocks(written, snap)
    assert kept == written and notes == []
    assert len(busy) == 1 and busy[0]["study_provider"] == other_provider
    assert busy[0]["start"] == START and busy[0]["end"] == END
