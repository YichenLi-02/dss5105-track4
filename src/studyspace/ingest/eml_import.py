"""Import of saved emails (.eml), the format Outlook and Gmail both export."""

from __future__ import annotations

import html
import re
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parsedate_to_datetime

from ..models import Source
from ..timeutil import TZ
from .common import ImportResult, guess_course_code, short_hash

_TAGS = re.compile(r"<[^>]+>")
_BLOCK_TAGS = re.compile(r"</?(p|div|br|li|tr|h[1-6])[^>]*>", re.I)
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)


def html_to_text(markup: str) -> str:
    markup = _SCRIPT.sub("", markup)
    markup = _BLOCK_TAGS.sub("\n", markup)
    text = html.unescape(_TAGS.sub("", markup))
    lines = [re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _body(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    content = part.get_content()
    return html_to_text(content) if part.get_content_subtype() == "html" else content.strip()


def _sender(msg: EmailMessage) -> str | None:
    """Decoded From header, keeping a role comment such as "(TA)" that the address parser drops."""
    decoded = str(msg.get("From", "")).strip()
    raw = next((str(v) for k, v in msg.raw_items() if k.lower() == "from"), "")
    comment = re.search(r"\(([^()]{1,40})\)", raw.split("<")[0])
    if comment and comment.group(0) not in decoded and "<" in decoded:
        name, addr = decoded.split("<", 1)
        decoded = f"{name.strip()} {comment.group(0)} <{addr}"
    return decoded or None


def parse_eml(data: bytes, filename: str = "") -> ImportResult:
    msg = BytesParser(policy=policy.default).parsebytes(data)
    subject = str(msg.get("Subject", "")).strip() or None
    body = _body(msg)  # type: ignore[arg-type]
    if not body:
        return ImportResult(skipped=[f"{filename or 'email'}: no readable text body"])

    received_at = None
    if msg.get("Date"):
        try:
            received_at = parsedate_to_datetime(str(msg["Date"]))
            if received_at.tzinfo is None:
                received_at = received_at.replace(tzinfo=TZ)
        except (TypeError, ValueError):
            received_at = None

    record_id = (
        str(msg.get("X-Record-Id", "")).strip()
        or str(msg.get("Message-ID", "")).strip().strip("<>")
        or f"EML-{short_hash(subject or '', body)}"
    )
    meta = {"filename": filename} if filename else {}
    if msg.get("To"):
        meta["to"] = str(msg["To"])
    if msg.get("In-Reply-To"):
        meta["in_reply_to"] = str(msg["In-Reply-To"]).strip("<>")

    source = Source(
        record_id=record_id,
        source_type="eml",
        course_code=str(msg.get("X-Course-Code", "")).strip() or guess_course_code(subject, body),
        subject=subject,
        sender=_sender(msg),  # type: ignore[arg-type]
        received_at=received_at,
        body_text=body,
        meta=meta,
    )
    return ImportResult(sources=[source])
