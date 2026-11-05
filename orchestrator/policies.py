from __future__ import annotations

import re
import unicodedata
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
_EMAIL_KNOWN_KEYS = ("email_requested", "email_captured", "captured_email", "verified_email", "email_declined")

_EMAIL_NOUN = r"(?:e-?mail|mail|correo|email)"
_EMAIL_DEFERRAL_RE = re.compile(
    # "prefiero no dar mi mail", "no quiero pasar el correo", "prefiro nao passar o email"
    rf"\b(?:prefiero|prefiro|preferimos|no quiero|no puedo|nao quero|nao posso|i(?:'d)? rather not|prefer not to|dont want to|do not want to)\s+(?:no\s+|nao\s+)?(?:dar|pasar|compartir|dejar|enviar|mandar|passar|dar|share|give|send|leave)\b[^.?!]{{0,25}}{_EMAIL_NOUN}"
    # "no te doy mi mail", "no voy a pasar el email"
    rf"|\bno (?:te |les )?(?:doy|paso|dejo|voy a (?:dar|pasar|dejar))\b[^.?!]{{0,20}}{_EMAIL_NOUN}"
    # "despues te paso el mail", "te lo mando luego", "i'll send it later", "depois te mando"
    rf"|\b(?:despues|luego|mas tarde|manana|depois|mais tarde|later|tomorrow)\b[^.?!]{{0,25}}\b(?:paso|mando|envio|escribo|doy|passo|mandarei|send|share|give)\b[^.?!]{{0,25}}{_EMAIL_NOUN}"
    rf"|\b(?:te|les|lhe|you)\s+(?:lo |la |o |a )?(?:paso|mando|envio|escribo|passo|mandarei|will send|ll send|send)\b[^.?!]{{0,25}}{_EMAIL_NOUN}[^.?!]{{0,25}}\b(?:despues|luego|mas tarde|manana|depois|mais tarde|later|tomorrow)\b"
    rf"|{_EMAIL_NOUN}[^.?!]{{0,20}}\b(?:te lo|lo|te a|a)\s*(?:paso|mando|envio|passo|mandarei)\b[^.?!]{{0,15}}\b(?:despues|luego|mas tarde|manana|depois|mais tarde)\b"
    rf"|\b(?:send|share|give)\b[^.?!]{{0,15}}{_EMAIL_NOUN}[^.?!]{{0,15}}\blater\b"
    # "prefiero por aca / por whatsapp / por aqui"
    r"|\b(?:prefiero|prefiro|i prefer|rather)\b[^.?!]{0,15}\b(?:aca|aqui|here|whatsapp|este medio|por este canal)\b"
)


def _fold(text: str) -> str:
    folded = unicodedata.normalize("NFKD", (text or "").lower())
    return " ".join(folded.encode("ascii", "ignore").decode("ascii").split())


def declines_or_defers_email(user_text: str) -> bool:
    """The client says they will send the email later or would rather not give it.

    Asking again after that read as a bot that does not listen (fallas-top10 #3).
    """
    return bool(_EMAIL_DEFERRAL_RE.search(_fold(user_text)))


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


def _split_trailing_question(reply: str) -> tuple[str, str]:
    """(answer, closing question) when the reply ends with a question; else (reply, "")."""
    text = (reply or "").rstrip()
    if not text.endswith("?"):
        return text, ""
    cut = max(text.rfind(mark, 0, len(text) - 1) for mark in (".", "!", "?", "\n"))
    if cut <= 0:
        return text, ""
    question = text[cut + 1 :].strip()
    if re.search(r"\d", question):  # "¿Te sirve la del 5/12?" carries data: keep it.
        return text, ""
    return text[: cut + 1].rstrip(), question


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
            # A person doesn't close with a question and then ask for the email
            # in the same breath: the (once per conversation) email ask takes
            # the place of a closing question without data. Waiting a turn
            # instead lost the ask when the client said "lo hablo y te aviso".
            reply, _ = _split_trailing_question(reply)
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
        warning = get_phrase("out_of_season", lang)
        if _OFFER_RE.search(reply or ""):
            # The reply already offers something ("Si querés, pasame tu email"):
            # two "si querés" in one message reads like stacked templates, so
            # the warning drops its own offer to send next season's dates.
            warning = _drop_last_sentence(warning)
        reply = f"{warning}\n\n{reply}"
        session_vars["out_of_season_warned"] = True
    return reply


_OFFER_RE = re.compile(r"\bsi quer[eé]s\b|\bsi quiere\b|\bif you'?d like\b|\bse quiser\b", re.IGNORECASE)


def _drop_last_sentence(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[:-1]) if len(sentences) > 1 else text


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
