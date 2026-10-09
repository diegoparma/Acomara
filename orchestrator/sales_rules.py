"""Sales rules from Fernando that the model does not apply reliably.

With gpt-4.1-mini, both rules were in the key facts and the model still
missed them (simulation 2026-10-09):

1. The 12+2 and 14+2 are only for people who have been above 6,000 m. The
   model told a Kilimanjaro climber (5,895 m) the 14+2 "can be suitable".
2. When the client shows concrete interest (picks a date, talks about
   booking), Fernando invites them to a short video call. The model never
   did, and closed with "¿Querés que te cuente más?" instead.
"""
from __future__ import annotations

import re
import unicodedata

_SHORT_PROGRAM_RE = re.compile(r"\b1[24]\s*\+\s*2\b|\bascenso (?:rapido|extremo)\b|\b(?:fast|extreme) ascent\b")
# "Is it OK for me?", not "what's the difference between the 14+2 and the 18+2?".
_SUITABILITY_RE = re.compile(
    r"\b(?:me sirve|nos sirve|me conviene|nos conviene|puedo|podemos|podria|alcanza|soy apto|recomendas|me recomendas"
    r"|ok for (?:me|us)|suitable|good (?:for|option for) (?:me|us)|enough|can i|can we|could i|should i|should we"
    r"|me serve|posso|da para)\b"
)
_COMPARISON_RE = re.compile(r"\b(?:diferencia|difference|diferenca|vs|versus|compar\w*)\b")
# Peaks of 6,000 m or more that clients mention, or an explicit altitude >= 6,000.
_ABOVE_6000_RE = re.compile(
    r"\b(?:[6-8][\s.,]?\d{3})\s*(?:m\b|mts|metros|meters|msnm)"
    r"|\b(?:ojos del salado|chimborazo|huascaran|illimani|sajama|parinacota|pissis|mercedario|tupungato"
    r"|denali|mckinley|lenin|everest|lhotse|manaslu|cho oyu|ama dablam|island peak|mera peak|aconcagua antes"
    r"|himalaya|kilimanjaro y (?:el )?(?:chimborazo|huascaran))\b"
)
_BELOW_6000_PEAKS = {
    "kilimanjaro": "el Kilimanjaro (5.895 m)",
    "elbrus": "el Elbrus (5.642 m)",
    "lanin": "el Lanín (3.776 m)",
    "everest base camp": "el campo base del Everest (5.364 m)",
    "mont blanc": "el Mont Blanc (4.806 m)",
}
_BELOW_6000_PEAKS_EN = {
    "kilimanjaro": "Kilimanjaro (5,895 m)",
    "elbrus": "Elbrus (5,642 m)",
    "lanin": "Lanín (3,776 m)",
    "everest base camp": "Everest Base Camp (5,364 m)",
    "mont blanc": "Mont Blanc (4,806 m)",
}

_DATE_PICK_RE = re.compile(
    r"\b\d{1,2}/\d{1,2}\b|\b(?:me interesa la (?:del|salida)|i(?:'m| am) interested in the|quiero la (?:del|salida)"
    r"|tengo interes en la)\b"
)
_BOOKING_RE = re.compile(r"\b(?:reservar|reserva|reservo|book|booking|reserve|reservation)\b")
_VIDEO_WORD_RE = re.compile(r"videollamada|video ?call|videochamada", re.IGNORECASE)

SHORT_PROGRAM_REPLY = {
    "es": (
        "Te soy sincero: el {program} es solo para quien ya estuvo arriba de los 6.000 m, está muy entrenado y llega aclimatado. "
        "{peak_sentence}Te recomiendo el 18+2: cuesta lo mismo y tiene más días para aclimatar, que es lo que más sube las chances de cumbre."
    ),
    "en": (
        "To be honest, the {program} is only for people who have already been above 6,000 m, are very well trained and arrive acclimatized. "
        "{peak_sentence}I'd recommend the 18+2: same price, more days to acclimatize, and that's what raises your summit chances the most."
    ),
    "pt": (
        "Sendo sincero: o {program} é só para quem já esteve acima de 6.000 m, está muito bem treinado e chega aclimatado. "
        "{peak_sentence}Recomendo o 18+2: custa o mesmo e tem mais dias para aclimatar, o que mais aumenta as chances de cume."
    ),
}
PEAK_SENTENCE = {
    "es": "{peak} no llega a esa altura. ",
    "en": "{peak} doesn't reach that altitude. ",
    "pt": "{peak} não chega a essa altitude. ",
}
VIDEO_CALL_INVITE = {
    "es": "Si querés, armamos una videollamada corta y lo vemos juntos: decime día, hora y desde qué ciudad me escribís.",
    "en": "If you'd like, we can set up a short video call and go over it together: just tell me a day, a time and your city.",
    "pt": "Se quiser, marcamos uma videochamada rápida e vemos juntos: me diz dia, horário e de que cidade você fala.",
}
VIDEO_CALL_INVITE_WITH_EMAIL = {
    "es": "Si querés, armamos una videollamada corta y lo vemos juntos: decime día, hora y desde qué ciudad me escribís, y pasame tu email así te mando el detalle.",
    "en": "If you'd like, we can set up a short video call and go over it together: tell me a day, a time and your city, and send me your email so I can share the details.",
    "pt": "Se quiser, marcamos uma videochamada rápida e vemos juntos: me diz dia, horário e de que cidade você fala, e me passa seu email para eu te mandar o detalhe.",
}
_EMAIL_KEYS = ("email_captured", "captured_email", "email_requested", "verified_email")
DATE_AVAILABILITY_NOTE = {
    "es": "La disponibilidad de esa fecha te la confirma un asesor.",
    "en": "An advisor will confirm availability for that date.",
    "pt": "A disponibilidade dessa data um consultor te confirma.",
}


def _normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", (text or "").lower())
    return " ".join(folded.encode("ascii", "ignore").decode("ascii").split())


def short_program_reply(user_text: str, lang: str) -> str | None:
    """Fixed answer when someone without 6,000 m experience asks about the 12+2 or 14+2."""
    text = _normalize(user_text)
    program_match = _SHORT_PROGRAM_RE.search(text)
    if (
        not program_match
        or not _SUITABILITY_RE.search(text)
        or _COMPARISON_RE.search(text)
        or _ABOVE_6000_RE.search(text)
    ):
        return None
    lang = lang if lang in SHORT_PROGRAM_REPLY else "es"
    program = "12+2" if "12" in program_match.group(0) or "extrem" in program_match.group(0) else "14+2"
    peaks = _BELOW_6000_PEAKS_EN if lang == "en" else _BELOW_6000_PEAKS
    peak = next((label for key, label in peaks.items() if key in text), None)
    peak_sentence = PEAK_SENTENCE[lang].format(peak=peak[:1].upper() + peak[1:]) if peak else ""
    return SHORT_PROGRAM_REPLY[lang].format(program=program, peak_sentence=peak_sentence)


def shows_concrete_interest(user_text: str) -> tuple[bool, bool]:
    """(interested, picked_a_date): the client picks a date or talks about booking."""
    text = _normalize(user_text)
    picked_date = bool(_DATE_PICK_RE.search(text))
    return picked_date or bool(_BOOKING_RE.search(text)), picked_date


def _drop_trailing_question(reply: str) -> str:
    """Remove a closing generic question ("¿Querés que te cuente más?") before the invite."""
    sentences = re.split(r"(?<=[.!?])\s+", reply.strip())
    if len(sentences) > 1 and sentences[-1].endswith("?") and not re.search(r"\d", sentences[-1]):
        return " ".join(sentences[:-1]).strip()
    return reply.strip()


def apply_video_call_close(reply: str, user_text: str, session_vars: dict, lang: str, has_email: bool = False) -> str:
    """Close with Fernando's video call invite on concrete interest, once per conversation."""
    if not reply.strip() or session_vars.get("video_call_offered"):
        return reply
    if _VIDEO_WORD_RE.search(reply):
        session_vars["video_call_offered"] = True
        return reply
    interested, picked_date = shows_concrete_interest(user_text)
    if not interested:
        return reply
    lang = lang if lang in VIDEO_CALL_INVITE else "es"
    parts = [_drop_trailing_question(reply)]
    if picked_date:
        parts.append(DATE_AVAILABILITY_NOTE[lang])
    session_vars["video_call_offered"] = True
    # Fernando asks for the email together with the call when we don't have it yet.
    known_email = has_email or any(session_vars.get(k) for k in _EMAIL_KEYS)
    invite = VIDEO_CALL_INVITE if known_email else VIDEO_CALL_INVITE_WITH_EMAIL
    return " ".join(parts) + "\n\n" + invite[lang]
