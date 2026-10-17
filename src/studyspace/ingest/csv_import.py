"""CSV import in the format member 2 hands over (Sprint1_核心10封_系统输入_交接版.csv).

Columns: record_id, course_code, subject, posted_at, received_at, timezone, academic_context, body_text,
body_text_type. Only record_id and body_text are required; unknown columns are kept in meta.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

from ..models import Source
from ..timeutil import TZ
from .common import ImportResult, guess_course_code, short_hash

KNOWN = {"record_id", "course_code", "subject", "received_at", "body_text", "sender"}


def _parse_time(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None
    dt = datetime.fromisoformat(value.strip())
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)


def parse_csv(data: bytes | str, source_type: str = "csv") -> ImportResult:
    text = data.decode("utf-8-sig") if isinstance(data, bytes) else data.lstrip("﻿")
    result = ImportResult()
    for line_no, row in enumerate(csv.DictReader(io.StringIO(text)), start=2):
        body = (row.get("body_text") or "").strip()
        if not body:
            result.skipped.append(f"row {line_no}: empty body_text")
            continue
        subject = (row.get("subject") or "").strip() or None
        try:
            received_at = _parse_time(row.get("received_at")) or _parse_time(row.get("posted_at"))
        except ValueError:
            result.skipped.append(f"row {line_no}: unreadable received_at {row.get('received_at')!r}")
            continue
        record_id = (row.get("record_id") or "").strip() or f"CSV-{short_hash(subject or '', body)}"
        meta = {k: v for k, v in row.items() if k and k not in KNOWN and v not in (None, "")}
        result.sources.append(
            Source(
                record_id=record_id,
                source_type=source_type,  # type: ignore[arg-type]
                course_code=(row.get("course_code") or "").strip() or guess_course_code(subject, body),
                subject=subject,
                sender=(row.get("sender") or "").strip() or None,
                received_at=received_at,
                body_text=body,
                meta=meta,
            )
        )
    return result
