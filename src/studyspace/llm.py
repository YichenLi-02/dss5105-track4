"""The single gateway to a language model. Nothing else in the code base may call a model provider.

Every request goes through the same four steps:
1. clean   - drop quoted earlier replies, signatures and links (they carry other people's details)
2. redact  - replace names, student IDs, emails, phone numbers and passwords with placeholders
3. call    - send only the cleaned, redacted text to the one configured provider
4. log     - record what was sent, so the student can see exactly what left the computer

The placeholder -> original mapping stays local and is used to put names back into drafts.
Until the team picks a provider the gateway runs in offline mode: steps 1-2 still run, nothing is sent,
and callers fall back to the rule-based path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol

# ---- 1. cleaning ----------------------------------------------------------------------------
_QUOTE_HEADER = re.compile(r"^\s*On .{3,200}wrote:\s*$", re.M)
_OUTLOOK_HEADER = re.compile(r"^\s*(?:-{2,}\s*Original Message\s*-{2,}|_{8,})\s*$", re.M | re.I)
_FROM_SENT = re.compile(r"^\s*From:\s.+\n\s*(?:Sent|Date):\s.+$", re.M)
_SIG_DELIM = re.compile(r"^--\s*$", re.M)
_SIGN_OFF = re.compile(
    r"^\s*(?:best|best regards|kind regards|warm regards|regards|cheers|thanks|thank you|many thanks|sincerely|yours sincerely)[,!.]?\s*$",
    re.I | re.M,
)
_URL = re.compile(r"https?://\S+|www\.\S+")
_SENT_FROM = re.compile(r"^\s*Sent from my .+$", re.M | re.I)


def clean_text(text: str) -> str:
    """Remove the parts of a message that are not about the task and often hold other people's details."""
    text = text.replace("\r\n", "\n")
    cut = len(text)
    for pattern in (_QUOTE_HEADER, _OUTLOOK_HEADER, _FROM_SENT, _SIG_DELIM):
        m = pattern.search(text)
        if m:
            cut = min(cut, m.start())
    text = text[:cut]
    text = "\n".join(line for line in text.split("\n") if not line.lstrip().startswith(">"))
    text = _SENT_FROM.sub("", text)

    # a sign-off near the end ("Best,\nAlan Tan\nLecturer, ...") ends the useful text
    lines = text.rstrip().split("\n")
    for i in range(len(lines) - 1, max(-1, len(lines) - 8), -1):
        if _SIGN_OFF.match(lines[i]) and all(len(l) <= 80 for l in lines[i + 1 :]):
            lines = lines[:i]
            break
    text = "\n".join(lines)
    text = _URL.sub("[LINK]", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---- 2. redaction ---------------------------------------------------------------------------
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_STUDENT_ID = re.compile(r"\b(?:[AaUu]\d{7}[A-Za-z]|[Ee]\d{7})\b")
_PHONE = re.compile(r"(?<![\w+])(?:\+65[\s-]?)?[3689]\d{3}[\s-]?\d{4}(?!\w)")
_SECRET = re.compile(r"\b(password|passcode|pin|access code)(\s*(?:is|:|=)\s*)(\S+)", re.I)
_GREETING = re.compile(r"^(\s*(?i:hi|hello|hey|dear)\s+)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)(?=[\s,!])", re.M)
_NOT_NAMES = {"all", "everyone", "students", "class", "team", "there", "folks", "prof", "professor", "sir", "madam"}


@dataclass
class Redacted:
    text: str
    mapping: dict[str, str] = field(default_factory=dict)  # placeholder -> original, never sent
    counts: dict[str, int] = field(default_factory=dict)


def redact(text: str, known_names: Iterable[str] = ()) -> Redacted:
    mapping: dict[str, str] = {}
    counts: dict[str, int] = {}
    name_ids: dict[str, str] = {}

    def bump(kind: str) -> None:
        counts[kind] = counts.get(kind, 0) + 1

    def name_placeholder(name: str) -> str:
        key = name.lower()
        if key not in name_ids:
            name_ids[key] = f"[NAME_{len(name_ids) + 1}]"
            mapping[name_ids[key]] = name
        bump("name")
        return name_ids[key]

    def sub(pattern: re.Pattern, kind: str, label: str, s: str) -> str:
        def repl(m: re.Match) -> str:
            bump(kind)
            return label
        return pattern.sub(repl, s)

    text = sub(_EMAIL, "email", "[EMAIL]", text)
    text = sub(_STUDENT_ID, "student_id", "[STUDENT_ID]", text)
    text = sub(_PHONE, "phone", "[PHONE]", text)

    def secret(m: re.Match) -> str:
        bump("secret")
        return f"{m.group(1)}{m.group(2)}[SECRET]"

    text = _SECRET.sub(secret, text)

    # names we know (course staff, groupmates), longest first so "Alan Tan" wins over "Alan"
    for name in sorted({n.strip() for n in known_names if n and n.strip()}, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(name)}\b", lambda m: name_placeholder(m.group(0)), text, flags=re.I)

    def greeting(m: re.Match) -> str:
        if m.group(2).split()[0].lower() in _NOT_NAMES:
            return m.group(0)
        return m.group(1) + name_placeholder(m.group(2))

    text = _GREETING.sub(greeting, text)
    return Redacted(text=text, mapping=mapping, counts=counts)


def restore(text: str, mapping: dict[str, str]) -> str:
    """Put real names back into model output, locally, before the student sees a draft."""
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text


def prepare(text: str, known_names: Iterable[str] = ()) -> Redacted:
    """Steps 1 and 2: what a provider would receive."""
    return redact(clean_text(text), known_names)


# ---- 3-4. provider call and log -------------------------------------------------------------
class Provider(Protocol):
    name: str

    def complete(self, system: str, prompt: str) -> str: ...


class OfflineProvider:
    """No network. Callers see `online == False` and use the rule-based path instead."""

    name = "offline"

    def complete(self, system: str, prompt: str) -> str:  # pragma: no cover - never called when offline
        raise RuntimeError("offline mode: no model provider is configured")


def get_provider(name: str) -> Provider:
    if name in ("", "offline", None):
        return OfflineProvider()
    raise ValueError(f"model provider {name!r} is not set up yet; use STUDYSPACE_LLM_PROVIDER=offline")


Logger = Callable[[str, str, str], None]  # provider name, purpose, text that was sent


class Gateway:
    def __init__(self, provider: Provider, log: Logger | None = None):
        self.provider = provider
        self.log = log

    @property
    def online(self) -> bool:
        return self.provider.name != "offline"

    def ask(self, purpose: str, system: str, text: str, known_names: Iterable[str] = ()) -> str | None:
        """Send cleaned, redacted text to the provider. Returns None in offline mode."""
        prepared = prepare(text, known_names)
        if not self.online:
            return None
        if self.log:
            self.log(self.provider.name, purpose, prepared.text)
        return restore(self.provider.complete(system, prepared.text), prepared.mapping)
