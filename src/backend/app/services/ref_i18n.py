"""English versions of app-provided labels (reference annotations, fixture titles).

Only labels the app shows *about* a source are localised here. Mail bodies, subjects, evidence
quotes, style excerpts, chat text and anything the user typed are never translated.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..config import settings

FIXTURE_TITLES_EN = {
    "synthetic_demo5105_report": "DEMO5105 report (synthetic)",
}
FIXTURE_DOC_TITLES_EN = {
    "合成课程大纲 · DEMO5105 (synthetic)": "Synthetic syllabus · DEMO5105",
    "合成学年日历 · Demo Term A (synthetic)": "Synthetic academic calendar · Demo Term A",
}


@lru_cache(maxsize=2)
def _load(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _data() -> dict:
    return _load(str(settings.sample_data_dir / "annotation_en.json"))


def mail(sample_id: str) -> dict:
    return _data().get("mail", {}).get(sample_id, {})


def task_title(entity_key: str) -> str | None:
    return FIXTURE_TITLES_EN.get(entity_key) or _data().get("tasks", {}).get(entity_key)


def style(sample_id: str) -> dict:
    return _data().get("style", {}).get(sample_id, {})


def profile_context(name: str) -> str | None:
    return _data().get("profile_contexts", {}).get(name)


def profile_fallback(name: str) -> str | None:
    return _data().get("profile_fallbacks", {}).get(name)


def doc_title(title: str | None) -> str | None:
    return FIXTURE_DOC_TITLES_EN.get(title or "")
