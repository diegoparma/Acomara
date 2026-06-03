from __future__ import annotations

from typing import Any, Callable


GetPhraseFn = Callable[[str, str | None], str]
ShouldRequestEmailFn = Callable[[dict[str, Any] | None], bool]
MentionsOutOfSeasonFn = Callable[[str], bool]
DetectExplicitLanguagePreferenceFn = Callable[[str], str | None]
DetectLanguageConfidentFn = Callable[[str], str | None]
GetSessionLanguageFn = Callable[[dict[str, Any] | None, str], str]


def apply_email_ack_or_request_policy(
    reply: str,
    session_vars: dict[str, Any],
    extracted_email: str | None,
    lang: str,
    *,
    get_phrase: GetPhraseFn,
    should_request_email: ShouldRequestEmailFn,
) -> str:
    """Apply deterministic email ack/request policy without side effects outside session_vars."""
    if extracted_email and not session_vars.get("email_received_acked"):
        reply = get_phrase("email_received_ack", lang).format(email=extracted_email)
        session_vars["email_received_acked"] = True
        session_vars["email_captured"] = True
        session_vars["captured_email"] = extracted_email
        session_vars["email_requested"] = True
        session_vars["proactive_email_capture_pending"] = False
    elif should_request_email(session_vars):
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
