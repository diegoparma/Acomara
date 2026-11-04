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
        r"quedo a (?:tu|su) (?:entera )?disposici[oó]n[^.!?\n]*[.!]?",
        r"espero que (?:esto |esta info(?:rmaci[oó]n)? )?(?:te |le )?(?:sirva|ayude)[.!]?",
        r"espero haber(?:te|le) ayudado[.!]?",
        r"(?:i )?hope (?:this|that) helps[.!]?",
        r"let me know if you have any (?:other |more |further )?questions[.!]?",
        r"espero que isso (?:te )?ajude[.!]?",
    )
)
# Apologies for a "confusion" nobody had. A person apologizes when something
# went wrong, not as a reflex.
_APOLOGY_RES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(?:disculp[aá](?:me)?|perd[oó]n(?:a(?:me)?)?|pido disculpas|lamento|mil disculpas)(?: por)? (?:la|cualquier|toda) confusi[oó]n[^.!?\n]*[.!]?",
        r"(?:i )?(?:apologi[sz]e|sorry) for (?:any|the) confusion[^.!?\n]*[.!]?",
        r"(?:desculp[ae]|pe[cç]o desculpas)(?: pela| por)? (?:a |qualquer )?confus[aã]o[^.!?\n]*[.!]?",
    )
)
# "Thanks for your question": fine in a first reply, odd in the middle of a chat.
_THANKS_FOR_ASKING_RES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^\s*(?:¡\s*)?(?:muchas )?gracias por (?:tu|su|la) (?:consulta|pregunta|mensaje|inter[eé]s)\s*[!.]+\s*",
        r"^\s*(?:thanks|thank you) for (?:your|the) (?:question|message|interest)\s*[!.]+\s*",
        r"^\s*obrigad[oa] pela (?:pergunta|mensagem)\s*[!.]+\s*",
    )
)
# Openers that read the question back to the client. Only stripped at the very
# start and only when more text follows.
_FILLER_OPENER_RES = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"^\s*(?:¡\s*)?entiendo (?:perfectamente|tu (?:consulta|pregunta|duda))\s*[!.]+\s*",
        r"^\s*entiendo que (?:quer[eé]s|quieres|necesit[aá]s|necesitas|te interesa|le interesa|quiere|necesita) (?:saber|conocer|consultar)[^.!?\n]*[.!]\s*",
        r"^\s*(?:me|nos) pregunt[aá]s (?:por|sobre|si)[^.!?\n]*[.!]\s*",
        r"^\s*(?:i understand (?:that )?you(?:'d| would)? (?:like|want) to know|you(?:'re| are) asking (?:about|whether|if))[^.!?\n]*[.!]\s*",
    )
)
# A one-word reaction at the start: "¡Genial!", "Perfecto,", "Great!".
# Fine once in a while; the same one every message gives a bot away. It must
# be followed by punctuation: "Claro que sí" or "Genial que vengan" are part of
# the sentence and stay.
_INTERJECTION_RE = re.compile(
    r"^\s*(?:¡\s*)?(?P<word>genial|perfecto|perfecta|excelente|buen[ií]simo|b[aá]rbaro|dale|claro|entiendo|"
    r"qu[eé] bueno|s[uú]per|ok|okey|listo|great|perfect|awesome|sure|got it|of course|absolutely|certainly|"
    r"[oó]timo|perfeito|legal|entendi|beleza|show)\s*[!.,]+\s*",
    re.IGNORECASE,
)
_EMOJI_RE = re.compile(
    "(?:[\U0001F1E6-\U0001F1FF]{2}|[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B50\u2B55][\uFE0F\u200D\U0001F3FB-\U0001F3FF]*"
    "(?:\u200D[\U0001F300-\U0001FAFF\u2600-\u27BF][\uFE0F]*)*)"
)
# Offers and questions repeated word for word from an earlier reply read as a
# template (Jacques got the same email pitch 4 times). Only those are dropped:
# facts may be repeated on purpose when the client asks again, and short
# sentences ("Dale.") or anything with a number (prices, dates) are kept.
_MIN_REPEATED_SENTENCE_CHARS = 40
_OFFER_RE = re.compile(
    r"\?|e-?mail|\bmail\b|correo|videollamada|video ?call|chamada|asesor|advisor|specialist|consultor|"
    r"\bsi quer[eé]s\b|\bif you(?:'d)? like\b|\bse quiser\b|\bpuedo\b|\bi can\b|\bposso\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")
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


def recent_assistant_replies(recent_turns: Any, limit: int = 3) -> list[str]:
    """The last assistant messages, oldest first."""
    replies = [
        str(t.get("text") or "")
        for t in (recent_turns if isinstance(recent_turns, list) else [])
        if isinstance(t, dict) and t.get("role") == "assistant" and t.get("text")
    ]
    return replies[-limit:] if limit > 0 else []


def _opening_interjection(text: str) -> str | None:
    match = _INTERJECTION_RE.match(text or "")
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group("word").lower()).replace("í", "i").replace("á", "a").replace("é", "e")


def _drop_repeated_opener(text: str, previous_replies: list[str]) -> str:
    """Drop "¡Genial!" when the last reply also opened with a reaction, or when
    the same reaction was used in any of the recent replies."""
    word = _opening_interjection(text)
    if not word or not previous_replies:
        return text
    used = [_opening_interjection(r) for r in previous_replies]
    if used[-1] is None and word not in used:
        return text
    rest = _INTERJECTION_RE.sub("", text, count=1)
    return rest if rest.strip() else text


def _normalize_sentence(sentence: str) -> str:
    return re.sub(r"[^\w ]+", "", re.sub(r"\s+", " ", sentence.lower())).strip()


def _drop_repeated_sentences(text: str, previous_replies: list[str]) -> str:
    seen = {
        _normalize_sentence(s)
        for r in previous_replies
        for s in _SENTENCE_SPLIT_RE.split(r)
        if len(s.strip()) >= _MIN_REPEATED_SENTENCE_CHARS
    }
    if not seen:
        return text
    kept_lines = []
    for line in text.split("\n"):
        parts = re.split(r"(?<=[.!?…])[ \t]+", line)
        kept = [
            p
            for p in parts
            if len(p.strip()) < _MIN_REPEATED_SENTENCE_CHARS
            or re.search(r"\d", p)
            or not _OFFER_RE.search(p)
            or _normalize_sentence(p) not in seen
        ]
        if kept or not line.strip():
            kept_lines.append(" ".join(kept))
    result = "\n".join(kept_lines).strip()
    return result if result else text


def _keep_one_emoji(text: str) -> str:
    found = [0]

    def repl(match: re.Match) -> str:
        found[0] += 1
        return match.group(0) if found[0] == 1 else ""

    return _EMOJI_RE.sub(repl, text)


def humanize_reply(
    reply: str,
    *,
    channel: str = "whatsapp",
    already_spoke: bool = False,
    previous_replies: list[str] | None = None,
) -> str:
    """Clean model output so it reads like a person typing in a chat.

    previous_replies: the last assistant messages in this conversation (oldest
    first), used to avoid opening every message the same way and to drop long
    sentences copied from an earlier reply.
    """
    previous_replies = [r for r in (previous_replies or []) if (r or "").strip()]
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
    for pattern in _FILLER_OPENER_RES + (_THANKS_FOR_ASKING_RES if already_spoke else ()):
        stripped = pattern.sub("", text, count=1)
        if stripped.strip():
            text = stripped

    for pattern in _ROBOTIC_SENTENCE_RES + _APOLOGY_RES:
        text = pattern.sub("", text)

    text = _drop_repeated_opener(text.lstrip(), previous_replies)
    text = _drop_repeated_sentences(text, previous_replies)
    text = _keep_one_emoji(text)
    text = re.sub(r"([!?])\1+", r"\1", text)

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


# --- Who the client is and how they write -------------------------------------

_NAME_WORD = r"[A-ZÁÉÍÓÚÑÜÇ][a-záéíóúñüçãõâêô'-]{1,20}"
_NAME_RES = tuple(
    re.compile(pattern)
    for pattern in (
        rf"(?i:\bme llamo|\bmi nombre es|\bmy name is|\bmeu nome [eé]|\bme chamo)\s+(?P<name>(?i:{_NAME_WORD}))",
        rf"(?i:\bsoy|\bsou(?: o| a)?|\bi'?m|\bi am|\bthis is|\bac[aá] (?:te escribe|habla))\s+(?P<name>{_NAME_WORD})(?=\s*(?:$|[,.!;)]|\s(?:de|from|y|and|e|da|do|desde|aqu[ií]|here)\b))",
        rf"(?i:\b(?:regards|best|cheers|thanks|saludos|abrazo|gracias|abra[cç]o|obrigad[oa]|atte\.?|atentamente)),?\s*\n?\s*(?P<name>{_NAME_WORD})\s*[.!]?\s*$",
    )
)
# Capitalized words that follow "soy"/"I'm" and are not names.
_NOT_A_NAME = {
    w.lower()
    for w in (
        "Argentino Argentina Brasileño Brasileña Chileno Chilena Uruguayo Uruguaya Mexicano Mexicana "
        "Español Española Médico Médica Guía Nuevo Nueva Interested Planning Looking Going Trying Thinking "
        "Not Very Really Just From Here Sure Ok Okay Happy Glad Sorry Brasileiro Brasileira Aconcagua Acomara "
        "Nico Fernando Mendoza Cordoba Córdoba Rosario Buenos Aires Australia Brasil Brazil Chile Usted Yo "
        "Team Equipo Rescue Muy Bien Interesado Interesada Perfecto Perfecta Genial Excelente Great Perfect "
        "Bueno Buena Dale Listo Saludos Abrazo Buenísimo Igualmente Amigo Amiga Crack Capo Maestro Señor Señora "
        "Gente Chicos Todos Everyone Again Mate Bro Fer Igual Nada Mil Muchas Much So Ótimo Obrigado Obrigada "
        "Valeu Legal Total Hermano Querido Querida Anyway Sir Madam Love De La El Un Una "
        "American Brazilian Australian Argentinian Argentine Chilean Mexican Spanish French German Italian British "
        "English Canadian Israeli Dutch Swiss Indian Polish Peruvian Colombian Uruguayan Excited Ready New Back Fine "
        "Francés Francesa Alemán Alemana Italiano Italiana Peruano Peruana Colombiano Colombiana Ingeniero Ingeniera "
        "Profesor Profesora Estudiante Montañista Andinista Principiante"
    ).split()
}


def extract_customer_name(text: str) -> str | None:
    """The client's first name when they introduce themselves or sign a message.

    Conservative on purpose: a wrong name is worse than none. "Soy de Córdoba",
    "I'm interested" and "soy médico" are not names.
    """
    text = (text or "").strip()
    if not text:
        return None
    for pattern in _NAME_RES:
        match = pattern.search(text)
        if match:
            name = match.group("name").strip("'-")
            if name.lower() not in _NOT_A_NAME and len(name) >= 2:
                return name[:1].upper() + name[1:]
    return None


_USTED_RE = re.compile(
    r"\b(?:usted(?:es)?|le (?:agradezco|consulto|escribo|pregunto)|podr[ií]a (?:usted|indicarme|decirme|informarme)|"
    r"me podr[ií]a|quisiera saber|disculpe|perdone|necesitar[ií]a)\b",
    re.IGNORECASE,
)
_VOS_RE = re.compile(r"\b(?:quer[eé]s|ten[eé]s|pod[eé]s|sab[eé]s|decime|pasame|contame|vos)\b", re.IGNORECASE)


def client_messages(recent_turns: Any) -> list[str]:
    """The client's messages in the stored transcript, oldest first."""
    return [
        str(t.get("text") or "")
        for t in (recent_turns if isinstance(recent_turns, list) else [])
        if isinstance(t, dict) and t.get("role") == "user" and t.get("text")
    ]


def client_uses_usted(user_texts: list[str]) -> bool:
    """True when the client writes formally ("usted", "me podría") and never with vos."""
    joined = " ".join(t for t in user_texts if t)
    return bool(_USTED_RE.search(joined)) and not _VOS_RE.search(joined)


def style_hints(
    user_text: str,
    recent_turns: Any,
    *,
    customer_name: str | None = None,
    language: str = "es",
) -> list[str]:
    """Short, concrete style notes for this reply, computed from the chat.

    The model follows "mirror the client" much better when told what the
    client actually did than from a general rule in the system prompt.
    """
    turns = recent_turns if isinstance(recent_turns, list) else []
    user_texts = [*client_messages(turns), user_text or ""]
    previous = recent_assistant_replies(turns, limit=2)
    hints: list[str] = []

    if language == "es" and client_uses_usted(user_texts):
        hints.append('El cliente te trata de "usted": respondé de usted (sin "querés", "tenés", "contame").')
    stripped = (user_text or "").strip()
    if 0 < len(stripped) <= 25 and "?" not in stripped[:-1]:
        hints.append("El cliente escribe corto: contestá en una o dos frases, sin introducción.")
    elif len(stripped) >= 220:
        hints.append("El cliente te contó bastante: reaccioná en pocas palabras a lo que contó y después respondé.")
    if not any(_EMOJI_RE.search(t) for t in user_texts):
        hints.append("El cliente no usa emojis: este mensaje, sin emojis.")
    if customer_name:
        used_recently = any(customer_name.lower() in r.lower() for r in previous)
        if used_recently:
            hints.append(f"Ya usaste el nombre {customer_name} hace poco: esta vez no lo pongas.")
        else:
            hints.append(f"El cliente se llama {customer_name}. Podés usar el nombre una vez, si sale natural.")
    if len(previous) == 2 and all(r.rstrip().endswith("?") for r in previous):
        hints.append("Tus dos últimos mensajes terminaron en pregunta: este no tiene por qué terminar en pregunta.")
    opener = _opening_interjection(previous[-1]) if previous else None
    if opener:
        hints.append(f'Tu mensaje anterior arrancó con "{opener}": arrancá distinto, o directo con la respuesta.')
    return hints


# --- Pacing: how a person splits a reply into WhatsApp messages ----------------

_BUBBLE_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+(?=[¡¿\"'(]?[A-ZÁÉÍÓÚÑ])")
_MAX_REACTION_CHARS = 30
_MIN_BUBBLE_CHARS = 40


def split_single_paragraph(paragraph: str) -> list[str]:
    """Split one paragraph the way people type on WhatsApp.

    A short reaction goes first on its own ("Dale!", then the answer), and a
    closing question goes last on its own after a long answer. Lists and
    anything with line breaks stay together, and short replies stay whole.
    """
    paragraph = (paragraph or "").strip()
    if not paragraph or "\n" in paragraph:
        return [paragraph] if paragraph else []
    sentences = [s for s in _BUBBLE_SENTENCE_RE.split(paragraph) if s.strip()]
    if len(sentences) < 2:
        return [paragraph]
    head: list[str] = []
    tail: list[str] = []
    if len(sentences[0]) <= _MAX_REACTION_CHARS and len(" ".join(sentences[1:])) >= _MIN_BUBBLE_CHARS:
        head = [sentences.pop(0)]
    if (
        len(sentences) >= 2
        and sentences[-1].rstrip().endswith("?")
        and len(" ".join(sentences[:-1])) >= 80
    ):
        tail = [sentences.pop()]
    if not head and not tail:
        return [paragraph]
    return head + [" ".join(sentences)] + tail
