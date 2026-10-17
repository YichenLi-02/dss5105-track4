"""Course files in PDF: lecture slides, assignment briefs, reading lists.

The text is extracted on this computer and becomes a Source like an email, so deadlines in an assignment brief are
found and merged with the emails about the same task. The original file is kept so the student can open it.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime
from pathlib import Path

from ..models import Source
from .common import ImportResult, guess_course_code

MAX_TEXT = 60_000  # characters kept for extraction; the original file is stored in full


def pdf_record_id(data: bytes) -> str:
    return "PDF-" + hashlib.sha256(data).hexdigest()[:10]


def parse_pdf(data: bytes, filename: str, received_at: datetime | None = None) -> ImportResult:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
        meta_title = (reader.metadata.title if reader.metadata else None) or ""
    except (PdfReadError, ValueError, KeyError) as exc:
        return ImportResult(skipped=[f"{filename}: not a readable PDF ({exc})"])

    text = re.sub(r"[ \t]+\n", "\n", "\n".join(pages)).strip()
    title = meta_title.strip() or Path(filename).stem.replace("_", " ")
    record_id = pdf_record_id(data)
    meta = {"filename": filename, "pages": len(pages), "file_id": record_id, "kind": "course_file"}
    if not text:
        meta["no_text"] = True
        text = "(This PDF has no selectable text, for example a scan. Open the original to read it.)"
    source = Source(
        record_id=record_id,
        source_type="pdf",
        course_code=guess_course_code(title, filename, text[:2000]),
        subject=title,
        sender=None,
        received_at=received_at,
        body_text=text[:MAX_TEXT],
        meta=meta,
    )
    return ImportResult(
        sources=[source],
        files=[{"file_id": record_id, "filename": filename, "content_type": "application/pdf", "data": data, "record_id": record_id}],
    )
