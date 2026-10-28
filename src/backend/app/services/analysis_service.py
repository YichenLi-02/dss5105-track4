"""W02 model analysis (only when enabled). One structured call per message; results are checked
locally and failures leave the message intact as analysis_failed. Annotations are never sent."""
from __future__ import annotations

import hashlib
import re
from datetime import date

from ..config import settings
from ..db import dumps, loads, now_iso, transaction
from ..errors import AppError
from ..llm import adapter
from .task_service import merge_candidates

MAX_BODY_CHARS = 8000


def minimized(row) -> dict:
    """Only what the model needs: no annotation, no split label, no later replies, no addresses."""
    return {"source_id": row["source_id"], "subject": row["subject"], "body": row["body_view"][:MAX_BODY_CHARS],
            "sent_at": row["sent_at"], "source_timezone": row["source_timezone"]}


_ZONE_ALIASES = {"SGT": "Asia/Singapore", "SST": "Asia/Singapore", "HKT": "Asia/Hong_Kong", "CST_CN": "Asia/Shanghai",
                 "JST": "Asia/Tokyo", "KST": "Asia/Seoul", "UTC": "UTC", "GMT": "UTC", "MST": "UTC-07:00",
                 "PST": "UTC-08:00", "PDT": "UTC-07:00", "EST": "UTC-05:00", "EDT": "UTC-04:00", "BST": "UTC+01:00"}


def normalize(result: dict) -> dict:
    """Deterministic clean-up of model formats: 12h -> HH:MM, zone abbreviations -> zone names.
    Anything not confidently convertible becomes null plus an 'unknowns' note (never guessed)."""
    from .task_service import parse_zone
    for c in result.get("candidates", []):
        t = (c.get("time") or "").strip()
        m = re.fullmatch(r"(?i)(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?", t)
        if m and 1 <= int(m.group(1)) <= 12:
            c["time"] = f"{int(m.group(1)) % 12 + (12 if m.group(3).lower() == 'p' else 0):02d}:{m.group(2) or '00'}"
        elif re.fullmatch(r"\d{1,2}:\d{2}", t):
            c["time"] = f"{int(t.split(':')[0]):02d}:{t.split(':')[1]}"
        elif t:
            result.setdefault("unknowns", []).append(f"time not normalised: {t}")
            c["time"] = None
        z = (c.get("timezone") or "").strip()
        if z:
            zone = _ZONE_ALIASES.get(z.upper(), z)
            if parse_zone(zone) is None:
                result.setdefault("unknowns", []).append(f"time zone needs review: {z}")
                zone = None
            c["timezone"] = zone
    return result


def check(result: dict, payload: dict) -> list[str]:
    errs = []
    if result.get("source_id") != payload["source_id"]:
        errs.append("unexpected_source_id")
    for c in result.get("candidates", []):
        for e in c.get("evidence", []):
            text = payload["subject"] if e.get("field") == "subject" else payload["body"]
            if e.get("source_id") != payload["source_id"] or e.get("quote", "") not in text or not e.get("quote"):
                errs.append(f"quote_not_in_source:{e.get('quote', '')[:40]}")
        if c.get("date"):
            try:
                date.fromisoformat(c["date"])
            except ValueError:
                errs.append(f"bad_date:{c['date']}")
        if c.get("time") and not re.fullmatch(r"\d{2}:\d{2}", c["time"]):
            errs.append(f"bad_time:{c['time']}")
    return errs


def cache_key(row) -> str:
    return hashlib.sha256(f"{row['body_hash']}|{adapter.PROMPT_VERSION}|{adapter.SCHEMA_VERSION}|{settings.openai_model}"
                          .encode()).hexdigest()


def run(ctx, payload: dict) -> dict:
    conn = ctx.conn
    adapter.require_enabled(conn)
    ids = payload["message_ids"]
    done = failed = cached = 0
    for i, mid in enumerate(ids):
        row = conn.execute("SELECT * FROM messages WHERE id=? AND direction='inbound'", (mid,)).fetchone()
        if not row:
            continue
        key = cache_key(row)
        if row["analysis_cache_key"] == key and row["analysis_origin"] == "model" and not payload.get("force"):
            cached += 1
            ctx.progress(i + 1, len(ids))
            continue
        p = minimized(row)
        try:
            result, usage = adapter.structured_call(adapter.BOUNDARY, p, adapter.MAIL_ANALYSIS, "mail_analysis")
            errs = check(normalize(result), p)
            if errs:  # one format-repair retry is allowed by the design; evidence errors are not "repaired"
                raise AppError(502, "MODEL_EVIDENCE_INVALID", "Model output failed local checks", errs)
        except AppError as e:
            failed += 1
            ctx.error(f"{row['source_id']}: {e.code}")
            with transaction(conn):
                conn.execute("UPDATE messages SET analysis_status='analysis_failed', updated_at=? WHERE id=?", (now_iso(), mid))
                conn.execute("UPDATE jobs SET failed_count=failed_count+1 WHERE id=?", (ctx.job_id,))
            ctx.progress(i + 1, len(ids))
            continue
        if len(result.get("attention_flags_en") or []) != len(result.get("attention_flags") or []):
            result["attention_flags_en"] = []
        prev = loads(row["analysis_json"], None)
        result.update({"model": settings.openai_model,
                       "prompt_version": adapter.PROMPT_VERSION, "schema_version": adapter.SCHEMA_VERSION,
                       "usage": {k: usage.get(k) for k in ("input_tokens", "output_tokens", "total_tokens")},
                       "previous_reference": prev if row["analysis_origin"] == "reference_annotation" else None})
        with transaction(conn):
            conn.execute("""UPDATE messages SET analysis_json=?, analysis_origin='model', analysis_status='complete',
                            analysis_cache_key=?, revision=revision+1, updated_at=? WHERE id=?""",
                         (dumps(result), key, now_iso(), mid))
            # Promotions never become tasks (coupon expiry is not student work).
            cands = [] if result.get("category") == "promotions" else result.get("candidates", [])
            for n, c in enumerate(cands):
                ev = c["evidence"][0] if c["evidence"] else {"quote": c["title"], "field": "subject"}
                merge_candidates(conn, f"model_{row['source_id']}_{n}", [{
                    "candidate_id": f"{row['source_id']}:model:{n}", "message_id": mid, "source_id": row["source_id"],
                    "kind": "submission_deadline" if c["status"] != "completed" else "deadline_in_completed_receipt",
                    "official_date_candidate": c["date"], "official_time_candidate": c["time"], "timezone": c["timezone"],
                    "status": "model_candidate", "origin": "model", "interpretation_note": "model candidate; needs review",
                    "evidence": {"quote": ev["quote"], "field": ev["field"]}}],
                    title=c["title"], title_en=c.get("title_en"), course=c["course"], term=None, origin="model")
        done += 1
        ctx.progress(i + 1, len(ids))
    return {"analysed": done, "failed": failed, "cached": cached}


def needs_flag_translation(a: dict | None, origin: str | None) -> bool:
    flags = (a or {}).get("attention_flags") or []
    return origin == "model" and bool(flags) and len((a or {}).get("attention_flags_en") or []) != len(flags)


def pending_translations(conn) -> tuple[list, list]:
    """Older model output that is in one language only: flag notes on mail, titles of model-made tasks."""
    msgs = [r for r in conn.execute("SELECT * FROM messages WHERE analysis_origin='model'")
            if needs_flag_translation(loads(r["analysis_json"], None), r["analysis_origin"])]
    tasks = conn.execute("SELECT id, title FROM tasks WHERE substr(entity_key, 1, 6)='model_' AND title_en IS NULL").fetchall()
    return msgs, list(tasks)


def translate_pending(ctx, payload: dict | None = None) -> dict:
    """Job body: give older model output an English copy. Only the short notes/titles are sent, never mail text."""
    conn = ctx.conn if hasattr(ctx, "conn") else ctx
    adapter.require_enabled(conn)
    msgs, tasks = pending_translations(conn)
    msgs, tasks = msgs[:100], tasks[:100]
    items = [{"id": f"m{n}:{k}", "text": f} for n, r in enumerate(msgs)
             for k, f in enumerate(loads(r["analysis_json"], {})["attention_flags"])]
    items += [{"id": f"t{n}", "text": t["title"]} for n, t in enumerate(tasks)]
    if not items:
        return {"flags": 0, "titles": 0}
    out, _ = adapter.structured_call(adapter.FLAG_BOUNDARY, {"items": items}, adapter.FLAG_TRANSLATION, "label_translation")
    got = {x["id"]: x for x in out.get("items", []) if x.get("zh", "").strip() and x.get("en", "").strip()}
    n_flags = n_titles = 0
    with transaction(conn):
        for n, r in enumerate(msgs):
            a = loads(r["analysis_json"], {})
            pairs = [got.get(f"m{n}:{k}") for k in range(len(a["attention_flags"]))]
            if not all(pairs):  # partial answers are not mixed in
                continue
            a["attention_flags_original"] = a["attention_flags"]
            a["attention_flags"] = [p["zh"] for p in pairs]
            a["attention_flags_en"] = [p["en"] for p in pairs]
            conn.execute("UPDATE messages SET analysis_json=?, revision=revision+1, updated_at=? WHERE id=?",
                         (dumps(a), now_iso(), r["id"]))
            n_flags += 1
        for n, t in enumerate(tasks):  # the stored title stays as it was; only the English copy is added
            if got.get(f"t{n}"):
                conn.execute("UPDATE tasks SET title_en=? WHERE id=? AND title=?",
                             (got[f"t{n}"]["en"][:200], t["id"], t["title"]))
                n_titles += 1
    return {"flags": n_flags, "titles": n_titles}
