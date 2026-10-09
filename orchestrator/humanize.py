"""Make Nico read like a person on WhatsApp.

Two jobs, both pure functions so they can be unit-tested:

1. Conversation memory. OpenBSP sends only the latest client message (verified
   2026-09-26), so without this the model answered every message blind: it
   greeted again, repeated what it had already said and re-asked data the
   client had given. We keep the last turns in the session variables and pass
   them to the model as real chat history.
2. Output cleanup. Strip the marks that give away a language model in a chat:
   Markdown that WhatsApp shows literally, em dashes, a fresh "Hola!" on every
   reply, canned assistant closers, and sentences cut by the token limit.
"""
from __future__ import annotations

import re
from typing import Any

MAX_RECENT_TURNS = 10
MAX_TURN_CHARS = 600

_GREETING_RE = re.compile(
    r"^\s*(?:¡\s*)?(?:hola|holaa+|buenas|buen dia|buenos dias|buenas tardes|buenas noches"
    r"|hi|hello|hey|ola|olá|oi|bom dia|boa tarde|boa noite)"
    r"(?:\s+(?:de nuevo|again|again!|novamente))?\s*[!¡.,]+\s*",
    re.IGNORECASE,
)
# Sentences only a chatbot sends. Removed when they are not the whole reply.
_ROBOTIC_SENTENCE_RES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"[¿]?hay algo m[aá]s en (?:lo )?que (?:te |le |lo |la )?pueda ayudar(?:te|le|lo|la)?\??",
        r"[¿]?en qu[eé] m[aá]s (?:te |le )?puedo ayudar(?:te|le)?\??",
        r"no dudes en (?:consultar|preguntar|escribir)(?:me|nos)?[^.!?\n]*[.!]?",
        r"estoy (?:aqu[ií]|ac[aá]) para ayudar(?:te|le)?[^.!?\n]*[.!]?",
        r"(?:is there )?anything else i can help (?:you )?with\??",
        r"feel free to (?:ask|reach out|contact)[^.!?\n]*[.!]?",
        r"i'?m here to help[^.!?\n]*[.!]?",
        r"posso (?:te )?ajudar (?:em )?mais alguma coisa\??",
        r"fico (?:à|a) disposi[cç][aã]o[^.!?\n]*[.!]?",
    )
)
_OPENING_PRAISE_RE = re.compile(
    r"^\s*(?:¡\s*)?(?:excelente|buena|gran|great|good|[oó]tima|boa)\s+(?:pregunta|consulta|question|pergunta)\s*[!.]+\s*",
    re.IGNORECASE,
)


def _clip(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= MAX_TURN_CHARS:
        return text
    return text[: MAX_TURN_CHARS - 1].rstrip() + "…"


def append_recent_turns(
    prior: Any,
    user_text: str,
    reply: str,
    max_turns: int = MAX_RECENT_TURNS,
) -> list[dict[str, str]]:
    """Return the rolling transcript with this exchange appended.

    Each entry is {"role": "user" | "assistant", "text": ...}. A suppressed or
    empty reply records only the client message, so the transcript matches
    what the client actually saw.
    """
    turns = [
        {"role": t["role"], "text": str(t.get("text") or "")}
        for t in (prior if isinstance(prior, list) else [])
        if isinstance(t, dict) and t.get("role") in ("user", "assistant") and t.get("text")
    ]
    if (user_text or "").strip():
        turns.append({"role": "user", "text": _clip(user_text)})
    if (reply or "").strip():
        turns.append({"role": "assistant", "text": _clip(reply)})
    return turns[-max_turns:]


def history_to_messages(recent_turns: Any) -> list[dict[str, str]]:
    """Turn the stored transcript into Responses API input messages."""
    if not isinstance(recent_turns, list):
        return []
    return [
        {"role": t["role"], "content": str(t["text"])}
        for t in recent_turns
        if isinstance(t, dict) and t.get("role") in ("user", "assistant") and t.get("text")
    ]


def assistant_already_spoke(recent_turns: Any) -> bool:
    return any(
        isinstance(t, dict) and t.get("role") == "assistant" and t.get("text")
        for t in (recent_turns if isinstance(recent_turns, list) else [])
    )


def trim_to_last_sentence(text: str) -> str:
    """Drop a trailing sentence that was cut mid-way by the token limit."""
    text = (text or "").rstrip()
    if not text or text[-1] in ".!?…)\"'»" or text[-1] in "🙌👍😊🏔️⛰️":
        return text
    cut = max(text.rfind(mark) for mark in (".", "!", "?", "\n"))
    if cut <= 0:
        return text
    return text[: cut + 1].rstrip()


def _capitalize_first(text: str) -> str:
    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1 :]
        if ch not in "¡¿\"'(":
            return text
    return text


def humanize_reply(reply: str, *, channel: str = "whatsapp", already_spoke: bool = False) -> str:
    """Clean model output so it reads like a person typing in a chat."""
    original = (reply or "").strip()
    if not original:
        return original
    text = original

    # Markdown: WhatsApp bold is *x*, and it never renders headings or links.
    if channel == "whatsapp":
        text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
        text = re.sub(r"__(.+?)__", r"_\1_", text)
        text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1: \2", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)

    # Em/en dashes used as punctuation are a classic model tell.
    # Ranges like "4300–5000 m" keep their dash.
    text = re.sub(r"\s+[—–]\s+", ", ", text)
    text = re.sub(r"(?<=[^\W\d])—(?=[^\W\d])", ", ", text)

    if already_spoke:
        text = _GREETING_RE.sub("", text, count=1)
    text = _OPENING_PRAISE_RE.sub("", text, count=1)

    for pattern in _ROBOTIC_SENTENCE_RES:
        text = pattern.sub("", text)

    # Tidy what the removals left behind.
    text = re.sub(r"[ \t]+([,.!?])", r"\1", text)
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?m)^[ \t,]+|[ \t]+$", "", text)
    text = text.strip().strip(",").strip()

    if not text:
        return original
    return _capitalize_first(text)
