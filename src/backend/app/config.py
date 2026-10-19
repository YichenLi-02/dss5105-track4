"""Runtime configuration. Everything optional: missing values disable features, never crash."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSION = "0.4.0"

load_dotenv(REPO_ROOT / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    p = Path(raw) if raw else default
    return p if p.is_absolute() else (REPO_ROOT / p).resolve()


@dataclass
class Settings:
    app_mode: str = "demo"
    data_dir: Path = REPO_ROOT / "local-data"
    database_path: Path = REPO_ROOT / "local-data" / "app.sqlite3"
    display_timezone: str = "Asia/Singapore"
    sample_data_dir: Path = Path("D:/DSS5105-track4/AI项目数据源_去隐私")
    design_dir: Path = Path("D:/DSS5105-track4/软件设计与AI工作流")
    llm_provider: str = "none"
    openai_api_key: str = ""
    openai_model: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    allow_model_processing: bool = False
    enable_external_writes: bool = False
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://127.0.0.1:8000/api/connections/google/callback"
    microsoft_client_id: str = ""
    microsoft_tenant_id: str = "organizations"
    microsoft_client_secret: str = ""
    microsoft_redirect_uri: str = "http://127.0.0.1:8000/api/connections/microsoft/callback"
    frontend_origin: str = "http://127.0.0.1:5173"
    allowed_origins: list[str] = field(default_factory=list)
    max_upload_bytes: int = 20 * 1024 * 1024

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def model_configured(self) -> bool:
        return self.llm_provider == "openai" and bool(self.openai_api_key and self.openai_model)

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def microsoft_configured(self) -> bool:
        return bool(self.microsoft_client_id)


def load_settings() -> Settings:
    s = Settings(
        app_mode=os.environ.get("APP_MODE", "demo").strip() or "demo",
        data_dir=_path("DATA_DIR", REPO_ROOT / "local-data"),
        display_timezone=os.environ.get("DISPLAY_TIMEZONE", "Asia/Singapore"),
        sample_data_dir=_path("SAMPLE_DATA_DIR", Path("D:/DSS5105-track4/AI项目数据源_去隐私")),
        design_dir=_path("DESIGN_DIR", Path("D:/DSS5105-track4/软件设计与AI工作流")),
        llm_provider=os.environ.get("LLM_PROVIDER", "none").strip().lower() or "none",
        openai_api_key=os.environ.get("OPENAI_API_KEY", "").strip(),
        openai_model=os.environ.get("OPENAI_MODEL", "").strip(),
        openai_base_url=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").strip(),
        allow_model_processing=_bool("ALLOW_MODEL_PROCESSING"),
        enable_external_writes=_bool("ENABLE_EXTERNAL_WRITES"),
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
        google_redirect_uri=os.environ.get(
            "GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/api/connections/google/callback"),
        microsoft_client_id=os.environ.get("MICROSOFT_CLIENT_ID", "").strip(),
        microsoft_tenant_id=os.environ.get("MICROSOFT_TENANT_ID", "organizations").strip() or "organizations",
        microsoft_client_secret=os.environ.get("MICROSOFT_CLIENT_SECRET", "").strip(),
        microsoft_redirect_uri=os.environ.get(
            "MICROSOFT_REDIRECT_URI", "http://127.0.0.1:8000/api/connections/microsoft/callback"),
        frontend_origin=os.environ.get("FRONTEND_ORIGIN", "http://127.0.0.1:5173"),
    )
    s.database_path = _path("DATABASE_PATH", s.data_dir / "app.sqlite3")
    if s.app_mode not in {"demo", "live"}:
        s.app_mode = "demo"
    s.allowed_origins = sorted({
        s.frontend_origin, "http://127.0.0.1:5173", "http://localhost:5173",
        "http://127.0.0.1:8000", "http://localhost:8000",
    })
    return s


settings = load_settings()
