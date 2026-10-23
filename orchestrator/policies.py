from __future__ import annotations

import re
from typing import Any, Callable


GetPhraseFn = Callable[[str, str | None], str]
ShouldRequestEmailFn = Callable[[dict[str, Any] | None], bool]
MentionsOutOfSeasonFn = Callable[[str], bool]
DetectExplicitLanguagePreferenceFn = Callable[[str], str | None]
DetectLanguageConfidentFn = Callable[[str], str | None]
GetSessionLanguageFn = Callable[[dict[str, Any] | None, str], str]


_EMAIL_WORD_RE = re.compile(r"\b(?:e-?mail|correo|mail)\b", re.IGNORECASE)


_EMAIL_ASK_CUE_RE = re.compile(
    r"\?|\b(?:pasame|pasás|pasas|mandame|dejame|compartime|escribime|send me|share|what'?s your|me passa|me manda)\b",
    re.IGNORECASE,
)
_EMAIL_KNOWN_KEYS = ("email_requested", "email_captured", "captured_email", "verified_email")


def drop_repeated_email_ask(reply: str, session_vars: dict[str, Any]) -> str:
    """Remove the model's own email ask when it was already asked or given.

    Simulation 2026-10-09: the reply closed with "¿Querés que te pase el
    detalle por email?" two turns after the email had been asked.
    """
    if not any(session_vars.get(k) for k in _EMAIL_KNOWN_KEYS):
        return reply
    sentences = re.split(r"(?<=[.!?])\s+", (reply or "").strip())
    kept = [s for s in sentences if not (_EMAIL_WORD_RE.search(s) and _EMAIL_ASK_CUE_RE.search(s))]
    return " ".join(kept).strip() if kept else reply


def _reply_asks_for_email(reply: str) -> bool:
    return bool(_EMAIL_WORD_RE.search(reply or ""))


def _asks_more_than_email(user_text: str, email: str) -> bool:
    rest = (user_text or "").replace(email, " ").strip(" \t\n.,;:!-")
    return "?" in rest or len(rest.split()) >= 6


def apply_email_ack_or_request_policy(
    reply: str,
    session_vars: dict[str, Any],
    extracted_email: str | None,
    lang: str,
    *,
    get_phrase: GetPhraseFn,
    should_request_email: ShouldRequestEmailFn,
    user_text: str = "",
) -> str:
    """Apply deterministic email ack/request policy without side effects outside session_vars."""
    if extracted_email and not session_vars.get("email_received_acked"):
        if _asks_more_than_email(user_text, extracted_email) and reply.strip():
            # "mi mail es x, cuanto sale el 18+2?": thank briefly and still
            # answer, instead of replacing the answer with the ack.
            reply = f"{get_phrase('email_received_short', lang)}\n\n{reply}"
        else:
            reply = get_phrase("email_received_ack", lang).format(email=extracted_email)
        session_vars["email_received_acked"] = True
        session_vars["email_captured"] = True
        session_vars["captured_email"] = extracted_email
        session_vars["email_requested"] = True
        session_vars["proactive_email_capture_pending"] = False
    elif should_request_email(session_vars):
        if not _reply_asks_for_email(reply):
            # The model often asks for it itself; asking twice in one message reads as a bot.
            reply = f"{reply}\n\n{get_phrase('proactive_email_request', lang)}"
        session_vars["email_requested"] = True
        session_vars["proactive_email_capture_pending"] = True
    return reply


def apply_out_of_season_policy(
    reply: str,
    user_text: str,
    session_vars: dict[str, Any],
    lang: str,
    *,
    mentions_out_of_season: MentionsOutOfSeasonFn,
    get_phrase: GetPhraseFn,
) -> str:
    """Prepend out-of-season warning once per conversation when intent is present."""
    if mentions_out_of_season(user_text) and not session_vars.get("out_of_season_warned"):
        reply = f"{get_phrase('out_of_season', lang)}\n\n{reply}"
        session_vars["out_of_season_warned"] = True
    return reply


def apply_language_commit_policy(
    user_text: str,
    session_vars: dict[str, Any],
    *,
    detect_explicit_language_preference: DetectExplicitLanguagePreferenceFn,
    detect_language_confident: DetectLanguageConfidentFn,
    i18n_languages: set[str],
    get_session_language: GetSessionLanguageFn,
) -> None:
    """Commit language only for explicit or confident signals; otherwise preserve current value."""
    explicit_pref = detect_explicit_language_preference(user_text)
    if explicit_pref and explicit_pref in i18n_languages:
        session_vars["conversation_language"] = explicit_pref
        session_vars["conversation_language_source"] = "user_preference_explicit"
        session_vars["conversation_language_locked"] = True
        return

    # Keep explicit lock stable for ambiguous/non-linguistic messages
    # (emails, short acknowledgements, etc.).
    if session_vars.get("conversation_language_locked") and session_vars.get("conversation_language") in i18n_languages:
        return

    confident_lang = detect_language_confident(user_text)
    if confident_lang and confident_lang in i18n_languages:
        session_vars["conversation_language"] = confident_lang
        session_vars["conversation_language_source"] = "message_detected"
        session_vars["conversation_language_locked"] = False
    elif not session_vars.get("conversation_language"):
        session_vars["conversation_language"] = get_session_language(session_vars, user_text)
        session_vars["conversation_language_source"] = "message_detected_low_confidence"
        session_vars["conversation_language_locked"] = False
