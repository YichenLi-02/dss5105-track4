"""W01 import of the de-identified sample set (selected_50.jsonl + date_candidates.jsonl).

- 40 inbound samples feed the functional views; 10 outbound samples are style references only.
- Messages are keyed by (connection_id, provider_message_id): importing twice changes nothing.
- Labels come from AI-assisted annotations pending human review -> analysis_origin='reference_annotation'.
  They are never presented as model predictions or as a gold standard.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections import defaultdict
from pathlib import Path

from ..config import settings
from ..db import audit, dumps, loads, now_iso
from ..errors import AppError
from . import reference_view
from . import importance, ref_i18n
from .privacy import sha256_text
from .task_service import merge_candidates, _term_from_subject

LOCAL_CONNECTION_ID = "conn_local_jsonl"
_NS = uuid.UUID("7b4c8a52-55c4-4d1e-9a51-5105a0000004")


def message_uuid(connection_id: str, provider_id: str) -> str:
    return "msg_" + uuid.uuid5(_NS, f"{connection_id}:{provider_id}").hex[:20]


def ensure_local_connection(conn: sqlite3.Connection) -> None:
    ts = now_iso()
    conn.execute(
        """INSERT OR IGNORE INTO connections(id,provider,account_label,scopes_json,capabilities_json,status,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?,?)""",
        (LOCAL_CONNECTION_ID, "local_jsonl", "local samples", "[]",
         dumps({"read_mail": True, "send_mail": False, "real_account": False}), "connected", ts, ts),
    )


def _sample_files() -> tuple[Path, Path]:
    base = settings.sample_data_dir
    mails, dates = base / "selected_50.jsonl", base / "date_candidates.jsonl"
    if not mails.is_file():
        raise AppError(503, "SAMPLE_DATA_MISSING", "selected_50.jsonl not found under SAMPLE_DATA_DIR",
                       [str(base)])
    return mails, dates


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _analysis_for(row: dict, view: dict | None) -> dict:
    ann = row.get("annotation") or {}
    flags = list(ann.get("attention_flags") or [])
    if row.get("source_capture_capped") and "incomplete_body" not in flags:
        flags.append("incomplete_body")
    return {
        "source_id": row["sample_id"],
        "category": (view or {}).get("category"),
        "summary": (view or {}).get("summary") or ann.get("task_or_intent") or "",
        "needs_reply": ann.get("needs_reply"),
        "needs_action": ann.get("needs_action"),
        "important": bool((view or {}).get("important")),
        "attention_flags": flags,
        "attention_label": (view or {}).get("attentionLabel") or None,
        "uncertainty": ann.get("uncertainty") or "",
        "expected_behavior": ann.get("expected_behavior") or "",
        "evidence_hint": ann.get("evidence") or "",
        "optional_opportunities": ann.get("optional_opportunities") or [],
        "annotation_status": ann.get("status"),
        "candidates": [],
        "unknowns": [ann["uncertainty"]] if ann.get("uncertainty") else [],
    }


def import_selected_50(conn: sqlite3.Connection, job_id: str | None = None) -> dict:
    mails_path, dates_path = _sample_files()
    rows = _read_jsonl(mails_path)
    view = reference_view.mail_view()
    ensure_local_connection(conn)
    created = updated = unchanged = 0
    ts = now_iso()
    for row in rows:
        provider_id = f"selected_50:{row['sample_id']}"
        mid = message_uuid(LOCAL_CONNECTION_ID, provider_id)
        body = row.get("body_redacted") or ""
        body_hash = sha256_text(body)
        direction = "outbound" if row.get("direction") == "outbound" else "inbound"
        locator = {
            "dataset": "selected_50.jsonl", "sample_id": row["sample_id"],
            "original_mbox_ordinal_1based": row.get("original_mbox_ordinal_1based"),
            "split": row.get("split"), "case_group": row.get("case_group"), "scenario": row.get("scenario"),
            "provenance": row.get("provenance"), "evaluation_context": row.get("evaluation_context"),
            "attachment_content_read": row.get("attachment_content_read", False),
            "source_capture_capped": row.get("source_capture_capped", False),
        }
        if direction == "outbound":
            locator["style_annotation"] = row.get("style_annotation")
        attachments = [{"name": n, "content_read": False} for n in row.get("attachments_present") or []]
        existing = conn.execute("SELECT id, body_hash, excluded FROM messages WHERE id=?", (mid,)).fetchone()
        if existing and existing["excluded"]:
            unchanged += 1
            continue  # removed by the user: keep it removed
        analysis = _analysis_for(row, view.get(row["sample_id"])) if direction == "inbound" else None
        if existing and existing["body_hash"] == body_hash:
            unchanged += 1
            continue
        if existing:
            conn.execute(
                """UPDATE messages SET subject=?, body_view=?, body_hash=?, locator_json=?, revision=revision+1, updated_at=?
                   WHERE id=?""", (row.get("subject", ""), body, body_hash, dumps(locator), ts, mid))
            updated += 1
            continue
        conn.execute(
            """INSERT INTO messages(id,connection_id,provider_message_id,source_type,source_id,thread_id,direction,subject,
               sender_json,recipients_json,sent_at,source_timezone,body_view,body_hash,locator_json,attachments_json,
               analysis_status,analysis_origin,analysis_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (mid, LOCAL_CONNECTION_ID, provider_id, "email", row["sample_id"], row.get("case_group"), direction,
             row.get("subject", ""), dumps({"label": row.get("from_redacted", "")}),
             dumps({"to": [row.get("to_redacted", "")]}), row.get("message_datetime_original"), None, body,
             body_hash, dumps(locator), dumps(attachments),
             "reference" if analysis else "not_applicable",
             "reference_annotation" if analysis else "none", dumps(analysis) if analysis else None, ts, ts),
        )
        created += 1

    tasks_before = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    _import_date_candidates(conn, dates_path)
    tasks_after = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    result = {"messages_created": created, "messages_updated": updated, "messages_unchanged": unchanged,
              "inbound": sum(1 for r in rows if r.get("direction") != "outbound"),
              "outbound_style": sum(1 for r in rows if r.get("direction") == "outbound"),
              "tasks_created": tasks_after - tasks_before,
              "reference_view_loaded": bool(view)}
    audit(conn, "import_completed", "job", job_id, result)
    return result


def _import_date_candidates(conn: sqlite3.Connection, path: Path) -> None:
    by_entity: dict[str, list[dict]] = defaultdict(list)
    titles = reference_view.candidate_titles()
    for c in _read_jsonl(path):
        msg = conn.execute("SELECT id, direction, subject FROM messages WHERE connection_id=? AND source_id=?",
                           (LOCAL_CONNECTION_ID, c["sample_id"])).fetchone()
        if not msg or msg["direction"] != "inbound":
            continue  # outbound samples are style references, never task sources
        c = dict(c, message_id=msg["id"], source_id=c["sample_id"], origin="reference_annotation",
                 _subject=msg["subject"])
        by_entity[c["entity_key"]].append(c)
    for key, cands in by_entity.items():
        term = next((t for t in (_term_from_subject(c["_subject"]) for c in cands) if t), None)
        merge_candidates(conn, key, cands, title=titles.get(key), course=None, term=term,
                         origin="reference_annotation")


# ---------------------------------------------------------------- read views

def mail_language(subject: str, body: str) -> str:
    """'zh' if the mail is mostly Chinese, else 'en' - used so English mail keeps an English summary."""
    text = (subject or "") + " " + (body or "")[:800]
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
    return "zh" if cjk >= max(5, letters * 0.1) else "en"


def message_summary(row: sqlite3.Row, threshold: float = importance.DEFAULT_THRESHOLD) -> dict:
    a = loads(row["analysis_json"], None) or {}
    sender = loads(row["sender_json"], {})
    reply, action = a.get("needs_reply"), a.get("needs_action")
    en = ref_i18n.mail(row["source_id"]) if row["analysis_origin"] == "reference_annotation" else {}
    imp, imp_reason, imp_params = importance.evaluate(a, threshold, row["subject"]) if a else (False, None, {})
    return {
        "id": row["id"], "source_id": row["source_id"], "direction": row["direction"],
        "source_type": row["source_type"], "subject": row["subject"], "sent_at": row["sent_at"],
        "sender_label": sender.get("label", ""), "category": a.get("category"),
        "summary": a.get("summary", ""), "needs_reply": reply, "needs_action": action,
        "ignore": None if reply is None or action is None else (not reply and not action),
        "important": imp, "important_reason": imp_reason, "important_params": imp_params,
        "attention_flags": a.get("attention_flags", []),
        "attention_flags_en": a.get("attention_flags_en") or None,
        "attention_label": a.get("attention_label"), "uncertainty": a.get("uncertainty", ""),
        "summary_en": en.get("summary") or a.get("summary_en"), "uncertainty_en": en.get("uncertainty"),
        "attention_label_en": en.get("label") or None,
        "analysis_origin": row["analysis_origin"], "analysis_status": row["analysis_status"],
        "excluded": bool(row["excluded"]), "revision": row["revision"],
        "is_demo": row["connection_id"].startswith("conn_local"),
        "mail_language": mail_language(row["subject"], row["body_view"]),
        "account_security": importance.is_account_security(a, row["subject"]) if a else False,
        "attachment_count": len(loads(row["attachments_json"], [])),
        "split": loads(row["locator_json"], {}).get("split"),
    }


def message_detail(row: sqlite3.Row, threshold: float = importance.DEFAULT_THRESHOLD) -> dict:
    d = message_summary(row, threshold)
    locator = loads(row["locator_json"], {})
    d.update({
        "body_view": row["body_view"], "source_timezone": row["source_timezone"],
        "recipients": loads(row["recipients_json"], {}),
        "attachments": loads(row["attachments_json"], []),
        "provenance": {k: locator.get(k) for k in ("dataset", "sample_id", "original_mbox_ordinal_1based", "split",
                                                    "case_group", "provenance", "evaluation_context",
                                                    "source_capture_capped", "attachment_content_read") if k in locator},
        "analysis": loads(row["analysis_json"], None),
        "expected_en": (ref_i18n.mail(row["source_id"]).get("expected")
                        if row["analysis_origin"] == "reference_annotation" else None),
    })
    return d
