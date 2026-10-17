"""HTTP API (FastAPI). `create_app()` builds the application; `app` is what uvicorn serves."""

from .app import ApiError, create_app

__all__ = ["ApiError", "create_app"]
