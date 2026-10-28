"""Local single-user session, CSRF and Origin checks.

Sessions live in memory: restarting the server ends every session, so a stale
browser tab must re-create one. The bootstrap code is only demanded in live mode;
it is printed to the server console, never returned by an API.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass

from fastapi import Request

from .config import settings
from .errors import AppError

COOKIE = "swa_session"
OWNER = "local_user"
SESSION_TTL = 12 * 3600


@dataclass
class Session:
    session_id: str
    csrf_token: str
    created: float

    @property
    def id_hash(self) -> str:
        return hashlib.sha256(self.session_id.encode()).hexdigest()


_sessions: dict[str, Session] = {}
BOOTSTRAP_CODE = secrets.token_hex(4)


def create_session(bootstrap_code: str | None) -> Session:
    if settings.app_mode == "live" and not hmac.compare_digest(bootstrap_code or "", BOOTSTRAP_CODE):
        raise AppError(401, "BOOTSTRAP_CODE_INVALID", "Live mode needs the one-time code printed by the server")
    s = Session(secrets.token_urlsafe(32), secrets.token_urlsafe(24), time.time())
    _sessions[s.session_id] = s
    return s


def _lookup(request: Request) -> Session | None:
    sid = request.cookies.get(COOKIE)
    s = _sessions.get(sid or "")
    if s and time.time() - s.created < SESSION_TTL:
        return s
    return None


def require_session(request: Request) -> Session:
    s = _lookup(request)
    if not s:
        raise AppError(401, "SESSION_REQUIRED", "Create a local session first (POST /api/session)")
    return s


def require_mutation(request: Request) -> Session:
    s = require_session(request)
    origin = request.headers.get("origin")
    if origin and origin not in settings.allowed_origins:
        raise AppError(403, "ORIGIN_REJECTED", "Request origin is not allowed")
    token = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(token, s.csrf_token):
        raise AppError(403, "CSRF_REJECTED", "Missing or wrong X-CSRF-Token")
    return s
