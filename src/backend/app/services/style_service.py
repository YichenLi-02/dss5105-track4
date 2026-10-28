"""Personal style references: only the user's own authored section of sent samples.

Selection is an authorisation scope for drafting, not training. Contexts without own
samples (recruiters, Chinese) fall back to an explicitly generic tone.
"""
from __future__ import annotations

import json
import sqlite3
from functools import lru_cache

from ..config import settings
from ..db import audit, loads, now_iso
from ..errors import AppError, not_found
from . import preferences, ref_i18n, reference_view

# Fallback when the prototype view is missing: mapping from style_profile.json source_ids.
DEFAULT_CONTEXT = {"M41": "academic", "M42": "academic", "M43": "academic", "M47": "academic", "M44": "academic",
                   "M45": "academic", "M49": "academic", "M46": "peer", "M48": "peer", "M50": "correction"}
RELATIONSHIP_CONTEXT = {"professor": "academic", "admin": "academic", "peer": "peer", "correction": "correction",
                        "recruiter": None}


@lru_cache(maxsize=2)
def _profile_file(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def profile_limitations() -> list[dict]:
    """Structured so the UI can render the wording in its own language."""
    prof = _profile_file(str(settings.sample_data_dir / "style_profile.json"))
    out = []
    for p in prof.get("profiles", []):
        level = p.get("evidence_level")
        if level not in ("unsupported", "limited"):
            continue
        ctx = p.get("context", "")
        out.append({"level": level, "context": ctx, "context_en": ref_i18n.profile_context(ctx) or ctx,
                    "language": p.get("language"), "samples": len(p.get("source_ids", [])),
                    "fallback": p.get("fallback"), "fallback_en": ref_i18n.profile_fallback(ctx)})
    return out


def _refs_raw(conn: sqlite3.Connection) -> list[dict]:
    view = reference_view.style_view()
    rows = conn.execute(
        "SELECT * FROM messages WHERE direction='outbound' AND source_type='email' ORDER BY sent_at").fetchall()
    out = []
    for r in rows:
        loc = loads(r["locator_json"], {})
        sa = loc.get("style_annotation") or {}
        authored = sa.get("reusable_text") or ""
        pv = view.get(r["source_id"], {})
        out.append({
            "message_id": r["id"], "sample_id": r["source_id"], "subject": r["subject"], "sent_at": r["sent_at"],
            "context": pv.get("context") or DEFAULT_CONTEXT.get(r["source_id"], "academic"),
            "function": pv.get("function") or sa.get("function") or "",
            "observations": pv.get("observations") or sa.get("observations") or "",
            "function_en": ref_i18n.style(r["source_id"]).get("function"),
            "observations_en": ref_i18n.style(r["source_id"]).get("observations"),
            "language": "en", "authored_excerpt": authored,
            "authorship_basis": sa.get("authorship_basis"),
            "authorship_verified": bool(authored) and bool(sa.get("authorship_basis")),
        })
    return out


def selected_ids(conn: sqlite3.Connection) -> tuple[list[str], int, dict]:
    value, rev = preferences.get_raw(conn)
    refs = _refs_raw(conn)
    sel = value["style"].get("selected_reference_ids")
    if sel is None:
        sel = [r["message_id"] for r in refs if r["authorship_verified"]]
    return sel, rev, value["style"]


def list_references(conn: sqlite3.Connection) -> list[dict]:
    sel, rev, _ = selected_ids(conn)
    return [{**r, "included": r["message_id"] in sel, "profile_revision": rev} for r in _refs_raw(conn)]


def get_profile(conn: sqlite3.Connection) -> dict:
    sel, rev, style = selected_ids(conn)
    return {"selected_reference_ids": sel, "length_preference": style.get("length_preference", "short"),
            "revision": rev, "limitations": profile_limitations()}


def _after_change(conn: sqlite3.Connection, changed_ids: set[str]) -> int:
    """Drafts that used a changed reference keep their body but are flagged; pending proposals are invalidated."""
    from .proposal_service import invalidate_for_source
    n = 0
    for d in conn.execute("SELECT id, style_reference_ids_json, verified_facts_json FROM drafts").fetchall():
        if set(loads(d["style_reference_ids_json"], [])) & changed_ids:
            facts = loads(d["verified_facts_json"], {})
            facts["_style_changed_at"] = now_iso()
            conn.execute("UPDATE drafts SET verified_facts_json=?, revision=revision+1, ready_for_review=0, updated_at=? WHERE id=?",
                         (json.dumps(facts, ensure_ascii=False), now_iso(), d["id"]))
            n += invalidate_for_source(conn, "draft", d["id"], "style_reference_changed")
    return n


def set_included(conn: sqlite3.Connection, message_id: str, included: bool, expected_rev: int) -> dict:
    refs = {r["message_id"]: r for r in _refs_raw(conn)}
    if message_id not in refs:
        raise not_found("style reference")
    if included and not refs[message_id]["authorship_verified"]:
        raise AppError(422, "AUTHORSHIP_NOT_VERIFIED", "Only the user's own authored sections can be used")
    sel, _, _ = selected_ids(conn)
    sel = [s for s in sel if s != message_id] + ([message_id] if included else [])
    preferences.update_style(conn, expected_rev, {"selected_reference_ids": sel})
    invalidated = _after_change(conn, {message_id})
    audit(conn, "style_reference_changed", "style_reference", message_id,
          {"included": included, "proposals_invalidated": invalidated})
    return next(r for r in list_references(conn) if r["message_id"] == message_id)


def update_profile(conn: sqlite3.Connection, body: dict) -> dict:
    sel_before, _, _ = selected_ids(conn)
    patch = {}
    if body.get("selected_reference_ids") is not None:
        valid = {r["message_id"] for r in _refs_raw(conn) if r["authorship_verified"]}
        bad = [i for i in body["selected_reference_ids"] if i not in valid]
        if bad:
            raise AppError(422, "UNKNOWN_REFERENCE", "Unknown or unverified references", bad)
        patch["selected_reference_ids"] = body["selected_reference_ids"]
    if body.get("length_preference"):
        patch["length_preference"] = body["length_preference"]
    preferences.update_style(conn, body["expected_revision"], patch)
    if "selected_reference_ids" in patch:
        _after_change(conn, set(sel_before) ^ set(patch["selected_reference_ids"]))
    return get_profile(conn)


def pick_examples(conn: sqlite3.Connection, relationship: str, language: str, limit: int = 3) -> tuple[list[dict], str, str]:
    """Return (examples, style_mode, note). Never borrows a sample from an unrelated relationship."""
    if language != "en":
        return [], "generic", "no_own_samples_for_language"
    context = RELATIONSHIP_CONTEXT.get(relationship)
    if context is None:
        return [], "generic", "no_own_samples_for_relationship"
    sel, _, _ = selected_ids(conn)
    refs = [r for r in _refs_raw(conn) if r["message_id"] in sel and r["context"] == context and r["authorship_verified"]]
    if not refs:
        return [], "generic", "no_selected_samples_for_relationship"
    return refs[:limit], "personal", "selected_samples"
