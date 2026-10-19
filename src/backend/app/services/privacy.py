"""Local minimisation before anything is stored or sent to a model."""
from __future__ import annotations

import hashlib
import re

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL = re.compile(r"https?://[^\s<>\"')]+", re.I)
_PHONE = re.compile(r"(?<![\d-])(?:\+?\d[\d\s().-]{8,}\d)(?![\d-])")
_DATE_INSIDE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}\.\d{1,2}\.\d{2,4}")
_LONG_NUMBER = re.compile(r"(?<!\d)\d{7,}(?!\d)")
_CODE_LINE = re.compile(r"(?i)\b(verification|security|one[- ]time|otp|验证码|passcode|code)\b[^\n]{0,40}?(\d{4,8})")


def _tag(prefix: str, value: str) -> str:
    return f"[{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:8]}]"


def scrub(text: str) -> str:
    """Replace addresses, links, phone numbers, codes and long IDs with stable placeholders."""
    if not text:
        return ""
    text = _CODE_LINE.sub(lambda m: m.group(0).replace(m.group(2), "[CODE_REMOVED]"), text)
    text = _EMAIL.sub(lambda m: _tag("EMAIL", m.group(0).lower()), text)
    text = _URL.sub(lambda m: _tag("LINK", m.group(0)), text)
    text = _LONG_NUMBER.sub("[LONG_NUMBER_REMOVED]", text)
    # Dates and date ranges look like phone numbers to a loose pattern; keep them.
    text = _PHONE.sub(lambda m: m.group(0) if _DATE_INSIDE.search(m.group(0)) else "[PHONE_REMOVED]", text)
    return text


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


REDACTED_ADDRESS = re.compile(r"\[(EMAIL|CONTACT|USER)[^\]]*\]")


def is_redacted_address(addr: str) -> bool:
    """Placeholders from de-identified samples can never be live recipients."""
    return bool(REDACTED_ADDRESS.search(addr)) or "@" not in addr
