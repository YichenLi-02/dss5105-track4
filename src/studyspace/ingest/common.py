"""Helpers shared by the import adapters."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from ..models import Source, TimeSlot

# NUS-style module codes: DSS5105, QF5213, CS1010S, DSX5101 ...
COURSE_CODE = re.compile(r"\b([A-Z]{2,4}\d{4}[A-Z]?)\b")


@dataclass
class ImportResult:
    """What one uploaded file produced. Sources are messages; slots are timetable or free-time entries."""

    sources: list[Source] = field(default_factory=list)
    slots: list[TimeSlot] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # human-readable notes about rows that were not imported
    files: list[dict] = field(default_factory=list)   # original files to keep (file_id, filename, content_type, data)

    def extend(self, other: "ImportResult") -> None:
        self.sources.extend(other.sources)
        self.slots.extend(other.slots)
        self.skipped.extend(other.skipped)
        self.files.extend(other.files)


def guess_course_code(*texts: str | None) -> str | None:
    for text in texts:
        if text:
            m = COURSE_CODE.search(text)
            if m:
                return m.group(1)
    return None


def short_hash(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()[:10]
