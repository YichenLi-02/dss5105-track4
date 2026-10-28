"""Reference grouping (category / importance / summary / candidate titles) for the 40 samples.

selected_50.jsonl has no topic category. The grouping comes from the offline prototype; the
pseudonymised data folder ships it as reference_view.json. That file is preferred so the app never
needs the prototype HTML (which still holds original text). Everything from here is stored with
analysis_origin='reference_annotation' - AI-assisted suggestions pending human review.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ..config import settings


@lru_cache(maxsize=4)
def _load_prototype(path: str) -> dict:
    p = Path(path)
    if not p.is_file():
        return {}
    text = p.read_text(encoding="utf-8")
    start = text.find("const DATA=")
    end = text.find("const catNames", start)
    if start < 0 or end < 0:
        return {}
    try:
        return json.loads(text[start + len("const DATA="):end].strip().rstrip(";"))
    except json.JSONDecodeError:
        return {}


@lru_cache(maxsize=4)
def _load_json(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def prototype_path() -> Path:
    return settings.design_dir / "ui" / "index.html"


def data() -> dict:
    shipped = settings.sample_data_dir / "reference_view.json"
    if shipped.is_file():
        return _load_json(str(shipped))
    return _load_prototype(str(prototype_path()))


def mail_view() -> dict[str, dict]:
    return {m["id"]: m for m in data().get("mail", [])}


def candidate_titles() -> dict[str, str]:
    return {c["key"]: c["title"] for c in data().get("candidates", []) if c.get("key") and c.get("title")}


def style_view() -> dict[str, dict]:
    return {s["id"]: s for s in data().get("styleReferences", []) or []}
