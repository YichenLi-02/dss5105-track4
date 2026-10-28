"""Outbound HTTP policy: only fixed official hosts; Canvas/LMS is always refused.
URLs found inside mail, PDFs or chat are never fetched through here."""
from __future__ import annotations

from urllib.parse import urlparse

import httpx

from ..config import settings
from ..errors import AppError

ALLOWED_HOSTS = {
    "accounts.google.com", "oauth2.googleapis.com", "gmail.googleapis.com", "www.googleapis.com",
    "openidconnect.googleapis.com", "login.microsoftonline.com", "graph.microsoft.com",
}
BLOCKED_SUFFIXES = ("canvas.nus.edu.sg", "instructure.com", "canvas.")


def allowed(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if urlparse(url).scheme != "https":
        return False
    if any(host == b or host.endswith("." + b) or host.startswith(b) for b in BLOCKED_SUFFIXES):
        return False
    model_host = (urlparse(settings.openai_base_url).hostname or "").lower()
    return host in ALLOWED_HOSTS or (bool(model_host) and host == model_host)


def request(method: str, url: str, *, timeout: float = 30.0, transport: httpx.BaseTransport | None = None, **kw) -> httpx.Response:
    if not allowed(url):
        raise AppError(403, "OUTBOUND_HOST_BLOCKED", "Destination is not an allowed provider endpoint")
    with httpx.Client(timeout=timeout, transport=transport or _transport, follow_redirects=False) as c:
        return c.request(method, url, **kw)


# Tests replace this with httpx.MockTransport; production uses the default network transport.
_transport: httpx.BaseTransport | None = None


def set_transport(t: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = t
