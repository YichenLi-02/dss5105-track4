"""Import adapters (member 2's area). Each turns one kind of input into Sources or TimeSlots.

Synthetic data and real exports go through the same adapters, so switching to real Outlook / Gmail /
NUSMods data later only adds a new adapter; nothing downstream changes.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..models import Source
from .availability import expand_template, parse_availability_json
from .common import ImportResult, guess_course_code, short_hash
from .csv_import import parse_csv
from .eml_import import parse_eml
from .ics_import import parse_ics
from .pdf_import import parse_pdf, pdf_record_id

SUPPORTED = (".csv", ".eml", ".ics", ".json", ".txt", ".pdf")


def parse_text(
    text: str,
    subject: str | None = None,
    course_code: str | None = None,
    received_at: datetime | None = None,
    source_type: str = "paste",
) -> ImportResult:
    """Pasted text: a forwarded email, a Teams / WhatsApp message, a line from a course page."""
    body = text.strip()
    if not body:
        return ImportResult(skipped=["empty text"])
    first_line = body.splitlines()[0][:120]
    return ImportResult(
        sources=[
            Source(
                record_id=f"PASTE-{short_hash(subject or '', body)}",
                source_type=source_type,  # type: ignore[arg-type]
                course_code=course_code or guess_course_code(subject, body),
                subject=subject or first_line,
                received_at=received_at,
                body_text=body,
            )
        ]
    )


def parse_file(filename: str, data: bytes, received_at: datetime | None = None) -> ImportResult:
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(data, filename, received_at)
    if suffix == ".csv":
        return parse_csv(data)
    if suffix == ".eml":
        return parse_eml(data, filename)
    if suffix == ".ics":
        return parse_ics(data)
    if suffix == ".json":
        return parse_availability_json(data)
    if suffix == ".txt":
        return parse_text(data.decode("utf-8-sig"), subject=Path(filename).stem, received_at=received_at)
    return ImportResult(skipped=[f"{filename}: unsupported file type (use {', '.join(SUPPORTED)})"])


__all__ = [
    "ImportResult",
    "SUPPORTED",
    "expand_template",
    "guess_course_code",
    "parse_availability_json",
    "parse_csv",
    "parse_eml",
    "parse_file",
    "parse_ics",
    "parse_pdf",
    "parse_text",
    "pdf_record_id",
]
