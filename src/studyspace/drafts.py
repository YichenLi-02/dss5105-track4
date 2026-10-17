"""Reply drafts (gate 3: the student reads and sends them; Studyspace never sends anything).

Offline mode fills templates in the student's own style (greeting and sign-off learned from a few sent emails).
When a model provider is configured, the same request goes through the privacy gateway instead.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parseaddr

from .llm import Gateway, clean_text
from .models import SENSITIVE_RECIPIENT, Source
from .timeutil import local
from .triage import sender_kind

GREETING = re.compile(r"^\s*(hi|hello|hey|dear)\b", re.I | re.M)
SIGN_OFF = re.compile(r"^\s*(thanks|thank you|best|best regards|regards|cheers|kind regards)\s*[,!.]?\s*$", re.I | re.M)
AVAILABILITY = re.compile(r"\b(your availability|are you (?:free|available)|a (?:quick |short |\d+-minute )?(?:call|chat)|coffee chat|"
                          r"meet up|set up a meeting|schedule a (?:call|meeting|chat)|catch up|when (?:are|would) you be free)\b", re.I)
REQUEST = re.compile(r"\b(could you|can you|would you|please)\s+(?P<what>[^?.!\n]{3,80})", re.I)
DEADLINE_HINT = re.compile(r"\bby\s+(?P<when>[A-Z][a-z]+day(?:\s+(?:night|evening|morning))?|\d{1,2}\s+[A-Z][a-z]{2,8}|tomorrow|tonight)", re.I)


@dataclass
class StyleProfile:
    name: str = "Jordan"
    greeting: str = "Hi"
    sign_off: str = "Thanks"
    formal_greeting: str = "Dear"
    formal_sign_off: str = "Best regards"


@dataclass
class Draft:
    record_id: str
    to: str
    subject: str
    body: str
    intent: str
    warnings: list[dict] = field(default_factory=list)
    mode: str = "offline-template"
    sent: bool = False  # always False: sending is the student's action


def learn_style(sent_texts: list[str], name: str = "Jordan") -> StyleProfile:
    """Most common greeting and sign-off in the student's sent mail."""
    greetings = Counter(m.group(1).capitalize() for t in sent_texts for m in GREETING.finditer(t))
    sign_offs = Counter(m.group(1).capitalize() for t in sent_texts for m in SIGN_OFF.finditer(t))
    profile = StyleProfile(name=name)
    if greetings:
        profile.greeting = greetings.most_common(1)[0][0]
    if sign_offs:
        profile.sign_off = sign_offs.most_common(1)[0][0]
    return profile


def _addressee(sender: str | None, kind: str) -> str:
    """'Priya' for a peer, 'Prof. Ho' for staff with a title, the full name otherwise."""
    display, address = parseaddr(sender or "")
    display = re.sub(r"\s*\(.*?\)", "", display).strip()
    if not display:
        return ""
    parts = display.replace("Prof.", "Prof").replace("Dr.", "Dr").split()
    if parts[0] in ("Prof", "Dr"):
        return f"{parts[0]}. {parts[-1]}"
    return parts[0] if kind in ("peer", "staff") else " ".join(parts)


def _fmt_slot(slot: dict) -> str:
    a, b = local(datetime.fromisoformat(slot["start"])), local(datetime.fromisoformat(slot["end"]))
    return f"{a:%a %d %b}, {a:%H:%M}–{b:%H:%M}"


def draft_reply(source: Source, style: StyleProfile, slots: list[dict] | None = None,
                student_domain: str | None = None, gateway: Gateway | None = None) -> Draft:
    kind = sender_kind(source.sender, student_domain)
    formal = kind in ("staff", "external")
    name = _addressee(source.sender, kind)
    greeting = f"{style.formal_greeting if formal and kind == 'staff' else style.greeting} {name},".replace(" ,", ",")
    sign = f"{style.formal_sign_off if formal else style.sign_off},\n{style.name}"
    text = clean_text(source.body_text)
    subject = source.subject or ""
    subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"

    if AVAILABILITY.search(text):
        intent = "availability"
        if slots:
            options = "\n".join(f"- {_fmt_slot(s)}" for s in slots[:3])
            core = (f"Thank you for reaching out. I would be glad to have a chat. These times work for me (Singapore time):\n\n"
                    f"{options}\n\nPlease let me know which suits you, or suggest another time.")
        else:
            core = "Thank you for reaching out. I would be glad to have a chat. Could you share a few times that suit you?"
    elif (m := REQUEST.search(text)):
        intent = "request"
        what = m.group("what").strip().rstrip(",")
        what = re.sub(r"\b(your|you)\b", "my", what, count=1) if what.lower().startswith(("send", "share")) else what
        when = DEADLINE_HINT.search(text)
        by = f" by {when.group('when')}" if when else ""
        core = f"Sure, I will {what.split(' by ')[0]}{by}. I will let you know once it is done."
    else:
        intent = "acknowledge"
        core = "Thank you for the update. Noted."

    body = f"{greeting}\n\n{core}\n\n{sign}"
    mode = "offline-template"
    if gateway is not None and gateway.online:
        prompt = f"Write a short reply in the student's style. Greeting: {greeting} Sign-off: {sign}\n\nMessage:\n{text}"
        reply = gateway.ask("draft", "You draft short, polite email replies for a university student.", prompt)
        if reply:
            body, mode = reply, "model"

    warnings = []
    if kind == "staff":
        warnings.append({"code": SENSITIVE_RECIPIENT, "message": "This goes to teaching staff. Check the tone and facts before sending."})
    elif kind == "external":
        warnings.append({"code": SENSITIVE_RECIPIENT, "message": "This goes outside the university. Share only what you are comfortable with."})
    _, address = parseaddr(source.sender or "")
    return Draft(record_id=source.record_id, to=address, subject=subject, body=body, intent=intent, warnings=warnings, mode=mode)
