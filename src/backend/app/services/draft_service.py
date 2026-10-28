"""Local drafts. Offline drafting is template-based and says so; it borrows only greeting /
closing / request phrasing from selected own samples, never their facts. Unknown facts become
[[placeholders]] that block review until the user fills them."""
from __future__ import annotations

import re
import sqlite3
from collections import Counter

from ..db import audit, dumps, loads, new_id, now_iso
from ..errors import AppError, conflict, not_found
from . import document_service, style_service
from .privacy import is_redacted_address

PLACEHOLDER = re.compile(r"\[\[[^\]\n]{1,120}\]\]")
ADDRESS_IN_LABEL = re.compile(r"<([^<>]+)>")
GREETING = re.compile(r"(?i)^(hi|hello|dear)(\s+professor)?\b")

P = {
    "en": {"name": "[[recipient name]]", "sig": "[[your name]]", "reason": "[[actual reason for the extension]]",
           "date": "[[requested new deadline]]", "task": "[[assignment / task name]]",
           "reply": "[[your reply - only facts you have checked]]", "points": "[[summary points to share]]"},
    "zh": {"name": "[[称呼]]", "sig": "[[你的署名]]", "reason": "[[延期的实际理由]]", "date": "[[希望延到的日期]]",
           "task": "[[作业/任务名称]]", "reply": "[[回复内容：只写你已核实的事实]]", "points": "[[要同步的要点]]"},
}
FIELD_FOR = {"reason": "reason", "date": "requested_new_date", "task": "task_title", "name": "recipient_name",
             "sig": "signature", "reply": "reply_points", "points": "summary_points"}


def _style_bits(examples: list[dict], relationship: str) -> dict:
    greet, close, could = [], [], False
    for e in examples:
        lines = [ln.strip() for ln in e["authored_excerpt"].splitlines() if ln.strip()]
        m = GREETING.match(lines[0]) if lines else None
        if m:
            # Only the salutation shape is reused; whoever the old email addressed never is.
            greet.append(f"{m.group(1).capitalize()}{' Professor' if m.group(2) else ''} {{name}},")
        for ln in lines[-3:]:
            if re.match(r"(?i)^best\b|^kind regards|^thank you", ln) and len(ln) < 30:
                close.append(ln.rstrip("，,") + ",")
        could |= "could you please" in e["authored_excerpt"].lower()
    if relationship == "professor":
        prof = [g for g in greet if "Professor" in g]
        greet = prof or greet
    return {"greeting": Counter(greet).most_common(1)[0][0] if greet else None,
            "closing": Counter(close).most_common(1)[0][0] if close else None, "could": could}


def _compose(purpose: str, language: str, facts: dict, subject: str, bits: dict, short: bool) -> str:
    p = P["zh" if language == "zh" else "en"]
    name = facts.get("recipient_name") or p["name"]
    sig = facts.get("signature") or p["sig"]
    if language == "zh":
        greeting, closing = f"{name}您好：", "谢谢！"
    else:
        greeting = (bits.get("greeting") or "Dear {name},").replace("{name}", name)
        closing = bits.get("closing") or "Kind regards,"
    ask = "Could you please" if bits.get("could") or language != "zh" else ""
    reason = facts.get("reason")
    if purpose == "extension":
        task = facts.get("task_title") or subject or p["task"]
        date = facts.get("requested_new_date") or p["date"]
        if language == "zh":
            body = [f"我想询问 {task} 能否延期至 {date}。",
                    f"原因：{reason}" if reason else p["reason"],
                    "请问是否可行？感谢您的理解。"]
        else:
            body = [f"I am writing to ask whether it would be possible to extend the deadline for {task} to {date}.",
                    f"The reason is that {reason}" if reason else p["reason"],
                    f"{ask} let me know whether this would be possible?",
                    *([] if short else ["Thank you for your time and consideration."])]
    elif purpose == "followup":
        pts = facts.get("summary_points")
        points = "\n".join(f"- {x}" for x in pts) if isinstance(pts, list) and pts else p["points"]
        body = (["以下是今天讨论的跟进：", points, "如有遗漏请补充。"] if language == "zh" else
                ["Here is a short follow-up from our discussion:", points, "Please add anything I missed."])
    else:
        reply = facts.get("reply_points") or p["reply"]
        body = ([f"关于「{subject}」：", reply] if language == "zh" else
                [f"Thank you for your email about \"{subject}\".", reply])
    return "\n\n".join([greeting, *body, f"{closing}\n{sig}"])


def placeholders(text: str) -> list[str]:
    return sorted(set(PLACEHOLDER.findall(text)))


FIELD_OF_PLACEHOLDER = {text: FIELD_FOR[k] for lang in P.values() for k, text in lang.items()}


def _missing(d: dict) -> list[str]:
    missing = [f"{FIELD_OF_PLACEHOLDER.get(ph, 'placeholder')}:{ph}"
               for ph in placeholders(d["subject"] + "\n" + d["body"])]
    rec = d["recipients"]
    if d["channel"] == "email" and not rec.get("to"):
        missing.append("recipients:to")
    if not d["subject"].strip() and d["channel"] == "email":
        missing.append("subject")
    return missing


def _view(row: sqlite3.Row) -> dict:
    vf = loads(row["verified_facts_json"], {})
    meta = vf.get("meta", {})
    rec = loads(row["recipients_json"], {})
    body = row["body"]
    return {
        "id": row["id"], "channel": row["channel"], "purpose": row["purpose"],
        "source_message_id": row["source_message_id"], "connection_id": row["connection_id"],
        "to": rec.get("to", []), "cc": rec.get("cc", []), "bcc": rec.get("bcc", []),
        "subject": row["subject"], "body": body, "attachments": loads(row["attachments_json"], []),
        "style_reference_ids": loads(row["style_reference_ids_json"], []),
        "style_mode": meta.get("style_mode", "generic"), "style_note": meta.get("style_note", ""),
        "relationship": meta.get("relationship", "professor"), "language": meta.get("language", "en"),
        "verified_facts": vf.get("facts", {}), "missing_fields": loads(row["missing_fields_json"], []),
        "placeholders": placeholders(row["subject"] + "\n" + body),
        "ready_for_review": bool(row["ready_for_review"]), "revision": row["revision"],
        "requires_confirmation": True, "stale_style": bool(vf.get("_style_changed_at")),
        "generation": meta.get("generation", "template"),
        "recipients_deidentified": any(is_redacted_address(a) for a in rec.get("to", []) + rec.get("cc", []) + rec.get("bcc", [])),
        "updated_at": row["updated_at"],
    }


def get_draft(conn: sqlite3.Connection, draft_id: str) -> dict:
    row = conn.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        raise not_found("draft")
    return _view(row)


def _attachments(ids: list[str]) -> list[dict]:
    out = []
    for i in ids:
        m = document_service.upload_meta(i)
        out.append({"id": i, "name": m["filename"], "size_bytes": m["size_bytes"], "sha256": m["sha256"]})
    return out


def _default_relationship(conn: sqlite3.Connection, msg: sqlite3.Row | None) -> str:
    if not msg:
        return "professor"
    a = loads(msg["analysis_json"], {}) or {}
    if a.get("category") == "career":
        return "recruiter"
    group = loads(msg["locator_json"], {}).get("case_group") or ""
    if any(k in group for k in ("team", "chat")):
        return "peer"
    sender = loads(msg["sender_json"], {}).get("label", "")
    return "professor" if re.search(r"(?i)prof|CSE|course|\(20\d\d", sender) else "admin"


def create_draft(conn: sqlite3.Connection, body: dict, model_text: str | None = None) -> dict:
    msg = None
    if body.get("source_message_id"):
        msg = conn.execute("SELECT * FROM messages WHERE id=? OR source_id=?",
                           (body["source_message_id"], body["source_message_id"])).fetchone()
        if not msg:
            raise not_found("source message")
    relationship = body.get("relationship") or _default_relationship(conn, msg)
    language = body.get("language") or "en"
    examples, style_mode, note = style_service.pick_examples(conn, relationship, language)
    bits = _style_bits(examples, relationship)
    profile = style_service.get_profile(conn)
    facts = {k: v for k, v in (body.get("verified_facts") or {}).items() if v not in (None, "", [])}
    subject = ""
    to: list[str] = []
    if msg is not None and msg["direction"] == "inbound" and msg["source_type"] == "email":
        subject = msg["subject"] if msg["subject"].lower().startswith("re:") else f"Re: {msg['subject']}"
        m = ADDRESS_IN_LABEL.search(loads(msg["sender_json"], {}).get("label", ""))
        if m:
            to = [m.group(1).strip()]
    elif body.get("purpose") == "extension":
        subject = f"Extension request: {facts.get('task_title') or P['zh' if language == 'zh' else 'en']['task']}"
    elif body.get("purpose") == "followup":
        subject = "Follow-up" if language != "zh" else "讨论跟进"
    text = model_text or _compose(body["purpose"], language, facts, (msg["subject"] if msg else facts.get("task_title", "")),
                                  bits, profile["length_preference"] == "short")
    draft_id, ts = new_id("draft"), now_iso()
    attachments = _attachments(body.get("attachment_ids") or [])
    meta = {"relationship": relationship, "language": language, "style_mode": style_mode, "style_note": note,
            "profile_revision": profile["revision"], "generation": "model" if model_text else "template"}
    d = {"subject": subject, "body": text, "recipients": {"to": to, "cc": [], "bcc": []},
         "channel": body.get("channel", "email")}
    missing = _missing(d)
    conn.execute(
        """INSERT INTO drafts(id,source_message_id,purpose,channel,connection_id,recipients_json,subject,body,attachments_json,
           verified_facts_json,style_reference_ids_json,missing_fields_json,ready_for_review,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (draft_id, msg["id"] if msg else None, body["purpose"], d["channel"], body.get("connection_id"),
         dumps(d["recipients"]), subject, text, dumps(attachments), dumps({"facts": facts, "meta": meta}),
         dumps([e["message_id"] for e in examples]), dumps(missing), 0 if missing else 1, ts, ts))
    audit(conn, "draft_created", "draft", draft_id, {"purpose": body["purpose"], "style_mode": style_mode,
                                                     "missing": len(missing)})
    return get_draft(conn, draft_id)


def update_draft(conn: sqlite3.Connection, draft_id: str, body: dict) -> dict:
    row = conn.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
    if not row:
        raise not_found("draft")
    if row["revision"] != body.get("expected_revision"):
        raise conflict("REVISION_CONFLICT", "Draft changed elsewhere; reload", [f"current_revision={row['revision']}"])
    rec = loads(row["recipients_json"], {})
    for k in ("to", "cc", "bcc"):
        if body.get(k) is not None:
            rec[k] = [a.strip() for a in body[k] if a and a.strip()]
    subject = body["subject"] if body.get("subject") is not None else row["subject"]
    text = body["body"] if body.get("body") is not None else row["body"]
    attachments = _attachments(body["attachment_ids"]) if body.get("attachment_ids") is not None else loads(row["attachments_json"], [])
    vf = loads(row["verified_facts_json"], {})
    if body.get("verified_facts") is not None:
        vf["facts"] = {**vf.get("facts", {}), **body["verified_facts"]}
    if body.get("acknowledge_style_change"):
        vf.pop("_style_changed_at", None)
    if vf.get("_style_changed_at"):
        # Style references changed after this draft: the body stays, but the user must re-check it first.
        vf.setdefault("meta", {})["style_note"] = "style_changed_recheck"
    d = {"subject": subject, "body": text, "recipients": rec, "channel": row["channel"]}
    missing = _missing(d)
    if vf.get("_style_changed_at"):
        missing.append("style:recheck_after_reference_change")
    conn.execute(
        """UPDATE drafts SET recipients_json=?, subject=?, body=?, attachments_json=?, verified_facts_json=?,
           missing_fields_json=?, ready_for_review=?, revision=revision+1, updated_at=? WHERE id=?""",
        (dumps(rec), subject, text, dumps(attachments), dumps(vf), dumps(missing), 0 if missing else 1, now_iso(), draft_id))
    from .proposal_service import invalidate_for_source
    n = invalidate_for_source(conn, "draft", draft_id, "draft_edited")
    audit(conn, "draft_updated", "draft", draft_id, {"proposals_invalidated": n, "missing": len(missing)})
    return get_draft(conn, draft_id)


def validate_live_recipients(addresses: list[str]) -> list[str]:
    return [a for a in addresses if is_redacted_address(a)]


def require_draft_ready(d: dict) -> None:
    if not d["ready_for_review"] or d["placeholders"]:
        raise AppError(422, "DRAFT_INCOMPLETE", "Fill every placeholder before review", d["missing_fields"])
