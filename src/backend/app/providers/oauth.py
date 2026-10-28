"""Google / Microsoft delegated OAuth (authorization code + PKCE), read-only first.

Each capability maps to the minimum scope set; adding send/write later is incremental.
A refusal, admin-consent requirement or expiry is shown as such - never as connected.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import sqlite3
import time
from urllib.parse import urlencode

from ..config import settings
from ..db import audit, dumps, loads, now_iso
from ..errors import AppError, not_found
from . import net, tokens

G = "https://www.googleapis.com/auth/"
CAPABILITY_SCOPES = {
    "google": {"read_mail": [G + "gmail.readonly"], "read_busy": [G + "calendar.events.freebusy"],
               "send_mail": [G + "gmail.send"], "study_calendar": [G + "calendar.app.created"]},
    "microsoft": {"read_mail": ["Mail.Read"], "read_busy": ["Calendars.ReadBasic"], "read_chat": ["Chat.Read"],
                  "send_mail": ["Mail.Send"], "send_chat": ["ChatMessage.Send"], "study_calendar": ["Calendars.ReadWrite"]},
}
BASE_SCOPES = {"google": ["openid", "email"], "microsoft": ["offline_access", "User.Read"]}
WRITE_CAPS = {"send_mail", "send_chat", "study_calendar"}
_pending: dict[str, dict] = {}


def connection_id(provider: str) -> str:
    return f"conn_{provider}"


def configured(provider: str) -> bool:
    return settings.google_configured if provider == "google" else settings.microsoft_configured


def _ms_base() -> str:
    return f"https://login.microsoftonline.com/{settings.microsoft_tenant_id}/oauth2/v2.0"


def list_connections(conn: sqlite3.Connection) -> list[dict]:
    rows = {r["id"]: r for r in conn.execute("SELECT * FROM connections").fetchall()}
    out = []
    for provider in ("google", "microsoft"):
        r = rows.get(connection_id(provider))
        scopes = loads(r["scopes_json"], []) if r else []
        status = r["status"] if r else "disconnected"
        if not configured(provider):
            status = "not_configured"
        caps = {cap: all(s in scopes for s in sc) for cap, sc in CAPABILITY_SCOPES[provider].items()}
        out.append({"id": connection_id(provider), "provider": provider,
                    "account_label": r["account_label"] if r else "", "status": status, "scopes": scopes,
                    "capabilities": caps, "revision": r["revision"] if r else 1,
                    "last_error": loads(r["cursor_json"], {}).get("last_error") if r else None})
    for rid, r in rows.items():
        if r["provider"] == "local_jsonl":
            out.append({"id": rid, "provider": "local_jsonl", "account_label": r["account_label"], "status": r["status"],
                        "scopes": [], "capabilities": loads(r["capabilities_json"], {}), "revision": r["revision"],
                        "last_error": None})
    return out


def begin(conn: sqlite3.Connection, provider: str, capability: str, session_hash: str) -> dict:
    if provider not in CAPABILITY_SCOPES:
        raise not_found("provider")
    if capability not in CAPABILITY_SCOPES[provider]:
        raise AppError(422, "UNSUPPORTED_CAPABILITY", f"{provider} does not offer {capability}")
    if not configured(provider):
        raise AppError(503, "PROVIDER_NOT_CONFIGURED",
                       f"Set {provider.upper()}_CLIENT_ID / secret in .env and register the redirect URI first")
    row = conn.execute("SELECT scopes_json FROM connections WHERE id=?", (connection_id(provider),)).fetchone()
    granted = loads(row[0], []) if row else []
    scopes = sorted(set(BASE_SCOPES[provider] + granted + CAPABILITY_SCOPES[provider][capability]))
    state, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    _pending[state] = {"provider": provider, "capability": capability, "verifier": verifier, "session": session_hash,
                       "expires": time.time() + 600, "scopes": scopes}
    if provider == "google":
        params = {"client_id": settings.google_client_id, "redirect_uri": settings.google_redirect_uri,
                  "response_type": "code", "scope": " ".join(scopes), "state": state, "access_type": "offline",
                  "include_granted_scopes": "true", "code_challenge": challenge, "code_challenge_method": "S256",
                  "prompt": "consent"}
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)
    else:
        params = {"client_id": settings.microsoft_client_id, "redirect_uri": settings.microsoft_redirect_uri,
                  "response_type": "code", "scope": " ".join(scopes), "state": state, "response_mode": "query",
                  "code_challenge": challenge, "code_challenge_method": "S256"}
        url = f"{_ms_base()}/authorize?" + urlencode(params)
    audit(conn, "oauth_started", "connection", connection_id(provider), {"capability": capability})
    return {"authorization_url": url}


def _set_status(conn, provider, status, error=None, **fields):
    cid, ts = connection_id(provider), now_iso()
    conn.execute("""INSERT OR IGNORE INTO connections(id,provider,account_label,status,created_at,updated_at)
                    VALUES(?,?,?,?,?,?)""", (cid, provider, "", "disconnected", ts, ts))
    cur = loads(conn.execute("SELECT cursor_json FROM connections WHERE id=?", (cid,)).fetchone()[0], {})
    cur["last_error"] = error
    sets = {"status": status, "cursor_json": dumps(cur), **fields}
    conn.execute(f"UPDATE connections SET {', '.join(k + '=?' for k in sets)}, revision=revision+1, updated_at=? WHERE id=?",
                 (*sets.values(), ts, cid))


def callback(conn: sqlite3.Connection, provider: str, code: str | None, state: str | None, error: str | None,
             error_description: str | None = None) -> str:
    """Returns the outcome keyword used in the redirect back to the UI."""
    pending = _pending.pop(state or "", None)
    if not pending or pending["provider"] != provider or pending["expires"] < time.time():
        return "invalid_state"
    if error:
        desc = (error_description or "").lower()
        outcome = "needs_admin" if ("admin" in desc or "aadsts65001" in desc or "aadsts90094" in desc) else (
            "denied" if error == "access_denied" else "error")
        # A refusal of an extra capability keeps whatever read-only access already exists.
        row = conn.execute("SELECT status FROM connections WHERE id=?", (connection_id(provider),)).fetchone()
        _set_status(conn, provider, row["status"] if row and row["status"] == "connected" else outcome, error=outcome)
        audit(conn, "oauth_refused", "connection", connection_id(provider), {"outcome": outcome})
        return outcome
    if provider == "google":
        r = net.request("POST", "https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri, "grant_type": "authorization_code",
            "code_verifier": pending["verifier"]})
    else:
        data = {"code": code, "client_id": settings.microsoft_client_id, "redirect_uri": settings.microsoft_redirect_uri,
                "grant_type": "authorization_code", "code_verifier": pending["verifier"],
                "scope": " ".join(pending["scopes"])}
        if settings.microsoft_client_secret:
            data["client_secret"] = settings.microsoft_client_secret
        r = net.request("POST", f"{_ms_base()}/token", data=data)
    if r.status_code != 200:
        _set_status(conn, provider, "error", error=f"token_exchange_http_{r.status_code}")
        return "error"
    tok = r.json()
    granted = tok.get("scope", "").split()
    if provider == "microsoft":
        granted = [s.split("/")[-1] for s in granted]
    tok["obtained_at"] = int(time.time())
    ref = f"{connection_id(provider)}:token"
    old = tokens.load(ref) or {}
    if "refresh_token" not in tok and old.get("refresh_token"):
        tok["refresh_token"] = old["refresh_token"]
    tokens.save(ref, tok)
    label = _account_label(provider, tok)
    _set_status(conn, provider, "connected", error=None, scopes_json=dumps(sorted(set(granted))),
                credential_ref=ref, account_label=label)
    from ..services.proposal_service import OPEN_STATUSES  # connection identity/scopes changed
    conn.execute(f"UPDATE proposals SET status='invalidated', result_json=? WHERE mode='live' AND status IN {OPEN_STATUSES}",
                 (dumps({"reason": "connection_changed"}),))
    audit(conn, "oauth_connected", "connection", connection_id(provider), {"scopes": len(granted)})
    return "connected"


def _account_label(provider: str, tok: dict) -> str:
    try:
        if provider == "google":
            r = net.request("GET", "https://openidconnect.googleapis.com/v1/userinfo",
                            headers={"Authorization": f"Bearer {tok['access_token']}"})
            return r.json().get("email", "Google account") if r.status_code == 200 else "Google account"
        r = net.request("GET", "https://graph.microsoft.com/v1.0/me?$select=userPrincipalName",
                        headers={"Authorization": f"Bearer {tok['access_token']}"})
        return r.json().get("userPrincipalName", "Microsoft account") if r.status_code == 200 else "Microsoft account"
    except Exception:  # noqa: BLE001
        return f"{provider} account"


def access_token(conn: sqlite3.Connection, provider: str) -> str:
    row = conn.execute("SELECT * FROM connections WHERE id=?", (connection_id(provider),)).fetchone()
    if not row or row["status"] != "connected" or not row["credential_ref"]:
        raise AppError(409, "NOT_CONNECTED", f"{provider} is not connected")
    tok = tokens.load(row["credential_ref"])
    if not tok:
        _set_status(conn, provider, "expired", error="token_missing")
        raise AppError(401, "RECONNECT_REQUIRED", "Stored credential is missing; reconnect")
    if time.time() < tok.get("obtained_at", 0) + int(tok.get("expires_in", 0)) - 60:
        return tok["access_token"]
    if not tok.get("refresh_token"):
        _set_status(conn, provider, "expired", error="no_refresh_token")
        raise AppError(401, "RECONNECT_REQUIRED", "Access expired; reconnect")
    if provider == "google":
        r = net.request("POST", "https://oauth2.googleapis.com/token", data={
            "client_id": settings.google_client_id, "client_secret": settings.google_client_secret,
            "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    else:
        data = {"client_id": settings.microsoft_client_id, "refresh_token": tok["refresh_token"],
                "grant_type": "refresh_token"}
        if settings.microsoft_client_secret:
            data["client_secret"] = settings.microsoft_client_secret
        r = net.request("POST", f"{_ms_base()}/token", data=data)
    if r.status_code != 200:
        _set_status(conn, provider, "expired", error=f"refresh_http_{r.status_code}")
        raise AppError(401, "RECONNECT_REQUIRED", "Refresh failed; reconnect this account only")
    new = r.json()
    new["obtained_at"] = int(time.time())
    new.setdefault("refresh_token", tok["refresh_token"])
    tokens.save(row["credential_ref"], new)
    return new["access_token"]


def disconnect(conn: sqlite3.Connection, cid: str) -> dict:
    row = conn.execute("SELECT * FROM connections WHERE id=?", (cid,)).fetchone()
    if not row or row["provider"] not in ("google", "microsoft"):
        raise not_found("connection")
    if row["credential_ref"]:
        tok = tokens.load(row["credential_ref"]) or {}
        if row["provider"] == "google" and tok.get("refresh_token"):
            try:
                net.request("POST", "https://oauth2.googleapis.com/revoke", data={"token": tok["refresh_token"]})
            except Exception:  # noqa: BLE001 - local removal still happens
                pass
        tokens.delete(row["credential_ref"])
    _set_status(conn, row["provider"], "disconnected", error=None, scopes_json="[]", credential_ref=None)
    from ..services.proposal_service import OPEN_STATUSES
    conn.execute(f"UPDATE proposals SET status='invalidated', result_json=? WHERE mode='live' AND status IN {OPEN_STATUSES}",
                 (dumps({"reason": "connection_disconnected"}),))
    audit(conn, "connection_disconnected", "connection", cid, {})
    return next(c for c in list_connections(conn) if c["id"] == cid)


def has_scope(conn: sqlite3.Connection, provider: str, capability: str) -> bool:
    row = conn.execute("SELECT status, scopes_json FROM connections WHERE id=?", (connection_id(provider),)).fetchone()
    if not row or row["status"] != "connected":
        return False
    scopes = loads(row["scopes_json"], [])
    return all(s in scopes for s in CAPABILITY_SCOPES[provider][capability])
