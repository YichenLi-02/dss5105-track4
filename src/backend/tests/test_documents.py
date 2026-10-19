"""PDF upload/parse states, page-traceable evidence, relative dates via same-term calendar, exclusion."""
import io

from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas


def _pdf(pages: list[list[str]]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for lines in pages:
        y = 800
        for line in lines:
            c.drawString(50, y, line)
            y -= 18
        c.showPage()
    c.save()
    return buf.getvalue()


def _upload(api, data: bytes, name="x.pdf"):
    return api.c.post("/api/uploads", files={"file": (name, data, "application/pdf")}, data={"format": "pdf"},
                      headers={"X-CSRF-Token": api.csrf})


def _doc(api, upload_id=None, **kw):
    body = {"upload_id": upload_id, "kind": "syllabus", "title": "Test syllabus", "course": "TEST5105",
            "term": "Synthetic Term B", "source_timezone": "Asia/Singapore", "permission_confirmed": True, **kw}
    return api.post("/api/documents", body)


def test_rejects_non_pdf_and_requires_permission(api):
    r = _upload(api, b"hello world", "a.pdf")
    assert r.status_code == 422 and r.json()["error"]["code"] == "NOT_A_PDF"
    up = _upload(api, _pdf([["Assignment 1 due 2026-10-30 23:59"]])).json()
    r = _doc(api, up["upload_id"], permission_confirmed=False)
    assert r.json()["error"]["code"] == "PERMISSION_NOT_CONFIRMED"


def test_text_pdf_parsed_with_pages_and_null_time(api):
    data = _pdf([["Course overview", "Nothing due here"],
                 ["Assignment 2 is due Friday, 30 Oct 2026.", "Quiz 3 deadline: 2026-11-04 11:50 PM"]])
    up = _upload(api, data).json()
    doc = _doc(api, up["upload_id"]).json()
    assert doc["extraction_status"] == "text_ready" and doc["page_count"] == 2
    assert doc["excerpt_origin"] == "parsed_pdf"
    r = api.post(f"/api/documents/{doc['id']}/extract", {"expected_revision": doc["revision"], "calendar_document_ids": [],
                                                           "use_model": False}).json()
    cands = {c["title"]: c for c in r["document"]["candidates"]}
    a2 = next(c for t, c in cands.items() if "Assignment 2" in t)
    assert a2["official_date"] == "2026-10-30" and a2["official_time"] is None  # no 23:59 default
    assert a2["evidence"][0]["locator"]["page"] == 2
    q3 = next(c for t, c in cands.items() if "Quiz 3" in t)
    assert q3["official_time"] == "23:50"
    ev = q3["evidence"][0]
    full = api.get(f"/api/documents/{doc['id']}").json()["parsed_text"]
    assert full[ev["start_char"]:ev["end_char"]] == ev["quote"]
    # Re-running the extraction updates the same candidates instead of duplicating them.
    again = api.post(f"/api/documents/{doc['id']}/extract", {"expected_revision": r["document"]["revision"],
                                                               "calendar_document_ids": [], "use_model": False}).json()
    assert again["result"]["candidates"] == 0


def test_blank_pdf_needs_ocr_and_paste_fallback(api):
    up = _upload(api, _pdf([[]])).json()
    doc = _doc(api, up["upload_id"]).json()
    assert doc["extraction_status"] == "needs_ocr" and doc["candidates"] == []
    r = api.post(f"/api/documents/{doc['id']}/extract", {"expected_revision": doc["revision"], "calendar_document_ids": [],
                                                           "use_model": False})
    assert r.status_code == 422 and r.json()["error"]["code"] == "NO_TEXT"
    p = api.patch(f"/api/documents/{doc['id']}", {"expected_revision": doc["revision"],
                                                  "user_excerpt": "Lab report due 2026-11-02", "page": 4}).json()
    assert p["excerpt_origin"] == "user_pasted" and p["extraction_status"] == "needs_ocr"
    r = api.post(f"/api/documents/{doc['id']}/extract", {"expected_revision": p["revision"], "calendar_document_ids": [],
                                                           "use_model": False}).json()
    ev = r["document"]["candidates"][0]["evidence"][0]
    assert ev["field"] == "user_excerpt" and ev["locator"]["page"] == 4 and ev["locator"]["excerpt_origin"] == "user_pasted"


def test_encrypted_and_broken_pdf(api):
    w = PdfWriter()
    w.append(PdfReader(io.BytesIO(_pdf([["Secret due 2026-11-01"]]))))
    w.encrypt(user_password="pw", owner_password="owner", algorithm="RC4-128")
    buf = io.BytesIO()
    w.write(buf)
    up = _upload(api, buf.getvalue()).json()
    assert _doc(api, up["upload_id"]).json()["extraction_status"] == "encrypted"
    up = _upload(api, b"%PDF-1.7\n garbage that is not a pdf").json()
    doc = _doc(api, up["upload_id"]).json()
    assert doc["extraction_status"] == "failed" and doc["extraction_error"]


def test_relative_date_needs_same_term_calendar_and_exclusion_invalidates(api):
    docs = api.post("/api/demo/documents").json()
    syl = next(d for d in docs if d["kind"] == "syllabus")
    cal = next(d for d in docs if d["kind"] == "academic_calendar")
    # Without a calendar the relative phrase stays unresolved.
    r = api.post(f"/api/documents/{syl['id']}/extract", {"expected_revision": syl["revision"], "calendar_document_ids": [],
                                                           "use_model": False}).json()
    rep = next(c for c in r["document"]["candidates"] if "report" in c["title"].lower())
    assert rep["official_date"] is None and "confirm_relative_date" in rep["missing_fields"]
    other = _doc(api, None, kind="academic_calendar", term="Other Term",
                 user_excerpt="Reading week: 2026-09-21 to 2026-09-27").json()
    syl2 = api.get(f"/api/documents/{syl['id']}").json()
    r = api.post(f"/api/documents/{syl['id']}/extract", {"expected_revision": syl2["revision"],
                                                           "calendar_document_ids": [other["id"]], "use_model": False}).json()
    # A calendar from another term is not used: a new rule-run with the same quote keeps the existing candidate.
    assert all(c["official_date"] != "2026-09-28" for c in r["document"]["candidates"])
    # Fresh document, same-term calendar -> resolves to the Friday after reading week, time unknown.
    syl3 = _doc(api, None, term=cal["term"], user_excerpt="The final essay is due the Friday after reading week.").json()
    r = api.post(f"/api/documents/{syl3['id']}/extract", {"expected_revision": syl3["revision"],
                                                            "calendar_document_ids": [cal["id"]], "use_model": False}).json()
    c = r["document"]["candidates"][0]
    assert c["official_date"] == "2026-10-16" and c["official_time"] is None and c["status"] == "needs_review"
    d = api.get(f"/api/documents/{syl3['id']}").json()
    ex = api.patch(f"/api/documents/{syl3['id']}", {"expected_revision": d["revision"], "excluded": True}).json()
    assert ex["excluded"] is True
    t = api.get(f"/api/tasks/{c['id']}").json()
    assert t["revision"] > c["revision"] and t["evidence"][0]["source_excluded"] is True
    r = api.post(f"/api/documents/{syl3['id']}/extract", {"expected_revision": ex["revision"], "calendar_document_ids": [],
                                                            "use_model": False})
    assert r.status_code == 409


def test_delete_local_data(api):
    up = _upload(api, _pdf([["Project due 2026-12-01"]])).json()
    doc = _doc(api, up["upload_id"]).json()
    api.post(f"/api/documents/{doc['id']}/extract", {"expected_revision": doc["revision"], "calendar_document_ids": [],
                                                       "use_model": False})
    d = api.get(f"/api/documents/{doc['id']}").json()
    out = api.delete(f"/api/documents/{doc['id']}", {"expected_revision": d["revision"]}).json()
    assert out["extraction_status"] == "deleted" and out["affected_tasks"] == 1
    assert all(x["id"] != doc["id"] for x in api.get("/api/documents").json())
