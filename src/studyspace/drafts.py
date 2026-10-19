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
    tone: str = "friendly"
    points: str = ""                                    # what the student wanted to say, in their own words
    changes: list[str] = field(default_factory=list)    # how their points were turned into the draft
    asks: list[str] = field(default_factory=list)       # the sentences in their message that need an answer
    sent: bool = False  # always False: sending is the student's action


# ---- turning quick notes into sentences (offline) ----------------------------------------------
SHORTHAND = {
    "tmr": "tomorrow", "tmrw": "tomorrow", "2moro": "tomorrow", "thx": "thanks", "thks": "thanks", "ty": "thank you",
    "pls": "please", "plz": "please", "u": "you", "ur": "your", "r": "are", "cuz": "because", "coz": "because",
    "b4": "before", "abt": "about", "asap": "as soon as possible", "idk": "I don't know", "btw": "by the way",
    "gonna": "going to", "wanna": "want to", "w/": "with", "w/o": "without", "im": "I'm", "dont": "don't",
    "cant": "can't", "wont": "won't", "didnt": "didn't", "ok": "OK", "i": "I", "mon": "Monday", "tue": "Tuesday",
    "tues": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "thur": "Thursday", "thurs": "Thursday", "fri": "Friday",
    "sat": "Saturday", "sun": "Sunday", "hr": "hour", "hrs": "hours", "min": "minutes", "mins": "minutes",
}
_SHORT = re.compile(r"(?<![\w/])(" + "|".join(re.escape(k) for k in sorted(SHORTHAND, key=len, reverse=True)) + r")(?![\w/])", re.I)
ASK = re.compile(r"\?|\b(let me know|could you|can you|would you|please (?:reply|confirm|let)|are you (?:free|available)|your availability)\b", re.I)


def polish_points(points: str) -> tuple[list[str], list[str]]:
    """Quick notes -> tidy sentences, plus a list of what was changed (shown to the student)."""
    changes: list[str] = []
    seen: set[str] = set()

    def expand(m: re.Match) -> str:
        word = m.group(1)
        full = SHORTHAND[word.lower()]
        if word.lower() == "i" and word == "I":
            return word
        if word != full and word.lower() not in seen:
            seen.add(word.lower())
            changes.append(f"{word} → {full}")
        return full

    parts = [p.strip(" -•*\t") for p in re.split(r"[\n;]+|(?<=[.!?])\s+", points) if p.strip(" -•*\t")]
    sentences = []
    for p in parts:
        p = _SHORT.sub(expand, p)
        p = re.sub(r"\s+", " ", p)
        # notes often drop the subject: "ok will finish by Thu" -> "OK, I will finish by Thu"
        fixed = re.sub(r"^(OK|sure|yes|yep|noted)[,!]?\s+(will|can|am|have|need|would|should)\b", lambda m: f"{m.group(1)}, I {m.group(2)}", p, flags=re.I)
        fixed = re.sub(r"^(will|can|am|have|need|would|should)\b", lambda m: f"I {m.group(1).lower()}", fixed, flags=re.I)
        if fixed != p and "added “I” where it was missing" not in changes:
            changes.append("added “I” where it was missing")
        p = fixed
        p = p[:1].upper() + p[1:]
        if not re.search(r"[.!?]$", p):
            p += "."
        sentences.append(p)
    if sentences:
        changes.append("written as full sentences")
    return sentences, changes


def asks_in(text: str) -> list[str]:
    """Sentences that ask the student something, to highlight in the original."""
    out = []
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", clean_text(text)):
        sentence = sentence.strip()
        if sentence and ASK.search(sentence) and len(sentence) < 300:
            out.append(sentence)
    return out[:4]


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


TONES = ("friendly", "formal", "brief")


def draft_reply(source: Source, style: StyleProfile, slots: list[dict] | None = None,
                student_domain: str | None = None, gateway: Gateway | None = None,
                points: str | None = None, tone: str = "auto") -> Draft:
    kind = sender_kind(source.sender, student_domain)
    if tone not in TONES:
        tone = "formal" if kind in ("staff", "external") else "friendly"
    name = _addressee(source.sender, kind)
    greeting = f"{style.formal_greeting if tone == 'formal' else style.greeting} {name},".replace(" ,", ",")
    sign = f"{style.formal_sign_off if tone == 'formal' else style.sign_off},\n{style.name}"
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

    changes: list[str] = []
    if points and points.strip():
        intent = "your points"
        sentences, changes = polish_points(points)
        opener = {"friendly": "Thanks for your message.", "formal": "Thank you for your email.", "brief": ""}[tone]
        closing = {"friendly": "Let me know if you need anything else.", "formal": "Please let me know if you need anything further.",
                   "brief": ""}[tone]
        core = " ".join(x for x in [opener, " ".join(sentences), closing] if x)
        changes = changes + ["added a greeting and sign-off in your style"]
    elif tone == "brief":
        core = re.split(r"(?<=[.!?])\s+", core)[0] if intent != "availability" else core

    body = f"{greeting}\n\n{core}\n\n{sign}"
    mode = "offline-template"
    if gateway is not None and gateway.online:
        ask = f"Rewrite these points as the reply: {points}" if points else "Write a short reply."
        prompt = f"{ask} Tone: {tone}. Greeting: {greeting} Sign-off: {sign}\n\nTheir message:\n{text}"
        reply = gateway.ask("draft", "You draft short, polite email replies for a university student.", prompt)
        if reply:
            body, mode = reply, "model"
            changes = ["rewritten by the language model from cleaned, redacted text"]

    warnings = []
    if kind == "staff":
        warnings.append({"code": SENSITIVE_RECIPIENT, "message": "This goes to teaching staff. Check the tone and facts before sending."})
    elif kind == "external":
        warnings.append({"code": SENSITIVE_RECIPIENT, "message": "This goes outside the university. Share only what you are comfortable with."})
    _, address = parseaddr(source.sender or "")
    return Draft(record_id=source.record_id, to=address, subject=subject, body=body, intent=intent, warnings=warnings, mode=mode,
                 tone=tone, points=points or "", changes=changes, asks=asks_in(source.body_text))
