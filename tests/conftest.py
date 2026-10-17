from __future__ import annotations

import warnings
from dataclasses import replace
from datetime import datetime

import pytest

from studyspace.academic_calendar import AcademicCalendar
from studyspace.config import load_settings
from studyspace.timeutil import TZ

warnings.filterwarnings("ignore", message="Using `httpx`")


@pytest.fixture()
def settings(tmp_path):
    base = load_settings()
    return replace(base, data_dir=tmp_path, db_path=tmp_path / "test.db", llm_provider="offline")


@pytest.fixture()
def calendar():
    return AcademicCalendar.load(load_settings().calendar_path)


@pytest.fixture()
def client(settings):
    from fastapi.testclient import TestClient

    from studyspace.api import create_app

    return TestClient(create_app(settings))


def sgt(text: str) -> datetime:
    """Local Singapore time from 'YYYY-MM-DDTHH:MM'."""
    return datetime.fromisoformat(text).replace(tzinfo=TZ)
