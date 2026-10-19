"""Student Work Assistant - single FastAPI process, SQLite, same-origin static frontend."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import errors
from .api import connections, core, documents, drafts, messages, plans, tasks
from .config import REPO_ROOT, VERSION, settings
from .db import init_db
from .security import BOOTSTRAP_CODE

FRONTEND_DIST = REPO_ROOT / "src" / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    print(f"[student-work-assistant] mode={settings.app_mode} db={settings.database_path}")
    if settings.app_mode == "live":
        print(f"[student-work-assistant] one-time local session code: {BOOTSTRAP_CODE}")
    yield


app = FastAPI(title="Student Work Assistant API", version=VERSION, lifespan=lifespan)
errors.install(app)
for module in (core, messages, tasks, documents, drafts, plans, connections):
    app.include_router(module.router)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse(errors.error_body("NOT_FOUND", "Unknown API route"), status_code=404)
        candidate = (FRONTEND_DIST / path).resolve()
        if path and candidate.is_file() and FRONTEND_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        # index.html must never be cached, otherwise a rebuilt bundle is not picked up on refresh.
        return FileResponse(FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
