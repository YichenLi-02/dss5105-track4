"""Runtime settings. Everything is local by default; values can be overridden with environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEZONE = "Asia/Singapore"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    calendar_path: Path
    synthetic_dir: Path
    timezone: str = DEFAULT_TIMEZONE
    llm_provider: str = "offline"


def load_settings() -> Settings:
    """Read settings from the environment.

    STUDYSPACE_DATA_DIR   where the local database lives (default: <repo>/.studyspace)
    STUDYSPACE_DB         full path of the SQLite file (default: <data dir>/studyspace.db)
    STUDYSPACE_LLM_PROVIDER  "offline" (rule-based, no network) until a provider is chosen
    """
    data_dir = Path(os.environ.get("STUDYSPACE_DATA_DIR", PROJECT_ROOT / ".studyspace"))
    return Settings(
        data_dir=data_dir,
        db_path=Path(os.environ.get("STUDYSPACE_DB", data_dir / "studyspace.db")),
        calendar_path=Path(os.environ.get("STUDYSPACE_CALENDAR", PROJECT_ROOT / "data" / "calendar" / "ay2026_s1.json")),
        synthetic_dir=Path(os.environ.get("STUDYSPACE_SYNTHETIC_DIR", PROJECT_ROOT / "data" / "synthetic")),
        llm_provider=os.environ.get("STUDYSPACE_LLM_PROVIDER", "offline"),
    )
