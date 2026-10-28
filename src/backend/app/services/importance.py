"""Deterministic importance rule. The model never decides importance by itself; it only supplies
category, needs_reply / needs_action, an account-security flag and an amount. A user's explicit
choice always wins.

important if:
  - academic or career, and it needs a reply or an action (coursework, applications, interviews);
  - or it involves a payment / charge of at least the user's threshold (any currency, as stated);
  - or it concerns the user's own account security / access (new sign-in, suspension, lock-out)
    and needs an action.
Promotions, notices and ignorable mail are not important.
"""
from __future__ import annotations

import re

DEFAULT_THRESHOLD = 200
# Fallback for analyses made before the model returned `account_security`.
# Only explicit security / access words; "account" alone is too broad (data exports, statements...).
_ACCOUNT_WORDS = re.compile(
    r"(?i)security|sign[- ]?in|suspend|locked|disabled|deactivat|compromis|fraud|unauthori[sz]ed|"
    r"password|2-step|two[- ]factor|account (?:has been |was )?(?:closed|suspended|disabled)|"
    r"安全|登录|停用|封禁|暂停|冻结|已关闭|被盗|密码")


def is_account_security(a: dict, subject: str = "") -> bool:
    if a.get("account_security") is not None:
        return bool(a["account_security"])
    text = " ".join(a.get("attention_flags") or []) + " " + subject + " " + (a.get("summary") or "")
    return bool(_ACCOUNT_WORDS.search(text)) and a.get("category") in ("other", None)


def evaluate(a: dict, threshold: int | float = DEFAULT_THRESHOLD, subject: str = "") -> tuple[bool, str | None, dict]:
    """Returns (important, reason_key, params). reason_key maps to an interface string."""
    if a.get("important_override") is not None:
        return bool(a["important_override"]), "user_choice", {}
    cat = a.get("category")
    reply, action = a.get("needs_reply") is True, a.get("needs_action") is True
    amount = a.get("amount")
    if isinstance(amount, (int, float)) and amount >= threshold:
        return True, "large_payment", {"amount": f"{amount:,.0f}", "currency": a.get("currency") or ""}
    if cat in ("academic", "career") and (reply or action):
        return True, f"{cat}_{'reply' if reply else 'action'}", {}
    if action and is_account_security(a, subject):
        return True, "account_action", {}
    return False, None, {}
