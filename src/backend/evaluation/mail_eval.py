"""Mail triage and deadline-extraction evaluation.

The mail goes through the real pipeline - sync, minimisation, storage, model analysis, task merge - inside an
isolated database, and what the student would then see (labels on each mail, tasks in the task list) is scored
against an answer key that the system never reads.

Two mail sets share one scorer:
  synthetic  data/synthetic/mail_eval_v1 (80 fictional mails), served to the app through a simulated Gmail API;
  samples    the 40 de-identified inbound samples already in the repository, imported the normal way. Their labels
             are AI-assisted drafts that nobody has reviewed yet, so every number on them is provisional.

Predictions are saved first and scored afterwards, so the scoring can be re-run or corrected without calling the
model again. Nothing here changes the app: prompts, rules and thresholds are used exactly as shipped.
"""
from __future__ import annotations

import base64
import json
import math
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
TRANSIENT = {"MODEL_UNREACHABLE", "MODEL_RATE_LIMITED", "MODEL_HTTP_ERROR"}
ROLE_ORDER = {"deadline": 0, "completed": 1, "optional": 2, "non_task": 3}
LABELS = ("needs_reply", "needs_action")
CATEGORIES = ("academic", "career", "events", "promotions", "other")

# ================================================================ answer keys


def load_synthetic(folder: Path) -> tuple[list[dict], dict]:
    messages = [json.loads(line) for line in (folder / "messages.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    key = json.loads((folder / "labels.json").read_text(encoding="utf-8"))
    key["verified"] = False
    key["label_status"] = "correct by construction (written with each mail, frozen before the first run); not yet reviewed by a human"
    return messages, key


SAMPLE_NON_TASK_KINDS = {"class_event", "graded_timestamp", "promotion_expiry", "security_token_lifetime",
                         "order_placed_timestamp", "meeting_time_conflict", "meeting_time_correction"}
SAMPLE_UNSETTLED = {"conflict_weekday_date", "subject_body_conflict", "unresolved_source_timezone",
                    "relative_semantics_need_confirmation", "no_exact_date"}


def _sample_item(c: dict, sent: str | None) -> dict:
    kind, status = c["kind"], c.get("status") or ""
    d, t, t2 = c.get("official_date_candidate"), c.get("official_time_candidate"), c.get("window_end_time_candidate")
    quote = (c.get("evidence") or {}).get("quote")
    anchors = [quote] if quote else []
    if kind in SAMPLE_NON_TASK_KINDS or status in ("non_task_expiry", "non_deadline"):
        return {"role": "non_task", "kind": kind, "date": d, "time": t, "anchors": anchors}
    if kind == "deadline_in_completed_receipt" or status in ("explicit_but_task_completed", "completed_record") \
            or c.get("pending_task_at_receipt") is False:
        return {"role": "completed", "deadline_id": c["entity_key"], "date": d, "time": t, "anchors": anchors}
    if kind == "conditional_deadline":
        return {"role": "optional", "date": d, "time": t, "anchors": anchors}
    dates = [d]
    if d is None or status in SAMPLE_UNSETTLED:
        dates.append(None)
    if d is None and status == "unresolved_source_timezone" and sent:
        # "due today" in a mail whose local sending day is unknown: either calendar day or "unknown" is acceptable
        utc = datetime.fromisoformat(sent.replace("Z", "+00:00")).date()
        dates += [utc.isoformat(), (utc - timedelta(days=1)).isoformat()]
    return {"role": "deadline", "deadline_id": c["entity_key"], "date": d, "time": t, "timezone": c.get("timezone"),
            "accept_dates": list(dict.fromkeys(dates)), "accept_times": [x for x in (t, t2) if x] or [None],
            "current": True, "anchors": anchors}


def load_samples(folder: Path) -> dict:
    """The de-identified sample set as an answer key of the same shape. Labels are whatever is in the files."""
    rows = [json.loads(line) for line in (folder / "selected_50.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    view_path = folder / "reference_view.json"
    view = {m["id"]: m for m in json.loads(view_path.read_text(encoding="utf-8")).get("mail", [])} if view_path.is_file() else {}
    by: dict[str, list[dict]] = defaultdict(list)
    cand_path = folder / "date_candidates.jsonl"
    if cand_path.is_file():
        for line in cand_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                c = json.loads(line)
                by[c["sample_id"]].append(c)
    inbound = [r for r in rows if r.get("direction") == "inbound"]
    messages = {}
    for r in inbound:
        ann = r.get("annotation") or {}
        sid = r["sample_id"]
        messages[sid] = {
            "category": (view.get(sid) or {}).get("category"), "needs_reply": ann.get("needs_reply"),
            "needs_action": ann.get("needs_action"), "difficulty": None, "language": "en", "split": r.get("split"),
            "tags": [r["scenario"]] if r.get("scenario") else [],
            "items": [_sample_item(c, r.get("message_datetime_original")) for c in by.get(sid, [])], "secrets": []}
    statuses = Counter((r.get("annotation") or {}).get("status") for r in inbound)
    verified = set(statuses) == {"human_reviewed"}
    return {"version": "selected_50 (de-identified real mail)", "verified": verified,
            "label_status": "human reviewed" if verified else
            f"NOT verified - annotation status in the files: {dict(statuses)}; treat every number as provisional",
            "messages": messages}


# ================================================================ driving the real pipeline (needs the app)


class Api:
    """The same HTTP API the browser uses, in process."""

    def __init__(self, client):
        self.c = client
        r = client.post("/api/session", json={})
        r.raise_for_status()
        self.h = {"X-CSRF-Token": r.json()["csrf_token"]}

    def get(self, url: str):
        r = self.c.get(url)
        r.raise_for_status()
        return r.json()

    def post(self, url: str, body: dict | None = None):
        r = self.c.post(url, json=body or {}, headers=self.h)
        if r.status_code >= 400:
            raise RuntimeError(f"POST {url} -> {r.status_code} {r.text[:300]}")
        return r.json()

    def patch(self, url: str, body: dict):
        r = self.c.patch(url, json=body, headers=self.h)
        if r.status_code >= 400:
            raise RuntimeError(f"PATCH {url} -> {r.status_code} {r.text[:300]}")
        return r.json()


def _gmail_message(m: dict) -> dict:
    return {"id": m["id"], "threadId": m.get("thread_id"), "labelIds": m.get("label_ids", ["INBOX"]),
            "payload": {"mimeType": "text/plain",
                        "headers": [{"name": "Subject", "value": m["subject"]}, {"name": "From", "value": m["from"]},
                                    {"name": "To", "value": m["to"]},
                                    {"name": "Date", "value": format_datetime(datetime.fromisoformat(m["sent_at"]))}],
                        "body": {"data": base64.urlsafe_b64encode(m["body"].encode("utf-8")).decode()}}}


class MailboxRouter(httpx.BaseTransport):
    """All outbound HTTP of the app goes through here during a run: the synthetic mailbox is served as the Gmail
    API (read-only), the configured model endpoint is let through, and anything else is refused and recorded."""

    def __init__(self, messages: list[dict], model_host: str | None):
        self.by_id = {m["id"]: m for m in messages}
        self.order = [m["id"] for m in sorted(messages, key=lambda m: m["sent_at"], reverse=True)]
        self.model_host = model_host
        self.real = httpx.HTTPTransport(retries=1)
        self.calls: Counter = Counter()
        self.refused: list[str] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "gmail.googleapis.com":
            if request.method != "GET":
                self.refused.append(f"{request.method} {host}{path}")
                return httpx.Response(405)
            self.calls["gmail_read"] += 1
            if path == "/gmail/v1/users/me/messages":
                return httpx.Response(200, json={"messages": [{"id": i} for i in self.order]})
            m = self.by_id.get(path.rsplit("/", 1)[1]) if path.startswith("/gmail/v1/users/me/messages/") else None
            return httpx.Response(200, json=_gmail_message(m)) if m else httpx.Response(404)
        if self.model_host and host == self.model_host:
            self.calls["model"] += 1
            return self.real.handle_request(request)
        self.refused.append(f"{request.method} {host}{path}")
        return httpx.Response(403)


def connect(messages: list[dict]) -> MailboxRouter:
    """Route the app's outbound HTTP and, when there is a synthetic mailbox, attach it as a read-only Gmail account.
    Tokens stay in memory: the operating-system credential store (where a real account's token may be) is never touched."""
    from app.config import settings
    from app.db import connect as db, dumps, now_iso
    from app.providers import net, tokens
    tokens.use_memory_store(True)
    router = MailboxRouter(messages, urlparse(settings.openai_base_url).hostname)
    net.set_transport(router)
    if messages:
        tokens.save("conn_google:token", {"access_token": "synthetic-mailbox", "expires_in": 10 ** 8,
                                          "obtained_at": int(time.time()), "token_type": "Bearer", "scope": GMAIL_READONLY})
        with db() as conn:
            conn.execute(
                """INSERT INTO connections(id,provider,account_label,scopes_json,credential_ref,status,created_at,updated_at)
                   VALUES('conn_google','google','synthetic mailbox',?,?,'connected',?,?)""",
                (dumps([GMAIL_READONLY]), "conn_google:token", now_iso(), now_iso()))
    return router


def sync_mailbox(api: Api, expected: int) -> dict:
    job = api.post("/api/sync-jobs", {"connection_id": "conn_google", "lookback_days": 90, "max_messages": 500,
                                      "include_spam_trash": False})
    job = api.get(f"/api/jobs/{job['id']}")
    if job["status"] != "completed" or (job.get("result") or {}).get("created") != expected:
        raise RuntimeError(f"sync did not store all {expected} mails: {job}")
    return job["result"]


def import_samples(api: Api) -> dict:
    job = api.post("/api/imports", {"source": "selected_50", "upload_id": None})
    job = api.get(f"/api/jobs/{job['id']}")
    if job["status"] != "completed":
        raise RuntimeError(f"sample import failed: {job}")
    return job["result"]


def enable_model(api: Api) -> dict:
    prefs = api.get("/api/preferences")
    api.patch("/api/preferences", {"expected_revision": prefs["revision"], "allow_model_processing": True})
    status = api.get("/api/model/status")
    if not status["enabled"]:
        raise RuntimeError(f"model processing is not available: {status['reasons']}")
    return status


def analyse(api: Api, batch: int = 8, log=print) -> dict:
    """Model analysis of every inbound mail through the app's own job endpoint. A failed mail is retried once, and
    only when the failure was a transport problem; mails the app rejected for bad evidence stay failed."""
    msgs = api.get("/api/messages?limit=500")["items"]
    sid_of = {m["id"]: m["source_id"] for m in msgs}
    ids = list(sid_of)
    errors: dict[str, str] = {}
    seconds = 0.0

    def go(chunk: list[str]) -> None:
        nonlocal seconds
        t0 = time.time()
        job = api.post("/api/analysis-jobs", {"message_ids": chunk, "force": False})
        job = api.get(f"/api/jobs/{job['id']}")
        seconds += time.time() - t0
        for e in job.get("errors") or []:
            sid, _, code = e.partition(": ")
            errors[sid] = code

    for i in range(0, len(ids), batch):
        go(ids[i:i + batch])
        log(f"  analysed {min(i + batch, len(ids))}/{len(ids)}  ({seconds:.0f}s, {len(errors)} failed so far)")
    first = dict(errors)
    retry = [mid for mid, sid in sid_of.items() if errors.get(sid) in TRANSIENT]
    if retry:
        for mid in retry:
            errors.pop(sid_of[mid], None)
        log(f"  retrying {len(retry)} mail(s) that failed on a transport error")
        for i in range(0, len(retry), batch):
            go(retry[i:i + batch])
    return {"messages": len(ids), "seconds": round(seconds, 1), "first_pass_errors": first, "errors": errors,
            "retried": len(retry)}


def collect(api: Api, errors: dict[str, str] | None = None) -> dict:
    """What the student sees after the run: labels on each mail and the model-made tasks in the task list."""
    errors = errors or {}
    by_msg: dict[str, list[dict]] = defaultdict(list)
    for t in api.get("/api/tasks")["items"]:
        key = t["entity_key"]
        if not key.startswith("model_"):
            continue
        sid, _, n = key[len("model_"):].rpartition("_")
        ev = t["evidence"][0] if t["evidence"] else {}
        by_msg[sid].append({
            "entity_key": key, "candidate_index": int(n) if n.isdigit() else None, "title": t["title"],
            "title_en": t.get("title_en"), "status": t["status"],
            "state": "done" if t["status"] == "completed" else "ignored" if t["status"] == "ignored" else "pending",
            "date": t["official_date"], "time": t["official_time"], "timezone": t["source_timezone"],
            "deadline_status": t["deadline_status"], "required": t["required"], "field": ev.get("field"),
            "quote": ev.get("quote"), "start": ev.get("start_char"), "end": ev.get("end_char")})
    out = {}
    for m in api.get("/api/messages?limit=500")["items"]:
        d = api.get(f"/api/messages/{m['id']}")
        sid = d["source_id"]
        from_model = d["analysis_origin"] == "model"
        a = (d.get("analysis") or {}) if from_model else {}
        cands = a.get("candidates") or []
        tasks = sorted(by_msg.get(sid, []), key=lambda t: t["candidate_index"] if t["candidate_index"] is not None else 99)
        for t in tasks:
            c = cands[t["candidate_index"]] if t["candidate_index"] is not None and t["candidate_index"] < len(cands) else {}
            t["model_status"], t["model_needs_review"] = c.get("status"), c.get("needs_review")
        out[sid] = {
            "source_id": sid, "sent_at": d.get("sent_at"), "analysis_origin": d["analysis_origin"],
            "analysis_status": d["analysis_status"], "error": errors.get(sid),
            "labels": {"needs_reply": a.get("needs_reply"), "needs_action": a.get("needs_action"),
                       "category": a.get("category")} if from_model else None,
            "summary": a.get("summary"), "summary_en": a.get("summary_en"),
            "attention_flags": a.get("attention_flags"), "account_security": d.get("account_security"),
            "important": d.get("important"), "amount": a.get("amount"), "currency": a.get("currency"),
            "unknowns": a.get("unknowns"), "candidates": cands, "usage": a.get("usage"),
            "subject": d["subject"], "body_view": d["body_view"], "sender_label": d.get("sender_label"), "tasks": tasks}
    return out


# ================================================================ scoring (pure: no app, no network)


def wilson(k: int, n: int) -> list[float] | None:
    """95% Wilson interval for k successes out of n."""
    if not n:
        return None
    z, p = 1.96, k / n
    mid, half = (p + z * z / (2 * n)) / (1 + z * z / n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, mid - half), 3), round(min(1.0, mid + half), 3)]


def rate(k: int, n: int) -> dict:
    return {"k": k, "n": n, "value": round(k / n, 3) if n else None, "ci95": wilson(k, n)}


def _find_all(text: str, needle: str) -> list[tuple[int, int]]:
    out, i = [], text.find(needle) if needle else -1
    while i >= 0:
        out.append((i, i + len(needle)))
        i = text.find(needle, i + 1)
    return out


def _item_spans(item: dict, subject: str, body: str) -> list[tuple[str, int, int]]:
    out = []
    for a in item.get("anchors") or []:
        out += [("body", s, e) for s, e in _find_all(body, a)] + [("subject", s, e) for s, e in _find_all(subject, a)]
    return out


def _task_spans(task: dict, candidates: list[dict], subject: str, body: str) -> list[tuple[str, int, int]]:
    """Where in the mail the task's evidence is. The task row keeps only the first quote the model gave (often the
    subject line), so every quote of the model candidate it came from is used as well."""
    out = []
    field = "subject" if task.get("field") == "subject" else "body"
    s, e = task.get("start"), task.get("end")
    if s is not None and e is not None:
        out.append((field, s, e))
    elif task.get("quote"):
        out += [(field, a, b) for a, b in _find_all(subject if field == "subject" else body, task["quote"])[:1]]
    idx = task.get("candidate_index")
    if idx is not None and idx < len(candidates):
        for ev in candidates[idx].get("evidence") or []:
            f = "subject" if ev.get("field") == "subject" else "body"
            out += [(f, a, b) for a, b in _find_all(subject if f == "subject" else body, ev.get("quote") or "")]
    return out


def _dates(item: dict) -> list:
    return item.get("accept_dates") or [item.get("date")]


def _times(item: dict) -> list:
    return item.get("accept_times") or [item.get("time")]


def _classify(task: dict, item: dict) -> tuple[str, str]:
    """(what the task turned out to be, what happened to the answer-key item)."""
    open_ = task["state"] == "pending"
    if item["role"] == "deadline":
        if not open_:
            return "deadline_closed", "closed"  # real open work shown as completed or ignored
        if task["date"] in _dates(item):
            return ("correct" if item.get("current", True) else "stale"), "hit"
        return ("date_missing", "date_missing") if task["date"] is None else ("wrong_date", "wrong_date")
    if not open_:
        return "not_open", "kept_closed"
    return {"optional": "optional_promoted", "non_task": "non_task_promoted", "completed": "completed_reopened"}[item["role"]], "promoted"


def score_message(gt: dict, pred: dict) -> dict:
    """Pair the tasks the system made from one mail with the answer-key items of that mail.

    A task and an item are paired when the dates agree or when the task's evidence overlaps the item's words in the
    mail; the best pairs are taken first (date and words, then date, then words). Each item is used once. If that
    leaves exactly one open task and exactly one required deadline in the mail, they are taken to be the same thing."""
    subject, body = pred.get("subject") or "", pred.get("body_view") or ""
    items, tasks = gt.get("items") or [], [dict(t) for t in pred.get("tasks") or []]
    ispans = [_item_spans(it, subject, body) for it in items]
    tspans = [_task_spans(t, pred.get("candidates") or [], subject, body) for t in tasks]

    def overlap(pi: int, gi: int) -> bool:
        return any(tf == f and s < te and ts < e for tf, ts, te in tspans[pi] for f, s, e in ispans[gi])

    def same_date(pi: int, gi: int) -> bool:
        return tasks[pi]["date"] is not None and tasks[pi]["date"] in _dates(items[gi])

    cands = []
    for pi, p in enumerate(tasks):
        for gi, g in enumerate(items):
            d, o = same_date(pi, gi), overlap(pi, gi)
            if d or o:
                same_time = p["time"] is not None and p["time"] in _times(g)
                cands.append(((d and o, d, o, same_time, -ROLE_ORDER[g["role"]]), -pi, -gi))
    used_p: dict[int, int] = {}
    used_g: dict[int, int] = {}
    for _, npi, ngi in sorted(cands, reverse=True):
        pi, gi = -npi, -ngi
        if pi not in used_p and gi not in used_g:
            used_p[pi], used_g[gi] = gi, pi
    left_p = [pi for pi, t in enumerate(tasks) if pi not in used_p and t["state"] == "pending"]
    left_g = [gi for gi, g in enumerate(items) if gi not in used_g and g["role"] == "deadline"]
    if len(left_p) == 1 and len(left_g) == 1:
        used_p[left_p[0]], used_g[left_g[0]] = left_g[0], left_p[0]

    item_out = [{"role": it["role"], "kind": it.get("kind"), "deadline_id": it.get("deadline_id"),
                 "current": it.get("current", True), "expected_dates": _dates(it), "expected_times": _times(it),
                 "expected_timezone": it.get("timezone"), "anchor": (it.get("anchors") or [None])[0],
                 "status": "missed" if it["role"] == "deadline" else "untouched", "task": None} for it in items]
    actionable = bool(gt.get("needs_reply") or gt.get("needs_action"))
    for pi, t in enumerate(tasks):
        t["item"] = None
        if pi in used_p:
            gi = used_p[pi]
            t["outcome"], item_out[gi]["status"] = _classify(t, items[gi])
            t["item"], item_out[gi]["task"] = gi, pi
            t["deadline_id"], t["item_role"], t["item_kind"] = items[gi].get("deadline_id"), items[gi]["role"], items[gi].get("kind")
            continue
        again = [gi for gi in range(len(items)) if same_date(pi, gi) or overlap(pi, gi)]
        if again and t["state"] == "pending":
            t["outcome"], t["item"], t["item_role"] = "duplicate_in_mail", again[0], items[again[0]]["role"]
        elif t["state"] != "pending":
            t["outcome"] = "not_open"
        elif t["date"]:
            t["outcome"] = "invented"
        else:
            t["outcome"] = "undated_extra" if actionable else "undated_spurious"
    return {"tasks": tasks, "items": item_out}


def _offset(name: str | None, day: str | None) -> int | str | None:
    if not name:
        return None
    m = re.fullmatch(r"UTC([+-])(\d{2}):(\d{2})", name)
    if m:
        return (1 if m.group(1) == "+" else -1) * (int(m.group(2)) * 60 + int(m.group(3)))
    try:
        y, mo, d = (int(x) for x in (day or "2026-01-01").split("-"))
        return int(datetime(y, mo, d, 12, tzinfo=ZoneInfo(name)).utcoffset().total_seconds() // 60)
    except Exception:  # noqa: BLE001 - an unknown zone name is simply not equal to anything
        return "?"


EVENT_KINDS = {"event_time", "class_event", "meeting_time_conflict", "meeting_time_correction"}
GOOD = ("correct", "stale", "duplicate_across_mails")  # the date stated in that mail was extracted correctly
FALSE_POSITIVES = ("wrong_date", "invented", "non_task_promoted", "optional_promoted", "completed_reopened", "stale",
                   "duplicate_across_mails", "duplicate_in_mail", "undated_spurious")


def score_deadlines(key: dict, preds: dict) -> dict:
    per = {sid: score_message(gt, preds.get(sid) or {}) for sid, gt in key["messages"].items()}
    first_seen: dict[str, str] = {}
    for sid in sorted(per, key=lambda s: ((preds.get(s) or {}).get("sent_at") or "", s)):
        for t in per[sid]["tasks"]:
            if t["outcome"] == "correct" and t.get("deadline_id"):
                if t["deadline_id"] in first_seen:
                    t["outcome"], t["first_seen_in"] = "duplicate_across_mails", first_seen[t["deadline_id"]]
                else:
                    first_seen[t["deadline_id"]] = sid

    tasks = [(sid, t) for sid, r in per.items() for t in r["tasks"]]
    items = [(sid, it) for sid, r in per.items() for it in r["items"]]
    pending = [(sid, t) for sid, t in tasks if t["state"] == "pending"]
    dated = [(sid, t) for sid, t in pending if t["date"]]
    req = [(sid, it) for sid, it in items if it["role"] == "deadline"]
    unique = {it["deadline_id"] for _, it in req}
    found = {it["deadline_id"] for _, it in req if it["status"] == "hit" and it["current"]}
    failed = sorted(sid for sid in key["messages"] if not (preds.get(sid) or {}).get("labels"))

    time_c: Counter = Counter()
    tz_c: Counter = Counter()
    for sid, t in pending:
        if t["outcome"] not in GOOD or t.get("item") is None:
            continue
        it = per[sid]["items"][t["item"]]
        times = it["expected_times"]
        if t["time"] in times:
            time_c["time_as_expected"] += 1
        elif t["time"] is None:
            time_c["time_missing"] += 1
        elif all(x is None for x in times):
            time_c["time_invented"] += 1
            time_c["time_invented_2359"] += t["time"] == "23:59"
        else:
            time_c["time_wrong"] += 1
        want, got = it["expected_timezone"], t["timezone"]
        if not want:
            tz_c["none_stated_none_given" if not got else "none_stated_but_given"] += 1
        elif not got:
            tz_c["stated_but_missing"] += 1
        else:
            tz_c["stated_and_right" if _offset(want, t["date"]) == _offset(got, t["date"]) else "stated_but_wrong"] += 1

    def bucket(role: str) -> dict:
        rows = [(sid, it) for sid, it in items if it["role"] == role]
        out = {"total": len(rows), "became_open_task": sum(it["status"] == "promoted" for _, it in rows)}
        if role == "non_task":
            kinds: dict[str, list[int]] = defaultdict(lambda: [0, 0])
            for _, it in rows:
                kinds[it["kind"] or "?"][1] += 1
                kinds[it["kind"] or "?"][0] += it["status"] == "promoted"
            out["by_kind"] = {k: {"became_open_task": a, "total": b} for k, (a, b) in sorted(kinds.items())}
        return out

    groups: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for sid, it in req:
        gt = key["messages"][sid]
        tags = [("difficulty", gt.get("difficulty")), ("language", gt.get("language")), ("category", gt.get("category")),
                ("split", gt.get("split"))] + [("tag", x) for x in gt.get("tags") or []]
        for dim, val in tags:
            if val is not None:
                groups[dim][val][1] += 1
                groups[dim][val][0] += it["status"] == "hit"

    failures = []
    for sid, it in req:
        if it["status"] != "hit":
            t = per[sid]["tasks"][it["task"]] if it["task"] is not None else None
            failures.append({"kind": "missed_deadline", "detail": it["status"], "mail": sid, "deadline_id": it["deadline_id"],
                             "expected_dates": it["expected_dates"], "expected_times": it["expected_times"],
                             "anchor": it["anchor"], "analysis_failed": sid in failed,
                             "got": {k: t.get(k) for k in ("title", "date", "time", "state", "model_status", "quote")} if t else None})
    for sid, t in tasks:
        if t["outcome"] in FALSE_POSITIVES:
            it = per[sid]["items"][t["item"]] if t.get("item") is not None else None
            failures.append({"kind": "false_task", "detail": t["outcome"], "mail": sid,
                             "task": {k: t.get(k) for k in ("title", "title_en", "date", "time", "timezone", "model_status", "quote")},
                             "item": {k: it.get(k) for k in ("role", "kind", "deadline_id", "expected_dates", "anchor")} if it else None,
                             "first_seen_in": t.get("first_seen_in")})

    n_ok = sum(t["outcome"] in GOOD for _, t in dated)
    n_list = sum(t["outcome"] == "correct" for _, t in dated)
    # Added after the first results, as a second reading only: the largest group of false tasks is "attend <event>".
    # The answer key (following the project's own rules) says an event time is not a task; this shows what precision
    # would be for a reader who accepts such tasks. The primary numbers above are unchanged.
    n_event = sum(t["outcome"] == "non_task_promoted" and t.get("item_kind") in EVENT_KINDS for _, t in dated)
    return {
        "answer_key": {"required_mentions": len(req), "required_unique": len(unique),
                       "optional": sum(it["role"] == "optional" for _, it in items),
                       "non_task": sum(it["role"] == "non_task" for _, it in items),
                       "completed": sum(it["role"] == "completed" for _, it in items),
                       "mails_with_required_deadline": len({sid for sid, _ in req})},
        "system_output": {"tasks": len(tasks), "open": len(pending), "open_with_date": len(dated),
                          "open_without_date": len(pending) - len(dated),
                          "closed": len(tasks) - len(pending), "mails_analysis_failed": failed},
        "recall_per_mail": rate(sum(it["status"] == "hit" for _, it in req), len(req)),
        "recall_unique": rate(len(found), len(unique)),
        "precision_per_mail": rate(n_ok, len(dated)),
        "precision_task_list": rate(n_list, len(dated)),
        "if_event_tasks_were_accepted": {"dated_event_tasks": n_event, "precision_per_mail": rate(n_ok + n_event, len(dated)),
                                         "precision_task_list": rate(n_list + n_event, len(dated))},
        "missed_breakdown": dict(Counter(it["status"] for _, it in req if it["status"] != "hit")),
        "open_task_outcomes": dict(Counter(t["outcome"] for _, t in pending)),
        "closed_task_outcomes": dict(Counter(t["outcome"] for _, t in tasks if t["state"] != "pending")),
        "optional": bucket("optional"), "non_task": bucket("non_task"), "completed": bucket("completed"),
        "time_of_day": dict(time_c), "timezone": dict(tz_c),
        "recall_by_group": {dim: {val: rate(a, b) for val, (a, b) in sorted(vals.items())} for dim, vals in groups.items()},
        "failures": failures, "per_mail": per,
    }


def _cls(reply: bool, action: bool) -> str:
    return "reply+action" if reply and action else "reply" if reply else "action" if action else "ignore"


def score_triage(key: dict, preds: dict) -> dict:
    """needs_reply and needs_action are scored separately and together. A mail the system could not analyse has no
    label: it counts as 'not flagged' for each label and as wrong for exact match and category."""
    conf = {k: Counter() for k in LABELS}
    matrix: dict[str, Counter] = defaultdict(Counter)
    cat_matrix: dict[str, Counter] = defaultdict(Counter)
    groups: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))  # exact, n, category right, n with category
    wrong, no_output, exact, n, cat_ok, cat_n = [], [], 0, 0, 0, 0
    for sid, gt in key["messages"].items():
        if not isinstance(gt.get("needs_reply"), bool) or not isinstance(gt.get("needs_action"), bool):
            continue
        lab = (preds.get(sid) or {}).get("labels")
        has = bool(lab) and all(isinstance(lab.get(k), bool) for k in LABELS)
        if not has:
            no_output.append(sid)
        for k in LABELS:
            truth, pred = gt[k], bool(has and lab[k])
            conf[k][("T" if truth == pred else "F") + ("P" if pred else "N")] += 1
        want = _cls(gt["needs_reply"], gt["needs_action"])
        got = _cls(lab["needs_reply"], lab["needs_action"]) if has else "no output"
        matrix[want][got] += 1
        n += 1
        ok = want == got
        exact += ok
        cat_right = None
        if gt.get("category"):
            got_cat = (lab or {}).get("category") or "no output"
            cat_matrix[gt["category"]][got_cat] += 1
            cat_n += 1
            cat_right = got_cat == gt["category"]
            cat_ok += cat_right
        for dim in ("category", "difficulty", "language", "split"):
            if gt.get(dim) is not None:
                g = groups[dim][gt[dim]]
                g[0] += ok
                g[1] += 1
                if cat_right is not None:
                    g[2] += cat_right
                    g[3] += 1
        if not ok or cat_right is False:
            wrong.append({"mail": sid, "expected": want, "got": got, "expected_category": gt.get("category"),
                          "got_category": (lab or {}).get("category"), "difficulty": gt.get("difficulty"),
                          "tags": gt.get("tags"), "summary_en": (preds.get(sid) or {}).get("summary_en"),
                          "error": (preds.get(sid) or {}).get("error")})

    def prf(c: Counter) -> dict:
        tp, fp, fn, tn = c["TP"], c["FP"], c["FN"], c["TN"]
        p, r = rate(tp, tp + fp), rate(tp, tp + fn)
        f1 = round(2 * tp / (2 * tp + fp + fn), 3) if 2 * tp + fp + fn else None
        return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "precision": p, "recall": r, "f1": f1}

    truth_ignore = sum(matrix["ignore"].values())
    return {
        "mails": n, "no_output": no_output,
        "labels": {k: prf(conf[k]) for k in LABELS},
        "exact_match": rate(exact, n),
        "ignore": {"correctly_ignored": rate(matrix["ignore"]["ignore"], truth_ignore),
                   "needed_attention_but_ignored": rate(sum(matrix[w]["ignore"] for w in matrix if w != "ignore"), n - truth_ignore)},
        "confusion": {w: dict(c) for w, c in matrix.items()},
        "category_accuracy": rate(cat_ok, cat_n),
        "category_confusion": {w: dict(c) for w, c in cat_matrix.items()},
        "by_group": {dim: {val: {"exact_match": rate(g[0], g[1]), "category": rate(g[2], g[3])}
                           for val, g in sorted(vals.items())} for dim, vals in groups.items()},
        "wrong": wrong,
    }


def score_privacy(key: dict, preds: dict) -> dict:
    """Did the addresses, links, phone numbers, codes and long IDs planted in the synthetic mail survive into what
    the app stored (and would send to the model)?"""
    planted, leaked = 0, []
    for sid, gt in key["messages"].items():
        p = preds.get(sid) or {}
        text = " ".join(str(p.get(k) or "") for k in ("subject", "body_view", "sender_label"))
        for secret in gt.get("secrets") or []:
            planted += 1
            if secret in text:
                leaked.append({"mail": sid, "kind": "address" if "@" in secret else "link" if secret.startswith("http") else "number or code"})
    return {"planted": planted, "removed": rate(planted - len(leaked), planted), "still_present": leaked}


# ================================================================ baselines (fixed before the first run)

BASE_REPLY = re.compile(r"(?i)\b(please reply|reply to this email|reply by|let me know|could you|can you|please confirm|"
                        r"confirm that|which day|suit you)\b|请.{0,12}回复|告诉我|能参加吗|你能.{0,10}吗")
BASE_ACTION = re.compile(r"(?i)\b(due|deadline|submit|complete|upload|re-upload|pay|renew|sign up|book|must|required|expires?)\b|"
                         r"截止|提交|登记|完成")
_MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_MON = "jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec"
_B_DATES = [
    (re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b"), "num"),
    (re.compile(rf"(?i)\b(?P<d>\d{{1,2}})\s+(?P<mon>{_MON})[a-z]*\.?(?:\s+(?P<y>\d{{4}}))?"), "name"),
    (re.compile(rf"(?i)\b(?P<mon>{_MON})[a-z]*\.?\s+(?P<d>\d{{1,2}})\b(?:,?\s+(?P<y>\d{{4}}))?"), "name"),
    (re.compile(r"(?P<m>\d{1,2})月(?P<d>\d{1,2})日"), "num"),
]
_B_CUE = re.compile(r"(?i)\b(due|deadline|by|before|until|closes?|expires?|submit)\b|截止|前")
_B_TIME = re.compile(r"(?i)\b(?P<h>\d{1,2}):(?P<mi>\d{2})\b(?:\s*(?P<ap1>am|pm))?|\b(?P<h2>\d{1,2})\s*(?P<ap2>am|pm)\b|\b(?P<noon>noon)\b")


def _b_time(text: str) -> str | None:
    m = _B_TIME.search(text)
    if not m:
        return None
    if m.group("noon"):
        return "12:00"
    h, mi, ap = (int(m.group("h")), m.group("mi"), m.group("ap1")) if m.group("h") else (int(m.group("h2")), "00", m.group("ap2"))
    if ap:
        h = h % 12 + (12 if ap.lower() == "pm" else 0)
    return f"{h:02d}:{mi}" if 0 <= h < 24 else None


def baseline_predictions(preds: dict) -> dict:
    """What a keyword-and-regex tool would produce from exactly the text the model saw: flag reply/action by
    keyword; turn every written date on a line with a deadline word into an open task. No relative dates."""
    out = {}
    for sid, p in preds.items():
        subject, body = p.get("subject") or "", p.get("body_view") or ""
        text = subject + "\n" + body
        year = int((p.get("sent_at") or "2026")[:4])
        tasks, pos = [], 0
        for line in body.split("\n"):
            if _B_CUE.search(line):
                for rx, kind in _B_DATES:
                    for m in rx.finditer(line):
                        g = m.groupdict()
                        mo = _MONTHS[g["mon"].lower()[:3]] if kind == "name" else int(g["m"])
                        try:
                            day = datetime(int(g.get("y") or year), mo, int(g["d"])).date().isoformat()
                        except ValueError:
                            continue
                        tasks.append({"title": line.strip()[:80], "state": "pending", "status": "needs_review", "date": day,
                                      "time": _b_time(line[m.end():]), "timezone": None, "field": "body_view",
                                      "quote": m.group(0), "start": pos + m.start(), "end": pos + m.end()})
            pos += len(line) + 1
        seen, uniq = set(), []
        for t in tasks:  # one task per date and position
            if (t["date"], t["start"]) not in seen:
                seen.add((t["date"], t["start"]))
                uniq.append(t)
        out[sid] = {**{k: p.get(k) for k in ("source_id", "sent_at", "subject", "body_view", "sender_label")},
                    "labels": {"needs_reply": bool(BASE_REPLY.search(text)), "needs_action": bool(BASE_ACTION.search(text)),
                               "category": None}, "tasks": uniq}
    return out


# ================================================================ report


def build_report(key: dict, preds: dict, meta: dict | None = None) -> dict:
    base = baseline_predictions(preds)
    bt, bd = score_triage(key, base), score_deadlines(key, base)
    cats = Counter(g.get("category") for g in key["messages"].values() if g.get("category"))
    usage = [p.get("usage") or {} for p in preds.values()]
    return {
        "meta": meta or {}, "answer_key": {"version": key.get("version"), "verified": key.get("verified"),
                                           "label_status": key.get("label_status"), "mails": len(key["messages"])},
        "triage": score_triage(key, preds), "deadlines": score_deadlines(key, preds), "privacy": score_privacy(key, preds),
        "tokens": {"input": sum(u.get("input_tokens") or 0 for u in usage), "output": sum(u.get("output_tokens") or 0 for u in usage)},
        "baseline": {
            "what": "keywords for reply/action; every written date on a line with a deadline word becomes an open task",
            "labels": bt["labels"], "exact_match": bt["exact_match"],
            "majority_category": rate(max(cats.values()) if cats else 0, sum(cats.values())),
            "recall_per_mail": bd["recall_per_mail"], "recall_unique": bd["recall_unique"],
            "precision_per_mail": bd["precision_per_mail"], "precision_task_list": bd["precision_task_list"],
            "open_task_outcomes": bd["open_task_outcomes"]},
    }


def _pct(r: dict | None) -> str:
    if not r or r.get("value") is None:
        return "n/a"
    ci = r.get("ci95")
    return f"{r['value']:.1%} ({r['k']}/{r['n']}" + (f", 95% CI {ci[0]:.0%}-{ci[1]:.0%})" if ci else ")")


def markdown(name: str, rep: dict) -> str:
    t, d, b, ak = rep["triage"], rep["deadlines"], rep["baseline"], rep["answer_key"]
    L = [f"# Mail evaluation - {name}", "",
         f"Answer key: {ak['version']}, {ak['mails']} mails. Label status: **{ak['label_status']}**.", ""]
    m = rep.get("meta") or {}
    if m:
        L += [f"Run: model `{m.get('model')}`, prompt `{m.get('prompt_version')}`, schema `{m.get('schema_version')}`, "
              f"code `{m.get('code_commit')}`, {m.get('finished_at')}. Model time {m.get('analysis_seconds')} s for "
              f"{m.get('messages')} mails; tokens in {rep['tokens']['input']}, out {rep['tokens']['output']}. "
              f"Outbound requests refused: {len(m.get('refused_requests') or [])}.", ""]
    L += ["## Triage", "", "| Label | Precision | Recall | F1 | TP | FP | FN | TN | Keyword baseline F1 |", "|---|---|---|---|---|---|---|---|---|"]
    for k in LABELS:
        x = t["labels"][k]
        L.append(f"| {k} | {_pct(x['precision'])} | {_pct(x['recall'])} | {x['f1']} | {x['TP']} | {x['FP']} | {x['FN']} | {x['TN']} | {b['labels'][k]['f1']} |")
    L += ["", f"- Both labels right: {_pct(t['exact_match'])}; keyword baseline {_pct(b['exact_match'])}.",
          f"- Mails that need nothing and were left alone: {_pct(t['ignore']['correctly_ignored'])}.",
          f"- Mails that need attention but were marked ignore: {_pct(t['ignore']['needed_attention_but_ignored'])}.",
          f"- Category: {_pct(t['category_accuracy'])}; always guessing the largest category {_pct(b['majority_category'])}.",
          f"- Mails with no model output: {len(t['no_output'])} {t['no_output'] or ''}", ""]
    order = ["reply", "action", "reply+action", "ignore"]
    cols = order + ["no output"]
    L += ["Reply / action / ignore (rows: answer key, columns: system)", "", "| | " + " | ".join(cols) + " |", "|---" * (len(cols) + 1) + "|"]
    L += [f"| **{w}** | " + " | ".join(str(t["confusion"].get(w, {}).get(c, 0)) for c in cols) + " |" for w in order]
    ccols = list(CATEGORIES) + ["no output"]
    L += ["", "Category (rows: answer key, columns: system)", "", "| | " + " | ".join(ccols) + " |", "|---" * (len(ccols) + 1) + "|"]
    L += [f"| **{w}** | " + " | ".join(str(t["category_confusion"].get(w, {}).get(c, 0)) for c in ccols) + " |"
          for w in CATEGORIES if w in t["category_confusion"]]
    for dim, vals in t["by_group"].items():
        L += ["", f"By {dim}", "", f"| {dim} | Both labels right | Category right |", "|---|---|---|"]
        L += [f"| {v} | {_pct(x['exact_match'])} | {_pct(x['category'])} |" for v, x in vals.items()]
    a, o = d["answer_key"], d["system_output"]
    L += ["", "## Deadlines", "",
          f"Answer key: {a['required_unique']} required deadlines, written {a['required_mentions']} times in "
          f"{a['mails_with_required_deadline']} mails; {a['non_task']} times that are not student work, {a['optional']} "
          f"optional dates, {a['completed']} due dates inside receipts.",
          f"System: {o['tasks']} tasks, {o['open']} open ({o['open_with_date']} with a date, {o['open_without_date']} without), "
          f"{o['closed']} closed. Analysis failed on {len(o['mails_analysis_failed'])} mail(s).", "",
          "| Measure | System | Regex baseline |", "|---|---|---|",
          f"| Recall, each mail on its own (stated date extracted) | {_pct(d['recall_per_mail'])} | {_pct(b['recall_per_mail'])} |",
          f"| Recall, unique deadlines with their final date | {_pct(d['recall_unique'])} | {_pct(b['recall_unique'])} |",
          f"| Precision, each mail on its own | {_pct(d['precision_per_mail'])} | {_pct(b['precision_per_mail'])} |",
          f"| Precision of the task list (duplicates and outdated dates count as wrong) | {_pct(d['precision_task_list'])} | {_pct(b['precision_task_list'])} |",
          "", f"- Second reading (added after the first results): if 'attend <event>' tasks were accepted as tasks "
          f"({d['if_event_tasks_were_accepted']['dated_event_tasks']} of them), precision would be "
          f"{_pct(d['if_event_tasks_were_accepted']['precision_per_mail'])} per mail and "
          f"{_pct(d['if_event_tasks_were_accepted']['precision_task_list'])} for the task list.",
          f"- Missed deadlines by reason: {d['missed_breakdown'] or 'none'}",
          f"- Open tasks by outcome: {d['open_task_outcomes']}",
          f"- Closed tasks by outcome: {d['closed_task_outcomes'] or 'none'}",
          f"- Times that are not student work turned into open tasks: {d['non_task']['became_open_task']}/{d['non_task']['total']}"]
    L += [f"  - {k}: {v['became_open_task']}/{v['total']}" for k, v in d["non_task"].get("by_kind", {}).items() if v["became_open_task"]]
    L += [f"- Optional dates turned into open tasks: {d['optional']['became_open_task']}/{d['optional']['total']}",
          f"- Receipts re-opened as work: {d['completed']['became_open_task']}/{d['completed']['total']}",
          f"- Time of day on correctly dated tasks: {d['time_of_day'] or 'n/a'}",
          f"- Time zone on correctly dated tasks: {d['timezone'] or 'n/a'}"]
    for dim, vals in d["recall_by_group"].items():
        L += ["", f"Recall (each mail on its own) by {dim}", "", f"| {dim} | Recall |", "|---|---|"]
        L += [f"| {v} | {_pct(x)} |" for v, x in vals.items()]
    p = rep["privacy"]
    if p["planted"]:
        L += ["", "## Data minimisation", "",
              f"Addresses, links, phone numbers, codes and long IDs removed before storage: {_pct(p['removed'])}.",
              f"Still present: {p['still_present'] or 'none'}"]
    L += ["", "## Every error", "", f"Triage ({len(t['wrong'])}):", ""]
    L += [f"- `{w['mail']}` expected {w['expected']} / {w['expected_category']}, got {w['got']} / {w['got_category']}"
          + (f" - {w['summary_en']}" if w.get("summary_en") else "") + (f" [{w['error']}]" if w.get("error") else "") for w in t["wrong"]]
    L += ["", f"Deadlines ({len(d['failures'])}):", ""]
    for f in d["failures"]:
        if f["kind"] == "missed_deadline":
            got = f["got"]
            L.append(f"- `{f['mail']}` {f['detail']}: expected {f['expected_dates']} {f['expected_times']} (\"{f['anchor']}\")"
                     + (f"; got {got['date']} {got['time']} \"{got['title']}\" [{got['state']}]" if got else "")
                     + (" [analysis failed]" if f["analysis_failed"] else ""))
        else:
            tk, it = f["task"], f["item"]
            L.append(f"- `{f['mail']}` {f['detail']}: task \"{tk['title_en'] or tk['title']}\" {tk['date']} {tk['time']}"
                     + (f" from {it['role']}" + (f"/{it['kind']}" if it.get("kind") else "") + f" \"{it['anchor']}\"" if it else "")
                     + (f" (first seen in {f['first_seen_in']})" if f.get("first_seen_in") else ""))
    return "\n".join(L) + "\n"


def aggregate(reports: list[dict]) -> dict:
    """Mean, minimum and maximum of the headline numbers over repeated runs of the same mail set."""
    def span(get) -> dict:
        vals = [v for v in (get(r) for r in reports) if v is not None]
        return {"mean": round(sum(vals) / len(vals), 3), "min": min(vals), "max": max(vals), "runs": len(vals)} if vals else {}
    return {
        "needs_reply_f1": span(lambda r: r["triage"]["labels"]["needs_reply"]["f1"]),
        "needs_action_f1": span(lambda r: r["triage"]["labels"]["needs_action"]["f1"]),
        "exact_match": span(lambda r: r["triage"]["exact_match"]["value"]),
        "category_accuracy": span(lambda r: r["triage"]["category_accuracy"]["value"]),
        "deadline_recall_per_mail": span(lambda r: r["deadlines"]["recall_per_mail"]["value"]),
        "deadline_recall_unique": span(lambda r: r["deadlines"]["recall_unique"]["value"]),
        "deadline_precision_per_mail": span(lambda r: r["deadlines"]["precision_per_mail"]["value"]),
        "deadline_precision_task_list": span(lambda r: r["deadlines"]["precision_task_list"]["value"]),
        "deadline_precision_task_list_if_event_tasks_accepted": span(
            lambda r: r["deadlines"]["if_event_tasks_were_accepted"]["precision_task_list"]["value"]),
        "non_task_became_open_task": span(lambda r: r["deadlines"]["non_task"]["became_open_task"]),
        "optional_became_open_task": span(lambda r: r["deadlines"]["optional"]["became_open_task"]),
        "open_tasks_with_date": span(lambda r: r["deadlines"]["system_output"]["open_with_date"]),
        "needs_action_precision": span(lambda r: r["triage"]["labels"]["needs_action"]["precision"]["value"]),
        "needs_action_recall": span(lambda r: r["triage"]["labels"]["needs_action"]["recall"]["value"]),
        "needs_reply_precision": span(lambda r: r["triage"]["labels"]["needs_reply"]["precision"]["value"]),
        "needs_reply_recall": span(lambda r: r["triage"]["labels"]["needs_reply"]["recall"]["value"]),
        "ignored_correctly": span(lambda r: r["triage"]["ignore"]["correctly_ignored"]["value"]),
        "needed_attention_but_ignored": span(lambda r: r["triage"]["ignore"]["needed_attention_but_ignored"]["value"]),
        "baseline_exact_match": span(lambda r: r["baseline"]["exact_match"]["value"]),
        "baseline_deadline_recall_per_mail": span(lambda r: r["baseline"]["recall_per_mail"]["value"]),
        "baseline_deadline_precision_per_mail": span(lambda r: r["baseline"]["precision_per_mail"]["value"]),
        "secrets_removed": span(lambda r: r["privacy"]["removed"]["value"]),
        "seconds_per_mail": span(lambda r: round(r["meta"]["analysis_seconds"] / r["meta"]["messages"], 2) if r.get("meta") else None),
        "tokens_per_mail": span(lambda r: round((r["tokens"]["input"] + r["tokens"]["output"]) / r["answer_key"]["mails"])),
        "open_tasks": span(lambda r: r["deadlines"]["system_output"]["open"]),
        "analysis_failed": span(lambda r: len(r["deadlines"]["system_output"]["mails_analysis_failed"])),
    }
