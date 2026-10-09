#!/usr/bin/env python3
"""OpenBSP + Session Agent + RAG Orchestrator.

MVP flow:
1) Receive inbound webhook payload (or direct test payload).
2) Normalize conversation/contact/message fields.
3) Append inbound event and upsert session state in session-agent.
4) Retrieve top-k FAQ chunks by embeddings.
5) Generate grounded sales reply.
6) Optionally send outbound message through an OpenBSP-compatible endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from openai import OpenAI

from orchestrator.security import (
    bot_signal,
    check_email_reputation,
    extract_email_from_text,
    pause_conversation,
    should_request_email,
)
from orchestrator.handoff_email import (
    try_send_handoff_email,
    try_send_new_lead_email,
    try_send_suspicious_admin_alert,
)
from orchestrator.policies import (
    apply_email_ack_or_request_policy as _apply_email_ack_or_request_policy,
    apply_language_commit_policy as _apply_language_commit_policy,
    apply_out_of_season_policy as _apply_out_of_season_policy,
)
from orchestrator.observability import (
    build_health_response,
    build_safe_version_response,
    build_version_payload as _build_version_payload,
    build_version_text as _build_version_text,
    parse_bool_query,
    render_audit_dashboard_html,
)
from orchestrator.session_client import (
    session_headers as _session_headers,
    session_get as _session_get,
    session_delete as _session_delete,
    session_append_event as _session_append_event,
    session_upsert as _session_upsert,
    try_session_get as _try_session_get,
    try_session_append_event as _try_session_append_event,
    try_session_upsert as _try_session_upsert,
    try_session_delete as _try_session_delete,
)
from orchestrator.inbound import (
    validate_and_normalize_headers as _validate_and_normalize_headers,
)
from orchestrator.crm_client_status import check_client_status
from orchestrator.departures import ensure_departure_hit, filter_past_departures
from orchestrator.humanize import (
    append_recent_turns,
    assistant_already_spoke,
    history_to_messages,
    humanize_reply,
    trim_to_last_sentence,
)
from orchestrator.human_activity import DEFAULT_NICO_AGENT_ID, human_replied_recently
from orchestrator.conversation_audit import DEFAULT_ORG_ID, run_conversation_audit

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "docs" / "knowledge" / "faq_cloud_index.jsonl"
SYSTEM_PROMPT_PATH = ROOT / "docs" / "sales-agent" / "02-system-prompt.md"
KEY_FACTS_PATH = ROOT / "docs" / "knowledge" / "datos-clave.md"

app = Flask(__name__)


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """Typed envelope for inbound message metadata used across the pipeline."""

    text: str
    conversation_id: str
    organization_id: str
    organization_address: str
    contact_id: str
    contact_address: str
    channel: str

    @classmethod
    def from_headers(cls, text: str, headers_dict: dict[str, str]) -> InboundMessage:
        return cls(
            text=text,
            conversation_id=headers_dict["conversation_id"],
            organization_id=headers_dict["organization_id"],
            organization_address=headers_dict["organization_address"],
            contact_id=headers_dict["contact_id"],
            contact_address=headers_dict["contact_address"],
            channel=headers_dict["channel"],
        )

    def as_dict(self) -> dict[str, str]:
        return {
            "text": self.text,
            "conversation_id": self.conversation_id,
            "organization_id": self.organization_id,
            "organization_address": self.organization_address,
            "contact_id": self.contact_id,
            "contact_address": self.contact_address,
            "channel": self.channel,
        }


@dataclass(slots=True)
class ProcessingContext:
    """Mutable per-request state that is deterministic and testable."""

    session_vars: dict[str, Any]
    now_ts: int
    inbound_signature: str
    extracted_email: str | None = None
    handoff_requested: bool = False
    email_suspicious: bool = False
    suspicious_email_value: str = ""
    email_suspicious_alert_sent: bool = False


@dataclass(slots=True)
class ReplyDecision:
    """Decision output from policy/routing stage before persistence."""

    reply: str
    hits: list[dict[str, Any]] = field(default_factory=list)
    handoff_attempted: bool = False
    handoff_status: int = 0
    handoff_data: dict[str, Any] = field(default_factory=dict)
    handoff_sent: bool = False
    outbound_suppressed: bool = False
    outbound_safety_blocked: bool = False


# i18n: Internationalization layer for fixed phrases
I18N_PHRASES = {
    "es": {
        "reset_acknowledge": "Conversación reiniciada. ¿En qué te puedo ayudar?",
        "handoff_ask_email": "Dale, te paso con un asesor del equipo. ¿Me dejás tu email así te contacta?",
        "handoff_executed": "Listo, ya le pasé tu consulta a un asesor del equipo. Te escribe por acá en breve 🙌",
        "handoff_pending": "Me falta tu email para pasarte con el asesor. ¿Cuál es?",
        "proactive_email_request": "Si querés, pasame tu email y te mando el detalle completo con precios y fechas.",
        "proactive_email_saved": "Genial, ya me quedó tu email. Si después querés hablar con un asesor, avisame y te paso.",
        "proactive_email_check_failed": "Gracias, ya me quedó tu email. Si en algún momento querés hablar con un asesor, avisame.",
        "paused_handoff": "Ya le pasé tu consulta a un asesor, te escribe por acá en breve.",
        "paused_suspicious": "Perfecto, te escribimos en breve.",
        "paused_proactive_email": "Pasame tu email cuando puedas y seguimos.",
        "paused_loop_final": "Ya quedó todo registrado. En breve te escribe alguien del equipo por acá, no hace falta que mandes nada más 👍",
        "repeat_prefix": "Como te decía,",
        "thanks_reply_1": "¡De nada! Cualquier cosa me escribís por acá.",
        "thanks_reply_2": "¡Un placer! Si te surge otra duda, acá estoy.",
        "bot_question": "Soy el asistente digital del equipo de Acomara 🙂 Te respondo por acá lo que necesites, y si preferís hablar con un asesor, avisame y te paso.",
        "email_received_short": "¡Gracias! Ya tengo tu email, se lo paso a un asesor del equipo.",
        "email_received_ack": "¡Gracias! Ya tengo tu email ({email}). Un asesor del equipo revisa tu consulta y te escribe por acá. Si querés sumar algo (fechas, cuántos son, experiencia previa), contame y lo agrego.",
        "out_of_season": "Ojo: las expediciones al Aconcagua son solo de noviembre a marzo (temporada del hemisferio sur), así que para esa fecha no tenemos salidas. Si querés te paso las fechas de la próxima temporada.",
        "opening_welcome": "¡Hola! Gracias por escribirnos. ¿En qué te puedo ayudar?\n\nSi te sirve, además de responderte por acá te mando por email toda la info: precios, fechas, servicios, lista de equipo y recomendaciones.",
    },
    "en": {
        "reset_acknowledge": "Conversation restarted. How can I help you?",
        "handoff_ask_email": "Sure, I'll put you in touch with one of our advisors. What's your email so they can reach you?",
        "handoff_executed": "Done, I've passed your request to one of our advisors. They'll message you here shortly 🙌",
        "handoff_pending": "I just need your email to pass you to the advisor. What is it?",
        "proactive_email_request": "If you'd like, send me your email and I'll share the full details with prices and dates.",
        "proactive_email_saved": "Great, got your email. If you want to talk to an advisor later, just let me know.",
        "proactive_email_check_failed": "Thanks, got your email. If you'd like to talk to an advisor at some point, just let me know.",
        "paused_handoff": "I've passed your request to an advisor, they'll message you here shortly.",
        "paused_suspicious": "Great! We'll be in touch shortly.",
        "paused_proactive_email": "Send me your email whenever you can and we'll continue.",
        "paused_loop_final": "It's all noted. Someone from the team will message you here shortly, no need to send anything else 👍",
        "repeat_prefix": "As I mentioned,",
        "thanks_reply_1": "You're welcome! Message me here anytime.",
        "thanks_reply_2": "My pleasure! If anything else comes up, I'm here.",
        "bot_question": "I'm the Acomara team's digital assistant 🙂 I can answer whatever you need here, and if you'd rather talk to an advisor, just let me know.",
        "email_received_short": "Thanks! Got your email, I'll pass it to one of our advisors.",
        "email_received_ack": "Thanks! I've got your email ({email}). One of our advisors will review your request and message you here. If you want to add anything (dates, group size, previous experience), tell me and I'll include it.",
        "out_of_season": "Heads up: Aconcagua expeditions only run from November to March (Southern Hemisphere season), so we don't have departures on that date. If you'd like, I can share the dates for next season.",
        "opening_welcome": "Hi! Thanks for reaching out. How can I help?\n\nIf it's useful, besides answering here I can email you all the info: prices, dates, services, gear list and recommendations.",
    },
    "pt": {
        "reset_acknowledge": "Conversa reiniciada. Como posso te ajudar?",
        "handoff_ask_email": "Claro, vou te passar para um consultor da equipe. Qual é o seu email para ele entrar em contato?",
        "handoff_executed": "Pronto, já passei sua consulta para um consultor da equipe. Ele te escreve por aqui em breve 🙌",
        "handoff_pending": "Só falta seu email para te passar para o consultor. Qual é?",
        "proactive_email_request": "Se quiser, me passa seu email e te mando o detalhe completo com preços e datas.",
        "proactive_email_saved": "Ótimo, já anotei seu email. Se depois quiser falar com um consultor, é só me avisar.",
        "proactive_email_check_failed": "Obrigado, já anotei seu email. Se em algum momento quiser falar com um consultor, é só me avisar.",
        "paused_handoff": "Já passei sua consulta para um consultor, ele te escreve por aqui em breve.",
        "paused_suspicious": "Perfeito, vamos te escrever em breve.",
        "paused_proactive_email": "Me passa seu email quando puder e seguimos.",
        "paused_loop_final": "Já ficou tudo registrado. Em breve alguém da equipe te escreve por aqui, não precisa mandar mais nada 👍",
        "repeat_prefix": "Como te falei,",
        "thanks_reply_1": "De nada! Qualquer coisa me escreve por aqui.",
        "thanks_reply_2": "Imagina! Se surgir outra dúvida, estou por aqui.",
        "bot_question": "Sou o assistente digital da equipe da Acomara 🙂 Te respondo por aqui o que precisar, e se preferir falar com um consultor, é só me avisar.",
        "email_received_short": "Obrigado! Já tenho seu email, vou passar para um consultor da equipe.",
        "email_received_ack": "Obrigado! Já tenho seu email ({email}). Um consultor da equipe vai ver sua consulta e te escreve por aqui. Se quiser acrescentar algo (datas, quantas pessoas, experiência prévia), me conta que eu incluo.",
        "out_of_season": "Atenção: as expedições ao Aconcágua acontecem só de novembro a março (temporada do hemisfério sul), então para essa data não temos saídas. Se quiser, te passo as datas da próxima temporada.",
        "opening_welcome": "Olá! Obrigado por escrever. Como posso te ajudar?\n\nSe for útil, além de responder por aqui te mando por email todas as informações: preços, datas, serviços, lista de equipamentos e recomendações.",
    },
}


def detect_language_from_text(text: str) -> str:
    """Simple language detection from message content.

    Returns detected language code (es/pt/en) or 'es' as conservative default.
    Treats short ambiguous greetings ("hola"/"olá"/"hi") as unknown -> caller
    keeps the previous session language instead of locking in on the first
    greeting (which historically caused language drift).
    """
    return _detect_language_with_evidence(text) or "es"


def _detect_language_with_evidence(text: str) -> str | None:
    """Detect es/pt/en from message content, or None when there is no signal.

    Keeping "no signal" separate from "Spanish" matters: callers that rotate the
    session language must not treat the Spanish fallback as a real detection
    (that made English speakers get Spanish replies mid-conversation).
    """
    if not text:
        return None

    text_lower = text.lower()
    normalized_text = unicodedata.normalize("NFKD", text_lower)
    normalized_text = normalized_text.encode("ascii", "ignore").decode("ascii")

    # Strong-signal tokens (each language) that should immediately win.
    strong_en_tokens = (
        "i would",
        "i'd like",
        "i want",
        "i need",
        "i'm interested",
        "interested in",
        "could you",
        "please send",
        "regards",
        "thanks",
        "thank you",
        "summit",
        "expedition",
        "ascent",
    )
    strong_pt_tokens = (
        "gostaria",
        "obrigado",
        "obrigada",
        "voce",
        "quero fazer",
        "quero saber",
        "este passeio",
        "qual e",
        "tem alguma",
        # NOTE: do not add "ola" here — it would substring-match "hola" (es)
        # and "español". The standalone "olá" greeting is too short to lock
        # the language on its own; it is handled via word-boundary keyword_count
        # below and the < 20-char fallback in detect_language_confident.
    )
    strong_es_tokens = (
        "quiero",
        "quisiera",
        "necesito",
        "me interesa",
        "buen dia",
        "buenas",
        "podrias",
        "podria",
        "gracias",
    )

    for tok in strong_en_tokens:
        if tok in normalized_text:
            return "en"
    for tok in strong_pt_tokens:
        if tok in normalized_text:
            return "pt"
    for tok in strong_es_tokens:
        if tok in normalized_text:
            return "es"

    def keyword_count(keywords: tuple[str, ...]) -> int:
        count = 0
        for keyword in keywords:
            pattern = r"(?<!\w)" + re.escape(keyword) + r"(?!\w)"
            if re.search(pattern, normalized_text):
                count += 1
        return count

    es_keywords = (
        "hola",
        "buen dia",
        "buenos",
        "buenas",
        "que",
        "como",
        "donde",
        "cuando",
        "gracias",
        "por favor",
        "si",
        "ayuda",
        "pregunta",
        "informacion",
        "quisiera",
        "quiero",
        "necesito",
        "tengo",
        "me interesa",
        "ascenso",
        # NOTE: do not add "aconcagua" — it is a proper noun used in every
        # language and made English messages tie with Spanish.
    )
    pt_keywords = (
        "oi",
        "ola",
        "como",
        "onde",
        "obrigado",
        "por favor",
        "sim",
        "nao",
        "ajuda",
        "pergunta",
        "informacao",
        "gostaria",
        "preciso",
        "tenho",
        "estou",
    )
    en_keywords = (
        "hello",
        "hi",
        "thanks",
        "thank you",
        "please",
        "help",
        "question",
        "information",
        "i want",
        "i need",
        "interested",
        "expedition",
        "route",
    )

    es_count = keyword_count(es_keywords)
    pt_count = keyword_count(pt_keywords)
    en_count = keyword_count(en_keywords)

    # Secondary signal: common function words improve robustness on colloquial
    # user messages (e.g., "Do u have 12 days sir?") where domain keywords are
    # sparse and the old heuristic defaulted to Spanish.
    words = re.findall(r"\b[a-z]+\b", normalized_text)
    word_set = set(words)
    es_stopwords = {
        "de", "la", "el", "que", "en", "y", "por", "para", "con", "una", "un",
        "hola", "buenas", "aun", "ninguna", "te", "me", "quiero", "necesito",
    }
    pt_stopwords = {
        "de", "do", "da", "que", "em", "e", "por", "para", "com", "uma", "um",
        "oi", "ola", "voce", "nao", "sim", "quero", "gostaria", "pergunta",
    }
    en_stopwords = {
        "the", "and", "for", "with", "to", "from", "please", "hello", "hi", "thanks",
        "i", "you", "we", "can", "do", "have", "sir", "week", "next", "my",
        "is", "are", "it", "what", "how", "will", "am", "this", "that", "of",
        "if", "now", "about", "because", "only", "any", "there", "your", "be",
        "would", "should", "price", "yes", "appreciate", "available", "climb",
        "climbing",
    }
    es_word_score = len(word_set & es_stopwords)
    pt_word_score = len(word_set & pt_stopwords)
    en_word_score = len(word_set & en_stopwords)

    if en_count > es_count and en_count > pt_count and en_count > 0:
        return "en"

    if es_count > pt_count and es_count > 0:
        return "es"
    # Avoid over-triggering PT on a single weak token inside mostly-Spanish text
    # (e.g. "Aun no te había hecho ninguna pergunta aun").
    if pt_count > es_count and pt_count >= 2:
        return "pt"

    if en_word_score > es_word_score and en_word_score > pt_word_score and en_word_score >= 2:
        return "en"
    if pt_word_score > es_word_score and pt_word_score > en_word_score and pt_word_score >= 2:
        return "pt"
    if es_word_score > pt_word_score and es_word_score > en_word_score and es_word_score >= 2:
        return "es"

    return None


def detect_language_confident(text: str) -> str | None:
    """Detect language only when there is enough evidence; else return None.

    Used to avoid locking the conversation language on a short ambiguous
    greeting (e.g. "Hola"/"Olá"/"Hi"). The caller should keep the previous
    session language when this returns None.
    """
    if not text:
        return None

    stripped = text.strip()
    # Non-linguistic payloads must not rotate session language.
    if "@" in stripped or stripped.startswith("http://") or stripped.startswith("https://"):
        return None
    if len(stripped) < 6:
        return None

    text_lower = stripped.lower()
    normalized_text = unicodedata.normalize("NFKD", text_lower)
    normalized_text = normalized_text.encode("ascii", "ignore").decode("ascii")

    strong_en_tokens = (
        "i would", "i'd like", "i want", "i need", "i'm interested",
        "interested in", "could you", "please send", "regards",
        "thank you", "summit", "expedition", "ascent",
    )
    strong_pt_tokens = (
        "gostaria", "obrigado", "obrigada", "quero fazer", "quero saber",
        "este passeio", "qual e", "tem alguma", "voce", "para mim",
    )
    strong_es_tokens = (
        "quiero", "quisiera", "necesito", "me interesa", "buenos dias",
        "buenas tardes", "podrias", "podria", "gracias", "por favor",
    )

    for tok in strong_en_tokens:
        if tok in normalized_text:
            return "en"
    for tok in strong_pt_tokens:
        if tok in normalized_text:
            return "pt"
    for tok in strong_es_tokens:
        if tok in normalized_text:
            return "es"

    # Fallback: only commit when the heuristic found actual evidence. A
    # non-trivial message with mostly english/portuguese keywords is reasonable
    # evidence; a single "hola" is not.
    detected = _detect_language_with_evidence(text)
    if detected == "es" and len(stripped) < 20:
        return None
    return detected


def detect_explicit_language_preference(text: str) -> str | None:
    """Detect direct user requests for a specific conversation language."""
    normalized = normalize_for_intent(text)

    en_patterns = (
        "english please",
        "speak english",
        "in english",
        "i dont speak spanish",
        "i do not speak spanish",
    )
    es_patterns = (
        "espanol por favor",
        "habla en espanol",
        "en espanol",
        "no hablo ingles",
    )
    pt_patterns = (
        "portugues por favor",
        "fale em portugues",
        "em portugues",
    )

    if any(pattern in normalized for pattern in en_patterns):
        return "en"
    if any(pattern in normalized for pattern in es_patterns):
        return "es"
    if any(pattern in normalized for pattern in pt_patterns):
        return "pt"
    return None


# Months treated as out-of-Aconcagua-season (April-October).
OUT_OF_SEASON_MONTH_TOKENS = (
    # English ("may" is handled separately: it is also a modal verb)
    "april", "june", "july", "august", "september", "october",
    # Spanish (normalized: no accents)
    "abril", "mayo", "junio", "julio", "agosto", "septiembre", "setiembre", "octubre",
    # Portuguese
    "maio", "junho", "julho", "agosto", "setembro", "outubro",
)
_OUT_OF_SEASON_MONTHS = range(4, 11)
# English "may" only counts as the month next to a date-like context
# ("in May", "May 12", "12th of May"), never as the modal verb ("May I...").
_MAY_MONTH_RE = re.compile(
    r"\b(?:in|on|of|during|early|late|mid|next|this|by|until)\s+may\b"
    r"|\bmay\s+\d"
    r"|\d(?:st|nd|rd|th)?\s+(?:of\s+)?may\b"
)
# Numeric day/month pairs (27/05, 05-27, 15/05/2027). Ranges followed by a
# unit ("4-6 personas", "5-7 dias") are quantities, not dates.
_NUMERIC_DATE_RE = re.compile(
    r"\b(\d{1,2})[/-](\d{1,2})\b(?!\s*(?:personas?|pessoas?|people|persons?|pax|dias?|days?"
    r"|noches?|noites?|nights?|semanas?|weeks?|horas?|hours?|km|kg|anos?|years?))"
)


def _numeric_date_is_out_of_season(first: int, second: int) -> bool:
    """True only when every valid reading (DD/MM and MM/DD) lands in Apr-Oct.

    "5/12" is 5 December for a Spanish/Portuguese speaker, a real departure,
    so an ambiguous pair must not trigger the out-of-season warning.
    """
    months = []
    if 1 <= second <= 12 and 1 <= first <= 31:
        months.append(second)  # DD/MM
    if 1 <= first <= 12 and 1 <= second <= 31:
        months.append(first)  # MM/DD
    return bool(months) and all(m in _OUT_OF_SEASON_MONTHS for m in months)
_TRIP_INTENT_TOKENS = (
    "tour", "expedicion", "expedición", "expedition", "trek", "trekking",
    "ascen", "subir", "climb", "summit", "viaje", "viagem", "paseo",
    "passeio", "passei", "passe", "salida", "departure", "saida", "saída",
    "aconcagua", "montaña", "montanha", "mountain", "alta montaña",
    "alta montanha", "fecha", "data", "date",
)


def mentions_out_of_season(text: str) -> bool:
    """Return True if the user message references an out-of-season month
    together with an expedition/trip intent. Conservative on purpose."""
    if not text:
        return False
    lowered = text.lower()
    normalized = unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode("ascii")

    has_intent = any(tok in normalized for tok in _TRIP_INTENT_TOKENS)
    if not has_intent:
        return False

    for tok in OUT_OF_SEASON_MONTH_TOKENS:
        if re.search(r"\b" + re.escape(tok) + r"\b", normalized):
            return True
    if _MAY_MONTH_RE.search(normalized):
        return True
    for match in _NUMERIC_DATE_RE.finditer(normalized):
        if _numeric_date_is_out_of_season(int(match.group(1)), int(match.group(2))):
            return True
    return False


def get_session_language(session_vars: dict[str, Any] | None, fallback_text: str = "") -> str:
    """Get conversation language from session variables. Default: Spanish.

    Reads conversation_language field set by session agent.
    Falls back to language detection from message text if not set.
    Falls back to 'es' if detection fails.

    If the latest user message has a *confident* language detection that
    differs from the stored session language, we rotate to follow the user
    (fixes language-drift bug where the bot stayed in the first-greeting
    language even after the user switched).
    """
    if not session_vars or not isinstance(session_vars, dict):
        if fallback_text:
            return detect_language_from_text(fallback_text)
        return "es"

    stored_lang = str(session_vars.get("conversation_language") or "").strip().lower()
    source = str(session_vars.get("conversation_language_source") or "").strip().lower()
    locked = bool(session_vars.get("conversation_language_locked"))

    # 0) Explicit user preference always wins and can switch the lock.
    if fallback_text and not fallback_text.strip().startswith("/"):
        explicit_pref = detect_explicit_language_preference(fallback_text)
        if explicit_pref and explicit_pref in I18N_PHRASES:
            return explicit_pref

    # If language was explicitly locked, preserve it unless user asks otherwise
    # (handled by branch 0 above).
    if locked and stored_lang in I18N_PHRASES:
        return stored_lang

    # 1) On /reset, prefer fresh detection from the next real message.
    if source == "reset" and fallback_text and not fallback_text.strip().startswith("/"):
        return detect_language_from_text(fallback_text)

    # 2) If the new user message has a confident language signal, follow it.
    if fallback_text and not fallback_text.strip().startswith("/"):
        confident = detect_language_confident(fallback_text)
        if confident and confident in I18N_PHRASES:
            return confident

    # 3) Otherwise keep the stored language.
    if stored_lang in I18N_PHRASES:
        return stored_lang

    # 4) Last resort: heuristic on text or 'es'.
    if fallback_text:
        return detect_language_from_text(fallback_text)
    return "es"


def get_phrase(key: str, language: str | None = None) -> str:
    """Get phrase by key and language with safe fallback.
    
    If language not provided or phrase not found, falls back to Spanish,
    then returns key itself as last resort.
    """
    lang = language or "es"
    if lang not in I18N_PHRASES:
        lang = "es"
    phrases = I18N_PHRASES[lang]
    return phrases.get(key, I18N_PHRASES["es"].get(key, f"[{key}]"))


def auth_error(message: str, code: int = 401) -> Any:
    return (
        jsonify(
            {
                "error": {
                    "message": message,
                    "type": "authentication_error",
                }
            }
        ),
        code,
    )


def is_authorized_for_chat() -> bool:
    expected = _env("ORCHESTRATOR_API_KEY")
    if not expected:
        raise RuntimeError(
            "ORCHESTRATOR_API_KEY environment variable is required in production. "
            "Set it or remove the auth_required decorator from endpoints."
        )

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        # Compatibility fallback for providers that send API keys as raw headers.
        # This keeps strict auth while supporting non-Bearer integrations.
        direct_token = (
            request.headers.get("api-key")
            or request.headers.get("x-api-key")
            or ""
        ).strip()
        if direct_token:
            return direct_token == expected

        # Some gateways place the key in query params or request body fields.
        query_token = (request.args.get("api_key") or request.args.get("key") or "").strip()
        if query_token:
            return query_token == expected

        body = request.get_json(silent=True) or {}
        body_token = (
            str(body.get("api_key") or body.get("apiKey") or body.get("key") or "").strip()
        )
        if body_token:
            return body_token == expected

        return False
    token = auth.removeprefix("Bearer ").strip()
    return token == expected


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def is_cloud_runtime() -> bool:
    return bool(
        _env("VERCEL")
        or _env("VERCEL_ENV")
        or _env("RENDER")
        or _env("RENDER_SERVICE_ID")
    )


def load_local_env() -> None:
    if not is_cloud_runtime():
        load_dotenv(ROOT / ".env")


def load_index(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(
            f"Missing {path}. Run scripts/build_cloud_index.py first."
        )
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON in {path}:{line_num}: {e}")
    return rows


def load_system_prompt() -> str:
    if not SYSTEM_PROMPT_PATH.exists():
        return (
            "Eres un asistente comercial de expediciones al Aconcagua. "
            "Responde con precision y no inventes datos."
        )
    prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    # Core facts go in the fixed system prompt (cacheable) so the model cannot
    # contradict them between runs; the permit was "included" in one run and
    # "not included" in the next (simulation 2026-10-08).
    if KEY_FACTS_PATH.exists():
        prompt = f"{prompt.rstrip()}\n\n--------------------------------------------------\n\n{KEY_FACTS_PATH.read_text(encoding='utf-8')}"
    return prompt


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def validate_and_normalize_headers(headers: Any, max_length: int = 1000) -> dict[str, str]:
    """Validate and normalize HTTP headers with size limits."""
    return _validate_and_normalize_headers(headers, max_length=max_length)


def http_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 15,
) -> tuple[int, dict[str, Any]]:
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")

    req = Request(url=url, data=data, headers=req_headers, method=method.upper())

    try:
        with urlopen(req, timeout=timeout) as resp:
            status = resp.getcode()
            raw = resp.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            return status, parsed
    except HTTPError as e:
        raw = e.read().decode("utf-8") if e.fp else ""
        try:
            parsed = json.loads(raw) if raw else {"error": raw}
        except json.JSONDecodeError:
            parsed = {"error": raw or str(e)}
        return e.code, parsed
    except URLError as e:
        return 0, {"error": str(e)}


def session_headers(msg: dict[str, str], agent_id: str) -> dict[str, str]:
    return _session_headers(msg, agent_id)


def session_get(session_base_url: str, conversation_id: str) -> dict[str, Any] | None:
    return _session_get(
        session_base_url,
        conversation_id,
        http_json=http_json,
        logger=app.logger,
    )


def session_delete(session_base_url: str, conversation_id: str) -> None:
    _session_delete(
        session_base_url,
        conversation_id,
        http_json=http_json,
        logger=app.logger,
    )


def session_append_event(
    session_base_url: str,
    conversation_id: str,
    event_type: str,
    event_data: dict[str, Any],
) -> None:
    _session_append_event(
        session_base_url,
        conversation_id,
        event_type,
        event_data,
        http_json=http_json,
        logger=app.logger,
    )


def session_upsert(
    session_base_url: str,
    msg: dict[str, str],
    agent_id: str,
    variables: dict[str, Any],
) -> None:
    _session_upsert(
        session_base_url,
        msg,
        agent_id,
        variables,
        http_json=http_json,
        logger=app.logger,
    )


def try_session_get(session_base_url: str | None, conversation_id: str) -> dict[str, Any] | None:
    return _try_session_get(
        session_base_url,
        conversation_id,
        http_json=http_json,
        logger=app.logger,
    )


def try_session_append_event(
    session_base_url: str | None,
    conversation_id: str,
    event_type: str,
    event_data: dict[str, Any],
) -> None:
    _try_session_append_event(
        session_base_url,
        conversation_id,
        event_type,
        event_data,
        http_json=http_json,
        logger=app.logger,
    )


def try_session_upsert(
    session_base_url: str | None,
    msg: dict[str, str],
    agent_id: str,
    variables: dict[str, Any],
) -> None:
    _try_session_upsert(
        session_base_url,
        msg,
        agent_id,
        variables,
        http_json=http_json,
        logger=app.logger,
    )


def try_session_delete(
    session_base_url: str | None,
    conversation_id: str,
) -> None:
    _try_session_delete(
        session_base_url,
        conversation_id,
        http_json=http_json,
        logger=app.logger,
    )


def build_reset_session_vars(now_ts: int) -> dict[str, Any]:
    """Build a canonical clean session state for /reset.

    Defaults conversation_language to Spanish.
    """
    return {
        "conversation_language": "es",
        "conversation_language_source": "reset",
        "conversation_language_locked": False,
        "conversation_turn_count": 0,
        "conversation_paused": False,
        "pause_reason": "",
        "paused_reply_count": 0,
        "paused_loop_frozen": False,
        "paused_loop_finalized_at_ts": None,
        "paused_loop_final_handoff_attempted": False,
        "paused_email": "",
        "paused_at_ts": now_ts,
        "last_user_message": "",
        "last_assistant_reply": "",
        "last_assistant_reply_ts": None,
        "recent_turns": [],
        "handoff_requested": False,
        "handoff_pending_confirmation": False,
        "proactive_email_capture_pending": False,
        "handoff_email_last_sent_ts": None,
        "handoff_email_last_to": "",
        "email_requested": False,
        "email_verified": False,
        "verified_email": "",
        "email_verified_real": False,
        "email_suspicious": False,
        "suspicious_email": "",
        "suspicious_email_alert_sent": False,
        "suspicious_email_alert_sent_ts": None,
        "suspicious_email_alert_last_status": None,
        "suspicious_email_alert_method": "",
        "suspicious_email_alert_last_response": {},
        "email_check_failed": False,
        "email_check_failed_at_ts": None,
        "crm_client_found": False,
        "crm_client_contacted": False,
        "crm_client_id": None,
        "crm_client_name": None,
        "crm_consultation_count": 0,
        "crm_last_consultation_date": None,
        "last_inbound_signature": "",
        "last_inbound_signature_ts": None,
    }


def reset_session_state(
    session_base_url: str | None,
    msg: dict[str, str],
    session_agent_id: str,
) -> None:
    """Reset state even if hard delete fails in remote session storage."""
    now_ts = int(time.time())
    try_session_delete(session_base_url, msg["conversation_id"])
    try_session_upsert(
        session_base_url,
        msg,
        session_agent_id,
        build_reset_session_vars(now_ts),
    )
    try_session_append_event(
        session_base_url,
        msg["conversation_id"],
        "session_reset",
        {"source": "command", "command": "/reset", "at_ts": now_ts},
    )


def get_language_source(session_vars: dict[str, Any] | None) -> str:
    if not session_vars or not isinstance(session_vars, dict):
        return "message content"
    source = str(session_vars.get("conversation_language_source") or "").strip().lower()
    if not source:
        return "message content"
    return source


def retrieve_top_k(
    client: OpenAI,
    embed_model: str,
    rows: list[dict[str, Any]],
    query_text: str,
    top_k: int,
) -> list[dict[str, Any]]:
    emb = client.embeddings.create(model=embed_model, input=query_text).data[0].embedding
    scored: list[dict[str, Any]] = []
    for row in rows:
        score = cosine(emb, row["embedding"])
        scored.append({"score": score, **row})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def build_contextual_query(query_text: str, recent_turns: Any, max_chars: int = 700) -> str:
    """Current message plus what was just talked about, for retrieval.

    "¿Y cuánto sale?" finds nothing alone; with the previous turns ("el 18+2
    es ideal para ustedes") it finds the 18+2 price.
    """
    turns = recent_turns if isinstance(recent_turns, list) else []
    previous = [
        str(t.get("text") or "")
        for t in turns[-3:]
        if isinstance(t, dict) and t.get("role") in ("user", "assistant")
    ]
    context = " ".join(p for p in previous if p).strip()
    if not context:
        return query_text
    return f"{query_text}\n{context[-max_chars:]}"


def retrieve_with_context(
    client: OpenAI,
    embed_model: str,
    rows: list[dict[str, Any]],
    query_text: str,
    recent_turns: Any,
    top_k: int,
) -> list[dict[str, Any]]:
    """Retrieve with the message alone and with recent context, keep the best of both.

    One embeddings call with two inputs. The plain query keeps a new topic from
    being pulled back to the old one; the contextual query resolves follow-ups.
    """
    contextual = build_contextual_query(query_text, recent_turns)
    if contextual == query_text:
        return retrieve_top_k(client, embed_model, rows, query_text, top_k)
    data = client.embeddings.create(model=embed_model, input=[query_text, contextual]).data
    best: dict[Any, dict[str, Any]] = {}
    for item in data:
        for row in rows:
            score = cosine(item.embedding, row["embedding"])
            key = row.get("id", id(row))
            if key not in best or score > best[key]["score"]:
                best[key] = {"score": score, **row}
    return sorted(best.values(), key=lambda x: x["score"], reverse=True)[:top_k]


def hits_to_context(hits: list[dict[str, Any]]) -> str:
    parts = []
    for h in hits:
        parts.append(
            "\n".join(
                [
                    f"ID: {h['id']}",
                    f"TOPIC: {h.get('topic', 'general')}",
                    f"QUESTION: {h['question']}",
                    f"ANSWER: {h['answer']}",
                    f"SIMILARITY: {h['score']:.4f}",
                ]
            )
        )
    return "\n\n---\n\n".join(parts)


def build_crm_client_context(session_vars: dict[str, Any]) -> str:
    crm_client_context = ""
    if session_vars.get("crm_client_found"):
        client_name = session_vars.get("crm_client_name", "Cliente")
        consultation_count = session_vars.get("crm_consultation_count", 0)
        if session_vars.get("crm_client_contacted"):
            crm_client_context = (
                f"\n⭐ CLIENTE REGISTRADO: {client_name} ya fue contactado anteriormente "
                f"({consultation_count} consulta(s) previa(s)). "
                "Ofrece trato VIP/preferencial: sé más personal, recuerda detalles de sus consultas anteriores si es relevante, "
                "y prioriza su comodidad."
            )
        else:
            crm_client_context = (
                f"\n👤 CLIENTE NUEVO: {client_name} es un cliente registrado pero sin consultas previas. "
                "Es su primer contacto: responde en dos bloques breves separados por una línea en blanco. "
                "El primer bloque debe ser un saludo y bienvenida. "
                "El segundo bloque debe explicar de forma clara los servicios disponibles."
            )
    else:
        crm_client_context = "\n👥 PROSPECTO DESCONOCIDO: Este cliente no está registrado en nuestro sistema."

    return crm_client_context


# The only session variables the model gets. The rest (timestamps, alert
# status, pause bookkeeping) cost ~400 tokens per reply and add nothing; the
# transcript goes as chat history and the CRM data has its own block.
_SESSION_KEYS_FOR_LLM = (
    "conversation_turn_count",
    "email_requested",
    "email_captured",
    "out_of_season_warned",
)


# How many past messages the model sees (env NICO_HISTORY_TURNS; 0 disables).
DEFAULT_HISTORY_TURNS = 10


def log_llm_usage(conversation_id: str, model: str, usage: Any) -> dict[str, Any]:
    """Print one [LLM_USAGE] line per model call so spend can be tracked in the logs."""
    if usage is None:
        return {}
    details = getattr(usage, "input_tokens_details", None)
    record = {
        "conversation_id": conversation_id,
        "model": model,
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "cached_input_tokens": int(getattr(details, "cached_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }
    print("[LLM_USAGE] " + json.dumps(record), flush=True)
    return record


# Argentina has no DST: Mendoza is UTC-3 all year.
ARGENTINA_TZ = timezone(timedelta(hours=-3), "ART")


def today_in_argentina(now: datetime | None = None) -> date:
    return (now or datetime.now(timezone.utc)).astimezone(ARGENTINA_TZ).date()


def generate_reply(
    client: OpenAI,
    chat_model: str,
    system_prompt: str,
    msg: dict[str, str],
    hits: list[dict[str, Any]],
    session_vars: dict[str, Any],
    today: date | None = None,
    history_turns: int = DEFAULT_HISTORY_TURNS,
) -> str:
    today = today or today_in_argentina()
    # Past departures are removed here: the small model dropped future ones when asked to.
    context = hits_to_context(
        [{**h, "answer": filter_past_departures(str(h.get("answer") or ""), today)} for h in hits]
    )
    user_lang = get_session_language(session_vars, msg["text"])

    lang_instruction = {
        "es": "Responde en español.",
        "en": "Respond in English.",
        "pt": "Responda em português.",
    }.get(user_lang, "Respond in the user's language.")

    crm_client_context = build_crm_client_context(session_vars)

    # Override conversation_language in the dumped state so the LLM does not
    # see a stale/contradictory signal vs the explicit lang_instruction.
    session_vars_for_llm = {key: session_vars[key] for key in _SESSION_KEYS_FOR_LLM if key in session_vars}
    session_vars_for_llm["conversation_language"] = user_lang
    recent_turns = session_vars.get("recent_turns")

    is_whatsapp = str(msg.get("channel", "")).strip().lower() == "whatsapp"
    response_length_instruction = (
        "Mantén la respuesta muy corta: máximo 2 líneas y 280 caracteres."
        if is_whatsapp
        else "Mantén la respuesta corta: máximo 3 líneas y 450 caracteres."
    )

    user_prompt = (
        "Fecha de hoy (Argentina): {today}\n"
        "Canal: {channel}\n"
        "Conversation ID: {conversation_id}\n"
        "Cliente pregunta:\n{question}\n\n"
        "Variables de sesion actuales:\n{session_vars}\n\n"
        "{crm_context}"
        "\n\nEvidencia interna recuperada:\n{context}\n\n"
        "Instrucciones CRÍTICAS:\n"
        "- {lang_instruction}\n"
        "- Basa tu respuesta ÚNICAMENTE en la evidencia recuperada y en lo que ya le dijiste al cliente en esta conversación "
        "(si ya le diste un precio o una fecha, podés repetirlo).\n"
        "- Si la evidencia trae información relacionada, aunque sea parcial, respondé con eso. "
        "Decir que no lo tenés es el último recurso.\n"
        "- Puedes traducir la respuesta del FAQ al idioma del usuario si es necesario.\n"
        "- Pero NO INVENTES, NO AGREGUES ni NO EMBELLEZCAS información más allá de lo que dice el FAQ.\n"
        "- La estructura y contenido de la respuesta debe ser fiel al FAQ, solo adaptado en idioma y claridad.\n"
        "- {response_length_instruction}\n"
        "- Si compartes fechas de salida y el canal es WhatsApp, usa lista numerada: una línea por programa con meses abreviados y días agrupados.\n"
        "- Las fechas de salida de la evidencia ya están actualizadas a hoy: compartilas todas, no saques ninguna.\n"
        "- Arriba tenés los mensajes anteriores de esta conversación. Si ya hablaron, no vuelvas a saludar, "
        "no repitas lo que ya dijiste y no preguntes datos que el cliente ya te dio.\n"
        "- NO hagas preguntas de cierre ni acciones siguientes que no vengan del FAQ.\n"
        "- Si de verdad no hay nada relacionado, decilo con tus palabras y ofrecé que un asesor del equipo lo confirme. "
        "Si ya lo dijiste antes en esta conversación, no lo repitas: respondé lo que sí sabés o preguntá qué necesita exactamente.\n"
        "- No pidas el email si ya lo pediste en esta conversación.\n"
        "- Nunca menciones FAQ, documentación, evidencia ni base de datos."
    ).format(
        today=today.isoformat(),
        channel=msg["channel"],
        conversation_id=msg["conversation_id"],
        question=msg["text"],
        session_vars=json.dumps(session_vars_for_llm, ensure_ascii=False),
        crm_context=crm_client_context,
        context=context,
        lang_instruction=lang_instruction,
        response_length_instruction=response_length_instruction,
    )

    resp = client.responses.create(
        model=chat_model,
        max_output_tokens=220,
        input=[
            {"role": "system", "content": system_prompt},
            *(history_to_messages(recent_turns)[-history_turns:] if history_turns > 0 else []),
            {"role": "user", "content": user_prompt},
        ],
    )
    log_llm_usage(msg.get("conversation_id", ""), chat_model, getattr(resp, "usage", None))
    reply = (resp.output_text or "").strip()
    if getattr(resp, "status", None) == "incomplete":
        reply = trim_to_last_sentence(reply)
    return humanize_reply(
        reply,
        channel="whatsapp" if is_whatsapp else "other",
        already_spoke=assistant_already_spoke(recent_turns),
    )


def supports_respond_tool(tools_payload: Any) -> bool:
    """Return True when upstream Chat Completions tools include `respond`."""
    if not isinstance(tools_payload, list):
        return False
    for tool in tools_payload:
        if not isinstance(tool, dict):
            continue
        function_obj = tool.get("function")
        if isinstance(function_obj, dict) and function_obj.get("name") == "respond":
            return True
    return False


def split_reply_into_messages(reply_text: str) -> list[str]:
    """Split a single assistant reply into short message chunks.

    Preferred separator is blank lines. If none are present, return a single
    chunk to avoid brittle sentence-level splitting.
    """
    if not reply_text:
        return []
    parts = [p.strip() for p in re.split(r"\n\s*\n+", reply_text) if p.strip()]
    return parts


MAX_REPLY_BUBBLES = 3


def choose_reply_bubbles(reply: str, can_emit_multi: bool, is_opening: bool) -> list[str]:
    """Split a reply into WhatsApp bubbles the way a person types.

    People send "Gracias!" and the answer as two messages. Paragraphs become
    bubbles when there are 2-3 of them; a longer list stays in one message.
    """
    if not can_emit_multi or not (reply or "").strip():
        return []
    parts = split_reply_into_messages(reply)
    if is_opening or 2 <= len(parts) <= MAX_REPLY_BUBBLES:
        return parts
    return []


def build_respond_tool_call_message(reply_parts: list[str]) -> dict[str, Any]:
    """Build assistant tool call payload for OpenBSP multi-message responses."""
    args = {
        "messages": [{"type": "text", "text": part} for part in reply_parts],
    }
    return {
        "role": "assistant",
        "tool_calls": [
            {
                "id": f"call_{uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": "respond",
                    "arguments": json.dumps(args, ensure_ascii=False),
                },
            }
        ],
    }


def is_multi_message_enabled() -> bool:
    raw = str(_env("OPENBSP_MULTI_MESSAGE_ENABLED", "false") or "false").strip().lower()
    return raw in ("1", "true", "yes", "on")


_MONTH_ABBR: dict[str, str] = {
    "enero": "Ene", "febrero": "Feb", "marzo": "Mar", "abril": "Abr",
    "mayo": "May", "junio": "Jun", "julio": "Jul", "agosto": "Ago",
    "septiembre": "Sep", "setiembre": "Sep", "octubre": "Oct",
    "noviembre": "Nov", "diciembre": "Dic",
    "january": "Jan", "february": "Feb", "march": "Mar", "april": "Apr",
    "may": "May", "june": "Jun", "july": "Jul", "august": "Aug",
    "september": "Sep", "october": "Oct", "november": "Nov", "december": "Dec",
}

_TITLE_PATTERN = re.compile(
    r"^([ \t]*)(\d+\s*\+\s*\d+)\s+(?:D[ÍI]AS|d[íi]as)\s*\|\s*(.+?)\s*$",
    flags=re.MULTILINE,
)


def _format_program_title(match: "re.Match[str]") -> str:
    indent = match.group(1)
    days = re.sub(r"\s+", "", match.group(2))
    rest = match.group(3).strip()
    paren = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", rest)
    if paren:
        name = paren.group(1).strip().title()
        note = paren.group(2).strip().lower()
        return f"{indent}*{days} días - {name}* _({note})_"
    return f"{indent}*{days} días - {rest.title()}*"


def _format_inline_program_list(text: str) -> str:
    """Convert semicolon-separated inline program dates into a numbered list."""
    if ";" not in text or not re.search(r"\(\s*\d+\s*\+\s*\d+\s*d[íi]as\s*\)", text, re.IGNORECASE):
        return text

    prefix = ""
    body = text
    if ":" in text:
        maybe_prefix, maybe_body = text.split(":", 1)
        if re.search(r"\(\s*\d+\s*\+\s*\d+\s*d[íi]as\s*\)", maybe_body, re.IGNORECASE):
            prefix = maybe_prefix.strip()
            body = maybe_body.strip()

    entry_re = re.compile(
        r"^\s*(?P<name>[^()]+?)\s*\(\s*(?P<days>\d+\s*\+\s*\d+)\s*d[íi]as\s*\)\s*(?P<schedule>.+?)\s*$",
        re.IGNORECASE,
    )
    month_keys = "|".join(sorted(_MONTH_ABBR.keys(), key=len, reverse=True))
    abbr_keys = "|".join(sorted(set(_MONTH_ABBR.values()), key=len, reverse=True))
    month_day_re = re.compile(
        rf"\b(?P<month>{month_keys}|{abbr_keys})\.?\s*(?P<days>\d{{1,2}}(?:\s*,\s*\d{{1,2}})*)",
        re.IGNORECASE,
    )

    lines: list[str] = []
    for raw_entry in [p.strip() for p in body.split(";") if p.strip()]:
        entry = raw_entry.rstrip(".")
        m = entry_re.match(entry)
        if not m:
            return text

        name = m.group("name").strip().title()
        days = re.sub(r"\s+", "", m.group("days"))
        schedule = m.group("schedule").strip()
        month_chunks: list[str] = []
        for mm in month_day_re.finditer(schedule):
            month_raw = mm.group("month").lower()
            abbr = _MONTH_ABBR.get(month_raw, mm.group("month").title())
            day_list = [d.strip() for d in mm.group("days").split(",") if d.strip()]
            month_chunks.append(f"{abbr} {', '.join(day_list)}")
        schedule_fmt = " · ".join(month_chunks) if month_chunks else schedule
        lines.append(f"{len(lines) + 1}. *{name}* ({days} días): {schedule_fmt}")

    if not lines:
        return text
    return f"{prefix}:\n" + "\n".join(lines) if prefix else "\n".join(lines)


def format_whatsapp_departure_dates(reply_text: str, channel: str) -> str:
    """Render departure-date blocks compactly for WhatsApp readability."""
    if not reply_text or channel.strip().lower() != "whatsapp":
        return reply_text

    text = reply_text
    lower_text = text.lower()
    has_dates_marker = any(
        token in lower_text
        for token in (
            "fechas",
            "salidas",
            "departure",
            "departures",
        )
    )
    has_structured_dates = "|" in text or re.search(
        r"\(\s*\d+\s*\+\s*\d+\s*d[íi]as\s*\).+;",
        text,
        re.IGNORECASE,
    )
    looks_like_dates_response = bool(has_dates_marker and has_structured_dates)
    if not looks_like_dates_response:
        return reply_text

    month_pattern = re.compile(
        r"\b("
        r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre|"
        r"january|february|march|april|may|june|july|august|september|october|november|december"
        r")\s*:\s*([0-9]{1,2}(?:\s*(?:\||,)\s*[0-9]{1,2})+)",
        flags=re.IGNORECASE,
    )

    def _compact_month(match: "re.Match[str]") -> str:
        month_label = match.group(1)
        days = [d.strip() for d in re.split(r"\||,", match.group(2)) if d.strip()]
        if len(days) < 2:
            return match.group(0)
        abbr = _MONTH_ABBR.get(month_label.lower(), month_label)
        return f"{abbr} {', '.join(days)}"

    formatted = month_pattern.sub(_compact_month, text)

    # Collapse consecutive month lines into one compact line per program.
    abbr_set = set(_MONTH_ABBR.values())
    month_keys = "|".join(sorted(_MONTH_ABBR.keys(), key=len, reverse=True))
    abbr_keys = "|".join(sorted(abbr_set, key=len, reverse=True))
    month_line_re = re.compile(
        rf"^[ \t]*[-*]?[ \t]*(?P<month>{month_keys}|{abbr_keys})[ \t]*:?[ \t]+"
        rf"(?P<days>\d{{1,2}}(?:[ \t]*[,|][ \t]*\d{{1,2}})*)\s*$",
        re.IGNORECASE,
    )

    out_lines: list[str] = []
    buffer: list[str] = []
    for line in formatted.split("\n"):
        if re.fullmatch(r"[ \t]*[-*][ \t]*", line):
            continue
        m = month_line_re.match(line)
        if m:
            month_raw = m.group("month").lower()
            abbr = _MONTH_ABBR.get(month_raw, m.group("month").capitalize())
            days = [d.strip() for d in re.split(r"[,|]", m.group("days")) if d.strip()]
            buffer.append(f"{abbr} {', '.join(days)}")
            continue
        if buffer:
            out_lines.append(" · ".join(buffer))
            buffer = []
        out_lines.append(line)
    if buffer:
        out_lines.append(" · ".join(buffer))

    formatted = "\n".join(out_lines)
    formatted = _TITLE_PATTERN.sub(_format_program_title, formatted)
    formatted = _format_inline_program_list(formatted)
    formatted = re.sub(r"[ \t]+\n", "\n", formatted)
    formatted = re.sub(r"\n{3,}", "\n\n", formatted)
    return formatted.strip()


def normalize_for_intent(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


_PURE_GREETING_TOKENS: frozenset[str] = frozenset({
    "hola", "hi", "hello", "hey", "oi", "ola",
    "buenas", "buen", "dia", "buenos", "dias",
    "good", "morning", "afternoon", "evening",
    "bom", "boa", "tarde", "noite",
})


def _is_pure_greeting(text: str) -> bool:
    """Return True when the message is only a greeting with no substantive question."""
    normalized = normalize_for_intent(text)
    # Strip punctuation for token matching
    cleaned = re.sub(r"[^\w\s]", " ", normalized).strip()
    if len(cleaned) > 50:
        return False
    tokens = set(cleaned.split())
    # Must have at least one known greeting token and no non-greeting words
    return bool(tokens & _PURE_GREETING_TOKENS) and tokens <= _PURE_GREETING_TOKENS


_THANKS_TOKENS: frozenset[str] = frozenset({"gracias", "thanks", "thank", "thx", "ty", "obrigado", "obrigada", "valeu"})
_THANKS_FILLER_TOKENS: frozenset[str] = frozenset({
    "muchas", "muchisimas", "mil", "por", "todo", "la", "info", "informacion", "genial", "perfecto",
    "dale", "ok", "buenisimo", "barbaro", "joya", "you", "so", "much", "very", "a", "lot", "for", "the",
    "great", "info", "muito", "pela", "informacao", "otimo", "perfeito", "show", "de", "nuevo", "again",
})


def is_thanks_only(text: str) -> bool:
    """A bare "gracias" / "thanks!": nothing to look up, just acknowledge.

    Retrieval on "Thanks!" returned unrelated FAQ entries and the model
    answered about gear rental (simulation 2026-10-08).
    """
    cleaned = re.sub(r"[^\w\s]", " ", normalize_for_intent(text)).split()
    if not cleaned or len(cleaned) > 8:
        return False
    tokens = set(cleaned)
    return bool(tokens & _THANKS_TOKENS) and tokens <= (_THANKS_TOKENS | _THANKS_FILLER_TOKENS)


_INTEREST_RE = re.compile(
    r"\b(?:interesad[oa]s?|interested|interessad[oa]s?|quiero info|quisiera info|me gustaria (?:saber|tener|recibir)"
    r"|(?:mas )?informacion|info\b|would like (?:some |more )?info|i want (?:some |more )?info|gostaria de (?:saber|receber)"
    r"|informac(?:ao|oes))"
)


def is_generic_opening(text: str) -> bool:
    """First message that only shows interest ("Hi, I'm interested in climbing Aconcagua").

    Answering it with a random FAQ entry (the guides) read like a bot; a
    person greets and asks what they want to know.
    """
    normalized = normalize_for_intent(text)
    if "?" in normalized or re.search(r"\d", normalized) or len(normalized.split()) > 14:
        return False
    return bool(_INTEREST_RE.search(normalized))


OUTBOUND_DUPLICATE_WINDOW_SECONDS = 180
# Same reply this soon after the last one means a burst of client messages
# answered in parallel: drop it. Later, the client asked again and must get
# an answer.
OUTBOUND_DUPLICATE_BURST_SECONDS = 30


def is_recent_duplicate_reply(reply: str, session_vars: dict[str, Any] | None, now_ts: int) -> bool:
    """Return True when `reply` repeats the last stored assistant reply recently."""
    if not reply.strip() or not session_vars:
        return False
    last_reply = str(session_vars.get("last_assistant_reply") or "").strip()
    try:
        last_ts = int(session_vars.get("last_assistant_reply_ts") or 0)
    except (TypeError, ValueError):
        last_ts = 0
    return bool(
        last_reply
        and last_ts
        and (now_ts - last_ts) <= OUTBOUND_DUPLICATE_WINDOW_SECONDS
        and normalize_for_intent(reply) == normalize_for_intent(last_reply)
    )


def resolve_duplicate_reply(reply: str, session_vars: dict[str, Any], now_ts: int, lang: str) -> str:
    """What to send when the reply repeats the previous one.

    Within a burst, nothing (the client already has it). Otherwise the client
    asked again: say it again the way a person does instead of going silent.
    """
    try:
        last_ts = int(session_vars.get("last_assistant_reply_ts") or 0)
    except (TypeError, ValueError):
        last_ts = 0
    if now_ts - last_ts <= OUTBOUND_DUPLICATE_BURST_SECONDS:
        return ""
    text = reply.strip()
    return f"{get_phrase('repeat_prefix', lang)} {text[:1].lower()}{text[1:]}"


def build_inbound_signature(msg: dict[str, str]) -> str:
    """Build a deterministic signature for inbound de-duplication."""
    normalized_text = normalize_for_intent(msg.get("text", ""))
    return "|".join(
        [
            msg.get("conversation_id", ""),
            msg.get("contact_id", ""),
            msg.get("contact_address", ""),
            msg.get("channel", ""),
            normalized_text,
        ]
    )


def is_duplicate_inbound(
    session_vars: dict[str, Any],
    inbound_signature: str,
    now_ts: int,
    window_seconds: int = 120,
) -> bool:
    """Return True when the inbound payload appears to be a recent retry."""
    last_sig = str(session_vars.get("last_inbound_signature") or "")
    raw_last_ts = session_vars.get("last_inbound_signature_ts")
    try:
        last_ts = int(raw_last_ts) if raw_last_ts is not None else 0
    except (TypeError, ValueError):
        last_ts = 0

    if not last_sig or not last_ts:
        return False
    if (now_ts - last_ts) > window_seconds:
        return False
    return inbound_signature == last_sig


def extract_command(text: str) -> str | None:
    """Extract slash command token from user text.

    Accepts commands like:
    - /reset
    - /RESET
    - /reset hola
    """
    stripped = (text or "").strip()
    if not stripped.startswith("/"):
        return None
    parts = stripped.split()
    if not parts:
        return None
    return parts[0].lower()


_HANDOFF_VERB = (
    r"(?:hablar|hablarlo|charlar|comunicarme|contactar(?:me)?|pas(?:a|as|ás|ame|arme)|comunicame"
    r"|falar|conversar|speak|talk|chat|connect me|put me through)"
)
_HANDOFF_TARGET = (
    r"(?:asesor(?:a|es)?|persona|humano|alguien|agente|vendedor(?:a)?|representante|operador(?:a)?"
    r"|atendente|consultor(?:a)?|pessoa|alguem"
    r"|human|person|someone|somebody|agent|representative|advisor|adviser|sales ?rep|real person)"
)
# "<verb> con/com/to/with [un/una/a/...] <human target>". The target is
# required: "quiero hablar con mi esposa" is not a handoff request.
_HANDOFF_REQUEST_RE = re.compile(
    rf"\b{_HANDOFF_VERB}\s+(?:con|com|to|with|a)?\s*"
    r"(?:(?:un|una|um|uma|a|an|the|el|la|o|algun|alguna|algum|alguma)\s+)?"
    r"(?:real\s+|de\s+verdad\s+)?"
    rf"{_HANDOFF_TARGET}\b"
)


_BOT_QUESTION_RE = re.compile(
    r"\b(?:sos|eres|es|sera|será|are you|is this|r u|voce e|você é|vc e|vc é)\s+(?:un|una|a|an|um|uma)?\s*"
    r"(?:bot|robot|robo|robô|ia|ai|inteligencia artificial|inteligência artificial|chatbot|maquina|máquina|machine)\b"
    r"|\b(?:sos|eres|are you|voce e|você é)\s+(?:una?\s+)?(?:persona|humano|human|real person|pessoa)\b"
    r"|\b(?:hablo|estoy hablando|am i talking|am i chatting|estou falando)\s+(?:con|with|com|to)\s+(?:un|una|a|an|um|uma)\s+"
    r"(?:real\s+|de\s+verdad\s+)?(?:bot|robot|robo|robô|ia|ai|maquina|máquina|machine|persona|humano|human|person|pessoa)\b",
    re.IGNORECASE,
)


def asks_if_bot(text: str) -> bool:
    """True when the client asks whether they are talking to a bot or a person."""
    return bool(_BOT_QUESTION_RE.search(normalize_for_intent(text)))


def wants_human_handoff(text: str, session_vars: dict[str, Any] | None = None) -> bool:
    """Return True only when the user *explicitly* requests a human agent.

    Affirmative detection ("si", "ok", etc.) was deliberately removed because
    the LLM often mentions "asesor" in normal replies, which caused every
    short affirmative to be misdetected as a handoff request. Generic phrases
    like "quiero hablar con" also need a human target: users often say they
    want to talk it over with their partner before booking.
    """
    normalized = normalize_for_intent(text)
    triggers = (
        "quiero un asesor",
        "quiero un humano",
        "necesito un asesor",
        "agente humano",
        "representante humano",
        "operador humano",
        "human agent",
        "speak to human",
        "quero um atendente",
        "quero um consultor",
    )
    if any(trigger in normalized for trigger in triggers):
        return True
    return bool(_HANDOFF_REQUEST_RE.search(normalized))


def _contains_known_program_duration(normalized_text: str) -> bool:
    return bool(
        re.search(
            r"\b(18\s*\+\s*2|17\s*\+\s*2|14\s*\+\s*2|12\s*\+\s*2)\b",
            normalized_text,
        )
    )


def _is_program_options_first_intent(normalized_text: str) -> bool:
    generic_keywords = (
        "opciones",
        "alternativas",
        "programas",
        "itinerarios",
        "expediciones",
        "que opciones",
        "cuales son",
        "what options",
        "which options",
        "alternatives",
        "programs",
        "itineraries",
        "expeditions",
    )
    has_generic_keyword = any(k in normalized_text for k in generic_keywords)
    return has_generic_keyword and not _contains_known_program_duration(normalized_text)


def _is_program_options_followup_intent(normalized_text: str) -> bool:
    followup_keywords = (
        "otras",
        "otras opciones",
        "otras alternativas",
        "las otras",
        "restantes",
        "demas",
        "todas",
        "lista",
        "listame",
        "all options",
        "other options",
        "other alternatives",
        "the other",
        "list the others",
    )
    return any(k in normalized_text for k in followup_keywords)


def _first_program_options_reply(lang: str) -> str:
    if lang == "en":
        return (
            "I recommend starting with two options:\n"
            "1. 18+2 (highly recommended)\n"
            "2. 12+2 (recommended)\n\n"
            "There are other alternatives as well. If you'd like, I can list them in detail."
        )
    return (
        "Para empezar, te recomiendo estas dos opciones:\n"
        "1. 18+2 (muy recomendada)\n"
        "2. 12+2 (recomendada)\n\n"
        "También hay otras alternativas. Si querés, te las paso en detalle."
    )


def _followup_program_options_reply(lang: str) -> str:
    if lang == "en":
        return (
            "The other alternatives are:\n"
            "1. 14+2\n"
            "2. 17+2"
        )
    return (
        "Las otras alternativas son:\n"
        "1. 14+2\n"
        "2. 17+2"
    )


def build_program_options_guidance_reply(
    user_text: str,
    session_vars: dict[str, Any],
    lang: str,
) -> str | None:
    normalized = normalize_for_intent(user_text)
    options_stage = int(session_vars.get("program_options_stage") or 0)

    if options_stage <= 0 and _is_program_options_first_intent(normalized):
        session_vars["program_options_stage"] = 1
        return _first_program_options_reply(lang)

    if options_stage >= 1 and _is_program_options_followup_intent(normalized):
        session_vars["program_options_stage"] = 2
        return _followup_program_options_reply(lang)

    return None


def should_send_handoff_email(
    session_vars: dict[str, Any],
    cooldown_seconds: int,
    now_ts: int,
) -> bool:
    raw_last = session_vars.get("handoff_email_last_sent_ts")
    if raw_last is None:
        return True
    try:
        last_ts = int(raw_last)
    except (TypeError, ValueError):
        return True
    return (now_ts - last_ts) >= cooldown_seconds


def extract_last_user_text(messages: Any) -> str:
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    parts.append(part["text"])
            joined = "\n".join(parts).strip()
            if joined:
                return joined
    return ""


def parse_csv_set(value: str | None) -> set[str]:
    if not value:
        return set()
    items = [part.strip() for part in value.split(",")]
    return {item for item in items if item}


def resolve_effective_chat_model(requested_model: str | None, runtime: dict[str, Any]) -> tuple[str, str]:
    """Resolve effective chat model and source label.

    Source labels:
    - runtime_default
    - request
    - request_rejected_not_allowlisted
    """
    configured_model = str(runtime.get("chat_model") or "").strip()
    requested = str(requested_model or "").strip()
    allow_from_request = bool(runtime.get("chat_model_from_request", False))
    allowlist = runtime.get("allowed_chat_models")
    allowset = allowlist if isinstance(allowlist, set) else set()

    if allow_from_request and requested:
        if allowset and requested not in allowset:
            return configured_model, "request_rejected_not_allowlisted"
        return requested, "request"
    return configured_model, "runtime_default"


def ensure_runtime() -> dict[str, Any]:
    load_local_env()

    api_key = _env("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing OPENAI_API_KEY")

    rows = app.config.get("INDEX_ROWS")
    if rows is None:
        rows = load_index(INDEX_PATH)
        app.config["INDEX_ROWS"] = rows

    system_prompt = app.config.get("SYSTEM_PROMPT")
    if system_prompt is None:
        system_prompt = load_system_prompt()
        app.config["SYSTEM_PROMPT"] = system_prompt

    return {
        "api_key": api_key,
        "embed_model": _env("OPENAI_EMBED_MODEL", "text-embedding-3-large"),
        "chat_model": _env("OPENAI_CHAT_MODEL", "gpt-5.4"),
        "chat_model_from_request": str(_env("OPENAI_CHAT_MODEL_FROM_REQUEST", "false") or "false")
        .strip()
        .lower()
        in ("1", "true", "yes", "on"),
        "allowed_chat_models": parse_csv_set(_env("OPENAI_ALLOWED_CHAT_MODELS", "") or ""),
        "top_k": int(_env("TOP_K", "4") or "4"),
        "history_turns": int(_env("NICO_HISTORY_TURNS", str(DEFAULT_HISTORY_TURNS)) or DEFAULT_HISTORY_TURNS),
        "session_base_url": _env("SESSION_AGENT_BASE_URL"),
        "session_agent_id": _env("SESSION_AGENT_ID", "sales-agent-v1")
        or "sales-agent-v1",
        "handoff_email_provider": _env("HANDOFF_EMAIL_PROVIDER", "resend") or "resend",
        "handoff_email_api_key": _env("HANDOFF_EMAIL_API_KEY"),
        "handoff_email_from": _env("HANDOFF_EMAIL_FROM"),
        "handoff_email_to": _env("HANDOFF_EMAIL_TO"),
        "handoff_smtp_host": _env("HANDOFF_SMTP_HOST"),
        "handoff_smtp_port": int(_env("HANDOFF_SMTP_PORT", "587") or "587"),
        "handoff_smtp_user": _env("HANDOFF_SMTP_USER"),
        "handoff_smtp_password": _env("HANDOFF_SMTP_PASSWORD"),
        "handoff_smtp_starttls": str(_env("HANDOFF_SMTP_STARTTLS", "true") or "true")
        .strip()
        .lower()
        in ("1", "true", "yes", "on"),
        "handoff_email_cooldown_seconds": int(
            _env("HANDOFF_EMAIL_COOLDOWN_SECONDS", "1800") or "1800"
        ),
        "paused_reply_threshold": int(_env("PAUSED_REPLY_THRESHOLD", "1") or "1"),
        # Nico stays silent while an advisor is handling the conversation (0 disables).
        "human_silence_hours": float(_env("HUMAN_SILENCE_HOURS", "12") or "12"),
        "nico_agent_id": _env("NICO_AGENT_ID", DEFAULT_NICO_AGENT_ID) or DEFAULT_NICO_AGENT_ID,
        "supabase_url": _env("SUPABASE_URL"),
        "supabase_key": _env("SUPABASE_SECRET_KEY"),
        "email_verification_enabled": str(_env("EMAIL_VERIFICATION_ENABLED", "true") or "true")
        .strip()
        .lower()
        in ("1", "true", "yes", "on"),
        "hibp_api_key": _env("HIBP_API_KEY"),
        "hibp_timeout_seconds": int(_env("HIBP_TIMEOUT_SECONDS", "10") or "10"),
        "rows": rows,
        "system_prompt": system_prompt,
    }


def build_version_payload() -> dict[str, Any]:
    return _build_version_payload(
        env=_env,
        is_cloud_runtime=is_cloud_runtime,
        python_version=sys.version.split(" ")[0],
    )


def build_version_text() -> str:
    return _build_version_text(build_version_payload())


def build_paused_reply(session_vars: dict[str, Any]) -> str:
    """Build paused-conversation reply in conversation language."""
    lang = get_session_language(session_vars)
    reason = str(session_vars.get("pause_reason") or "").strip().lower()
    if reason == "human_handoff_in_progress":
        return get_phrase("paused_handoff", lang)
    if reason == "proactive_email_request":
        return get_phrase("paused_proactive_email", lang)
    return get_phrase("paused_suspicious", lang)


def contains_sensitive_outbound_content(text: str) -> bool:
    """Return True when outbound text appears to contain credentials/secrets."""
    if not text:
        return False
    patterns = (
        r"\bpass(?:word)?\s*[:=]\s*\S+",
        r"\bapi[_-]?key\s*[:=]\s*\S+",
        r"\btoken\s*[:=]\s*\S+",
        r"\b(email|usuario|user)\s*[:=]\s*\S+@\S+\s+.*\bpass(?:word)?\b",
        r"\blogin\b.{0,80}\bpass(?:word)?\b",
    )
    lowered = text.lower()
    return any(re.search(pattern, lowered, re.IGNORECASE) for pattern in patterns)


def build_sensitive_outbound_block_reply(lang: str) -> str:
    if lang == "en":
        return "I can't share credentials or access data through this channel. A human advisor will continue with secure onboarding steps."
    if lang == "pt":
        return "Nao posso compartilhar credenciais ou dados de acesso por este canal. Um consultor humano continuara com os passos seguros."
    return "No puedo compartir credenciales ni datos de acceso por este canal. Un asesor humano continuara con los pasos seguros."


def apply_paused_anti_loop_guard(
    session_vars: dict[str, Any],
    msg: dict[str, str],
    runtime: dict[str, Any],
    now_ts: int,
) -> tuple[str, bool, int, dict[str, Any], bool]:
    """Limit repetitive paused replies and finalize automated thread replies."""
    raw_threshold = runtime.get("paused_reply_threshold", 1)
    try:
        threshold = max(1, int(raw_threshold))
    except (TypeError, ValueError):
        threshold = 1

    try:
        paused_reply_count = int(session_vars.get("paused_reply_count") or 0)
    except (TypeError, ValueError):
        paused_reply_count = 0

    paused_reply_count += 1
    session_vars["paused_reply_count"] = paused_reply_count

    if paused_reply_count <= threshold:
        return build_paused_reply(session_vars), False, 0, {}, False

    # Emit the final paused-loop message only once; suppress subsequent repeats.
    if session_vars.get("paused_loop_finalized_at_ts"):
        return "", False, 0, {"info": "paused loop already finalized"}, False

    lang = get_session_language(session_vars, msg.get("text", ""))
    session_vars["paused_loop_frozen"] = True
    if not session_vars.get("paused_loop_finalized_at_ts"):
        session_vars["paused_loop_finalized_at_ts"] = now_ts

    handoff_attempted = False
    handoff_status = 0
    handoff_data: dict[str, Any] = {"info": "paused loop frozen"}
    handoff_sent = False

    reason = str(session_vars.get("pause_reason") or "").strip().lower()
    if reason == "human_handoff_in_progress" and not session_vars.get("paused_loop_final_handoff_attempted"):
        cooldown_ok = should_send_handoff_email(
            session_vars,
            runtime["handoff_email_cooldown_seconds"],
            now_ts,
        )
        if cooldown_ok:
            handoff_attempted, handoff_status, handoff_data = try_send_handoff_email(
                runtime,
                msg,
                session_vars,
            )
            handoff_sent = handoff_attempted and handoff_status in (200, 201, 202)
        else:
            handoff_data = {"info": "paused loop final handoff skipped by cooldown"}
        session_vars["paused_loop_final_handoff_attempted"] = True

    return get_phrase("paused_loop_final", lang), handoff_attempted, handoff_status, handoff_data, handoff_sent


def _parse_bool_query(value: str | None, default: bool = False) -> bool:
    return parse_bool_query(value, default)


def _is_authorized_for_audit() -> bool:
    load_local_env()
    expected = _env("ORCHESTRATOR_API_KEY")
    if not expected:
        return True

    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth.removeprefix("Bearer ").strip() == expected

    direct_token = (
        request.headers.get("api-key")
        or request.headers.get("x-api-key")
        or request.args.get("api_key")
        or request.args.get("key")
        or ""
    ).strip()
    return bool(direct_token) and direct_token == expected


@app.get("/health")
def health() -> Any:
    payload = build_version_payload()
    return jsonify(build_health_response(payload))


@app.get("/audit/conversations")
def audit_conversations() -> Any:
        if not _is_authorized_for_audit():
                return auth_error("Invalid or missing API key for audit endpoint.")

        org_id = (request.args.get("organization_id") or DEFAULT_ORG_ID).strip()
        days_back_raw = (request.args.get("days_back") or "").strip()
        max_conversations_raw = (request.args.get("max_conversations") or "").strip()
        include_test = _parse_bool_query(request.args.get("include_test"), default=False)

        try:
                days_back = int(days_back_raw) if days_back_raw else None
                max_conversations = int(max_conversations_raw) if max_conversations_raw else None
        except ValueError:
                return jsonify({"ok": False, "error": "days_back and max_conversations must be integers"}), 400

        try:
                report = run_conversation_audit(
                        organization_id=org_id,
                        days_back=days_back,
                        include_test_conversations=include_test,
                        max_conversations=max_conversations,
                )
                return jsonify({"ok": True, "report": report})
        except Exception as exc:  # pragma: no cover
                return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/audit/dashboard")
def audit_dashboard() -> Any:
        if not _is_authorized_for_audit():
                return auth_error("Invalid or missing API key for audit dashboard.")

        org_id = (request.args.get("organization_id") or DEFAULT_ORG_ID).strip()
        days_back_raw = (request.args.get("days_back") or "").strip()
        include_test = _parse_bool_query(request.args.get("include_test"), default=False)

        try:
                days_back = int(days_back_raw) if days_back_raw else None
        except ValueError:
                return "days_back must be an integer", 400

        try:
                report = run_conversation_audit(
                        organization_id=org_id,
                        days_back=days_back,
                        include_test_conversations=include_test,
                )
        except Exception as exc:  # pragma: no cover
                return f"Audit error: {exc}", 500

        return render_audit_dashboard_html(report)


@app.get("/version")
def version() -> Any:
    payload = build_version_payload()
    return jsonify(build_safe_version_response(payload))


# ---------------------------------------------------------------------------
# Post-processing policies (Step 1 of refactor: mechanical extraction).
#
# These are pure helpers — same semantics as the inline blocks they replaced
# inside chat_completions_compatible. They mutate session_vars in place
# (matching the prior behavior) and return the possibly-modified reply.
# Tested in tests/test_helpers.py.
# ---------------------------------------------------------------------------


def apply_email_ack_or_request_policy(
    reply: str,
    session_vars: dict[str, Any],
    extracted_email: str | None,
    lang: str,
    user_text: str = "",
) -> str:
    """Fix #6 + proactive email request.

    If the user just shared an email, replace the LLM reply with a
    deterministic ack and mark email captured (single-ask rule). Otherwise,
    when the conversation is in the email-request window and no email has
    been seen yet, append the proactive ask.
    """
    return _apply_email_ack_or_request_policy(
        reply,
        session_vars,
        extracted_email,
        lang,
        get_phrase=get_phrase,
        should_request_email=lambda sv: should_request_email(sv or {}),
        user_text=user_text,
    )


def apply_out_of_season_policy(
    reply: str,
    user_text: str,
    session_vars: dict[str, Any],
    lang: str,
) -> str:
    """Fix #7: prepend an out-of-season heads-up once per conversation."""
    return _apply_out_of_season_policy(
        reply,
        user_text,
        session_vars,
        lang,
        mentions_out_of_season=mentions_out_of_season,
        get_phrase=get_phrase,
    )


def apply_language_commit_policy(user_text: str, session_vars: dict[str, Any]) -> None:
    """Fix #2: only commit conversation_language when the new user message
    has a confident language signal; otherwise keep the previous value.
    """
    _apply_language_commit_policy(
        user_text,
        session_vars,
        detect_explicit_language_preference=detect_explicit_language_preference,
        detect_language_confident=detect_language_confident,
        i18n_languages=set(I18N_PHRASES.keys()),
        get_session_language=get_session_language,
    )


def process_inbound_message(
    client: OpenAI,
    runtime: dict[str, Any],
    msg: InboundMessage,
    context: ProcessingContext,
) -> tuple[ReplyDecision, dict[str, Any]]:
    """Run deterministic + LLM decision flow and return reply + updated vars."""
    msg_dict = msg.as_dict()
    session_vars = context.session_vars

    # Check CRM client status by phone (from contact_address) first, fallback to email
    phone = msg.contact_address.strip()
    print(f"[SERVER_DEBUG] Checking CRM for phone={phone}")
    if phone:  # Only check if we have a phone number
        extracted_email_temp = extract_email_from_text(msg.text)
        print(f"[SERVER_DEBUG] Calling check_client_status with phone={phone}, email={extracted_email_temp}")
        crm_status = check_client_status(phone=phone, email=extracted_email_temp or "")
        print(f"[SERVER_DEBUG] CRM Status result: {crm_status}")
        session_vars["crm_client_found"] = crm_status.get("found", False)
        session_vars["crm_client_contacted"] = crm_status.get("contacted", False)
        session_vars["crm_client_id"] = crm_status.get("client_id")
        session_vars["crm_client_name"] = crm_status.get("client_name")
        session_vars["crm_consultation_count"] = crm_status.get("consultation_count", 0)
        session_vars["crm_last_consultation_date"] = crm_status.get("last_consultation_date")
        session_vars["crm_search_method"] = crm_status.get("search_by")
    else:
        print("[SERVER_DEBUG] No phone number in contact_address, skipping CRM check")

    # Email verification logic
    email_verification_enabled = runtime.get("email_verification_enabled", True)
    context.extracted_email = extract_email_from_text(msg.text)
    conversation_paused = bool(session_vars.get("conversation_paused"))

    # Fix #1: persist email capture as soon as the user shares any email,
    # regardless of HIBP outcome. This blocks the proactive-email loop.
    if context.extracted_email:
        emails_seen = list(session_vars.get("emails_seen") or [])
        if context.extracted_email.lower() not in (e.lower() for e in emails_seen):
            emails_seen.append(context.extracted_email)
        session_vars["emails_seen"] = emails_seen[-10:]
        session_vars["email_captured"] = True
        if not session_vars.get("captured_email"):
            session_vars["captured_email"] = context.extracted_email
        if not session_vars.get("email_captured_at_ts"):
            session_vars["email_captured_at_ts"] = int(time.time())
        session_vars["email_requested"] = True

    # Check CRM client status if we have an email
    if context.extracted_email and not session_vars.get("crm_client_found"):
        crm_status = check_client_status(email=context.extracted_email)
        session_vars["crm_client_found"] = crm_status.get("found", False)
        session_vars["crm_client_contacted"] = crm_status.get("contacted", False)
        session_vars["crm_client_id"] = crm_status.get("client_id")
        session_vars["crm_client_name"] = crm_status.get("client_name")
        session_vars["crm_consultation_count"] = crm_status.get("consultation_count", 0)
        session_vars["crm_last_consultation_date"] = crm_status.get("last_consultation_date")

    if email_verification_enabled and not conversation_paused:
        if context.extracted_email and not session_vars.get("email_verified"):
            is_suspicious, check_succeeded = check_email_reputation(
                context.extracted_email,
                runtime.get("hibp_api_key") or "",
                timeout=runtime.get("hibp_timeout_seconds", 10),
            )

            if check_succeeded:
                session_vars["email_verified"] = True
                session_vars["verified_email"] = context.extracted_email
                session_vars["email_checked_at_ts"] = int(time.time())
                # HIBP "not found" is recorded as information, not as a reason to
                # pause: one in three genuine leads had no breach history.
                session_vars["email_in_breaches"] = not is_suspicious
                bot_reason = bot_signal(
                    session_vars,
                    msg.text,
                    context.extracted_email,
                    email_in_breaches=not is_suspicious,
                )

                if bot_reason:
                    context.email_suspicious = True
                    context.suspicious_email_value = context.extracted_email
                    session_vars["bot_signal"] = bot_reason
                    session_vars = pause_conversation(
                        session_vars,
                        context.extracted_email,
                        f"Conversation looks automated: {bot_reason}",
                    )

                    if not session_vars.get("suspicious_email_alert_sent"):
                        alert_attempted, alert_status, alert_data, alert_sent, alert_method = try_send_suspicious_admin_alert(
                            runtime,
                            msg_dict,
                            context.extracted_email,
                            session_vars,
                        )
                        context.email_suspicious_alert_sent = alert_sent
                        if alert_attempted:
                            session_vars["suspicious_email_alert_last_status"] = alert_status
                            session_vars["suspicious_email_alert_method"] = alert_method
                            session_vars["suspicious_email_alert_last_response"] = alert_data

                    if context.email_suspicious_alert_sent:
                        session_vars["suspicious_email_alert_sent_ts"] = int(time.time())
                else:
                    session_vars["email_verified_real"] = True
                    if not session_vars.get("new_lead_email_sent"):
                        lead_attempted, lead_status, _ = try_send_new_lead_email(
                            runtime,
                            msg_dict,
                            context.extracted_email,
                            session_vars,
                        )
                        if lead_attempted and lead_status in (200, 201, 202):
                            session_vars["new_lead_email_sent"] = True
                            session_vars["new_lead_email_sent_ts"] = int(time.time())
            else:
                session_vars["email_check_failed"] = True
                session_vars["email_check_failed_at_ts"] = int(time.time())

    proactive_email_capture_pending = bool(session_vars.get("proactive_email_capture_pending"))
    proactive_email_verified = (
        bool(context.extracted_email)
        and proactive_email_capture_pending
        and not bool(session_vars.get("handoff_pending_confirmation"))
        and bool(session_vars.get("email_verified_real"))
    )
    proactive_email_check_failed = (
        bool(context.extracted_email)
        and proactive_email_capture_pending
        and not bool(session_vars.get("handoff_pending_confirmation"))
        and bool(session_vars.get("email_check_failed"))
        and not context.email_suspicious
    )

    # --- HANDOFF DETECTION (before LLM) ---
    context.handoff_requested = wants_human_handoff(msg.text, session_vars)
    if (
        not context.handoff_requested
        and session_vars.get("handoff_pending_confirmation")
        and session_vars.get("email_verified_real")
    ):
        context.handoff_requested = True

    decision = ReplyDecision(reply="")
    if session_vars.get("conversation_paused"):
        (
            decision.reply,
            decision.handoff_attempted,
            decision.handoff_status,
            decision.handoff_data,
            decision.handoff_sent,
        ) = apply_paused_anti_loop_guard(
            session_vars,
            msg_dict,
            runtime,
            context.now_ts,
        )
    elif context.handoff_requested and not session_vars.get("email_verified_real"):
        lang = get_session_language(session_vars, msg.text)
        decision.reply = get_phrase("handoff_ask_email", lang)
        session_vars["handoff_pending_confirmation"] = True
        session_vars["email_requested"] = True
        decision.handoff_data = {"info": "handoff pending email verification"}
    elif context.handoff_requested:
        lang = get_session_language(session_vars, msg.text)
        cooldown_ok = should_send_handoff_email(
            session_vars,
            runtime["handoff_email_cooldown_seconds"],
            context.now_ts,
        )
        if cooldown_ok:
            decision.handoff_attempted, decision.handoff_status, decision.handoff_data = try_send_handoff_email(
                runtime,
                msg_dict,
                session_vars,
            )
        else:
            decision.handoff_data = {"info": "handoff email skipped by cooldown"}
        decision.reply = get_phrase("handoff_executed", lang)
        session_vars["conversation_paused"] = True
        session_vars["pause_reason"] = "human_handoff_in_progress"
        session_vars["paused_reply_count"] = 0
        session_vars["paused_loop_frozen"] = False
        session_vars["paused_loop_finalized_at_ts"] = None
        session_vars["paused_loop_final_handoff_attempted"] = False
        session_vars["handoff_pending_confirmation"] = False
        session_vars["paused_at_ts"] = context.now_ts
        decision.handoff_sent = (
            cooldown_ok and decision.handoff_attempted and decision.handoff_status in (200, 201, 202)
        )
    elif proactive_email_verified:
        lang = get_session_language(session_vars, msg.text)
        decision.reply = get_phrase("proactive_email_saved", lang)
        session_vars["proactive_email_capture_pending"] = False
        session_vars["email_requested"] = False
        session_vars["conversation_paused"] = False
    elif proactive_email_check_failed:
        lang = get_session_language(session_vars, msg.text)
        decision.reply = get_phrase("proactive_email_check_failed", lang)
        session_vars["proactive_email_capture_pending"] = False
        session_vars["email_requested"] = False
    elif session_vars.get("handoff_pending_confirmation"):
        lang = get_session_language(session_vars, msg.text)
        decision.reply = get_phrase("handoff_pending", lang)
    elif session_vars.get("conversation_paused"):
        (
            decision.reply,
            decision.handoff_attempted,
            decision.handoff_status,
            decision.handoff_data,
            decision.handoff_sent,
        ) = apply_paused_anti_loop_guard(
            session_vars,
            msg_dict,
            runtime,
            context.now_ts,
        )
    else:
        lang = get_session_language(session_vars, msg.text)
        # On the very first turn, respond with a hardcoded opening welcome for
        # pure greetings (e.g. "Hi", "Hola") instead of calling the LLM.
        if session_vars.get("conversation_turn_count") == 1 and (
            _is_pure_greeting(msg.text) or is_generic_opening(msg.text)
        ):
            decision.reply = get_phrase("opening_welcome", lang)
        elif is_thanks_only(msg.text):
            thanks_count = int(session_vars.get("thanks_reply_count") or 0)
            decision.reply = get_phrase(f"thanks_reply_{thanks_count % 2 + 1}", lang)
            session_vars["thanks_reply_count"] = thanks_count + 1
        else:
            guided_reply = build_program_options_guidance_reply(msg.text, session_vars, lang)
            if asks_if_bot(msg.text):
                # Honest and fixed: the model tended to dodge it with "no lo tengo a mano".
                decision.reply = get_phrase("bot_question", lang)
            elif guided_reply is not None:
                decision.reply = guided_reply
            else:
                decision.hits = retrieve_with_context(
                    client,
                    runtime["embed_model"],
                    runtime["rows"],
                    msg.text,
                    session_vars.get("recent_turns"),
                    runtime["top_k"],
                )
                decision.hits = ensure_departure_hit(
                    decision.hits, runtime["rows"], msg.text, lang, runtime["top_k"]
                )
                decision.reply = generate_reply(
                    client,
                    runtime["chat_model"],
                    runtime["system_prompt"],
                    msg_dict,
                    decision.hits,
                    session_vars,
                    history_turns=runtime.get("history_turns", DEFAULT_HISTORY_TURNS),
                )
                decision.reply = apply_email_ack_or_request_policy(
                    decision.reply, session_vars, context.extracted_email, lang, msg.text
                )
                decision.reply = apply_out_of_season_policy(decision.reply, msg.text, session_vars, lang)

    decision.reply = format_whatsapp_departure_dates(decision.reply, msg.channel)

    # Outbound safety filter: never send credential-like content.
    effective_lang = get_session_language(session_vars, msg.text)
    if contains_sensitive_outbound_content(decision.reply):
        decision.reply = build_sensitive_outbound_block_reply(effective_lang)
        decision.outbound_safety_blocked = True

    # Short-window anti-duplicate guard for same assistant reply bursts.
    if is_recent_duplicate_reply(decision.reply, session_vars, context.now_ts):
        decision.reply = resolve_duplicate_reply(decision.reply, session_vars, context.now_ts, effective_lang)
        decision.outbound_suppressed = not decision.reply

    apply_language_commit_policy(msg.text, session_vars)

    updated_vars = {
        **session_vars,
        "last_user_message": msg.text,
        "channel": msg.channel,
        "contact_address": msg.contact_address,
        "handoff_requested": context.handoff_requested,
        "last_inbound_signature": context.inbound_signature,
        "last_inbound_signature_ts": context.now_ts,
    }
    if decision.reply.strip():
        updated_vars["last_assistant_reply"] = decision.reply
        updated_vars["last_assistant_reply_ts"] = context.now_ts
    updated_vars["recent_turns"] = append_recent_turns(
        session_vars.get("recent_turns"), msg.text, decision.reply
    )

    if decision.handoff_sent:
        updated_vars["handoff_email_last_sent_ts"] = context.now_ts
        updated_vars["handoff_email_last_to"] = runtime.get("handoff_email_to")
        updated_vars["handoff_pending_confirmation"] = False

    if context.email_suspicious:
        updated_vars["email_suspicious"] = True
        updated_vars["suspicious_email"] = context.suspicious_email_value

    if context.email_suspicious_alert_sent:
        updated_vars["suspicious_email_alert_sent"] = True
        updated_vars["suspicious_email_alert_sent_ts"] = context.now_ts

    return decision, updated_vars


# Compatibility aliases for providers that normalize or append the path
# differently under Chat Completions mode.
@app.post("/v1")
@app.post("/chat/completions")
@app.post("/v1/chat/completions")
def chat_completions_compatible() -> Any:
    """OpenAI Chat Completions compatible endpoint for OpenBSP custom model."""
    if not is_authorized_for_chat():
        return auth_error("Invalid or missing Authorization bearer token.")

    body = request.get_json(silent=True) or {}

    model = body.get("model")
    messages = body.get("messages")
    tools_payload = body.get("tools")
    stream = body.get("stream")
    if not isinstance(model, str) or not isinstance(messages, list):
        return (
            jsonify(
                {
                    "error": {
                        "message": "Invalid request body: expected model and messages.",
                        "type": "invalid_request_error",
                    }
                }
            ),
            400,
        )
    # Compatibility: some providers always send stream=true.
    # We currently return a non-streaming completion payload.
    _ = bool(stream)

    user_text = extract_last_user_text(messages)
    if not user_text:
        return (
            jsonify(
                {
                    "error": {
                        "message": "Could not extract user message text from messages.",
                        "type": "invalid_request_error",
                    }
                }
            ),
            400,
        )

    headers_dict = validate_and_normalize_headers(request.headers)
    inbound_msg = InboundMessage.from_headers(user_text, headers_dict)
    load_local_env()
    lightweight_model_runtime = {
        "chat_model": _env("OPENAI_CHAT_MODEL", "gpt-5.4"),
        "chat_model_from_request": str(_env("OPENAI_CHAT_MODEL_FROM_REQUEST", "false") or "false")
        .strip()
        .lower()
        in ("1", "true", "yes", "on"),
        "allowed_chat_models": parse_csv_set(_env("OPENAI_ALLOWED_CHAT_MODELS", "") or ""),
    }
    effective_chat_model, effective_chat_model_source = resolve_effective_chat_model(
        model,
        lightweight_model_runtime,
    )
    command = extract_command(user_text)
    if command in ("/reset", "/new"):
        session_base_url = _env("SESSION_AGENT_BASE_URL")
        session_agent_id = _env("SESSION_AGENT_ID", "sales-agent-v1") or "sales-agent-v1"
        pre_reset_vars: dict[str, Any] = {}
        snapshot = try_session_get(session_base_url, inbound_msg.conversation_id)
        if snapshot and isinstance(snapshot.get("variables"), dict):
            pre_reset_vars = snapshot["variables"]
        reset_session_state(session_base_url, inbound_msg.as_dict(), session_agent_id)

        # Use best-known language from the pre-reset session and current text.
        reply_lang = get_session_language(pre_reset_vars, user_text)
        reply = get_phrase("opening_welcome", reply_lang)
        split_parts = split_reply_into_messages(reply)
        can_emit_multi = is_multi_message_enabled() and supports_respond_tool(tools_payload)
        if can_emit_multi and len(split_parts) >= 2:
            completion = {
                "id": f"chatcmpl-{uuid4().hex[:24]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": effective_chat_model,
                "choices": [
                    {
                        "index": 0,
                        "message": build_respond_tool_call_message(split_parts),
                        "finish_reason": "tool_calls",
                        "logprobs": None,
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
        else:
            completion = {
                "id": f"chatcmpl-{uuid4().hex[:24]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": effective_chat_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": reply},
                        "finish_reason": "stop",
                        "logprobs": None,
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
        return jsonify(completion)
    msg = inbound_msg.as_dict()

    if command == "/version":
        try:
            runtime = ensure_runtime()
            session_vars: dict[str, Any] = {}
            session_base_url = runtime["session_base_url"]
            snapshot = try_session_get(session_base_url, msg["conversation_id"])
            if snapshot and isinstance(snapshot.get("variables"), dict):
                session_vars = snapshot["variables"]
            detected_lang = get_session_language(session_vars, msg["text"])
            version_text = build_version_text()
            model_text = (
                f"\nConfigured chat model: {runtime.get('chat_model')}"
                f"\nConfigured embed model: {runtime.get('embed_model')}"
                f"\nRequested chat model: {str(model).strip()}"
                f"\nEffective chat model: {effective_chat_model}"
                f"\nModel source: {effective_chat_model_source}"
            )

            client_status_text = ""
            if session_vars.get("crm_client_found"):
                client_status = "✅ CONTACTED" if session_vars.get("crm_client_contacted") else "👤 NEW CLIENT"
                client_status_text = f"\nCRM Client: {client_status} ({session_vars.get('crm_client_name', 'Unknown')})"
            else:
                client_status_text = "\nCRM Client: Not found in system"

            reply = (
                f"{version_text}{model_text}{client_status_text}"
                f"\nConversation Language: {detected_lang}"
                f"\nDetected from: {get_language_source(session_vars)}"
            )
        except Exception:
            reply = build_version_text()
        completion = {
            "id": f"chatcmpl-{uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": effective_chat_model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": reply},
                    "finish_reason": "stop",
                    "logprobs": None,
                }
            ],
            "usage": {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            },
        }
        return jsonify(completion)

    try:
        runtime = ensure_runtime()
        runtime["chat_model"] = effective_chat_model
        client = OpenAI(api_key=runtime["api_key"])

        session_vars: dict[str, Any] = {}
        session_base_url = runtime["session_base_url"]
        snapshot = try_session_get(session_base_url, msg["conversation_id"])
        if snapshot and isinstance(snapshot.get("variables"), dict):
            session_vars = snapshot["variables"]

        now_ts = int(time.time())
        inbound_signature = build_inbound_signature(msg)
        if is_duplicate_inbound(session_vars, inbound_signature, now_ts):
            # The first delivery was already answered; replaying that answer
            # made OpenBSP send it to the client a second time (audit
            # 2026-09: email acks arriving twice, ~60s apart). Acknowledge the
            # retry with an empty reply, which OpenBSP does not send.
            completion = {
                "id": f"chatcmpl-{uuid4().hex[:24]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": effective_chat_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "stop",
                        "logprobs": None,
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
                "deduplicated": True,
            }
            return jsonify(completion)

        human_active, human_info = human_replied_recently(
            supabase_url=runtime.get("supabase_url"),
            supabase_key=runtime.get("supabase_key"),
            conversation_id=msg["conversation_id"],
            window_hours=runtime.get("human_silence_hours", 12),
            nico_agent_id=runtime.get("nico_agent_id", DEFAULT_NICO_AGENT_ID),
        )
        print(f"[HUMAN_ACTIVITY] {msg['conversation_id']} silenced={human_active} {human_info}", flush=True)
        if human_active:
            # An advisor wrote in this conversation recently (often from the
            # WhatsApp Business phone app). Stay out of it: no reply, but keep
            # the inbound on record and mark the signature so retries dedupe.
            try_session_append_event(
                session_base_url,
                msg["conversation_id"],
                "inbound_message_silenced_human_active",
                {"text": msg["text"], "channel": msg["channel"], **human_info},
            )
            try_session_upsert(
                session_base_url,
                msg,
                runtime["session_agent_id"],
                {
                    **session_vars,
                    "last_user_message": msg["text"],
                    "last_inbound_signature": inbound_signature,
                    "last_inbound_signature_ts": now_ts,
                    "human_active_last_seen": human_info.get("last_human_message_at"),
                    "recent_turns": append_recent_turns(session_vars.get("recent_turns"), msg["text"], ""),
                },
            )
            return jsonify(
                {
                    "id": f"chatcmpl-{uuid4().hex[:24]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": effective_chat_model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": ""},
                            "finish_reason": "stop",
                            "logprobs": None,
                        }
                    ],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    "silenced_human_active": True,
                }
            )

        # Increment conversation turn counter
        current_turn = session_vars.get("conversation_turn_count", 0)
        session_vars["conversation_turn_count"] = current_turn + 1

        # Ensure session exists before appending events (new conversation case)
        try_session_upsert(session_base_url, msg, runtime["session_agent_id"], session_vars)

        try_session_append_event(
            session_base_url,
            msg["conversation_id"],
            "inbound_message",
            {
                "text": msg["text"],
                "channel": msg["channel"],
                "contact_id": msg["contact_id"],
            },
        )
        context = ProcessingContext(
            session_vars=session_vars,
            now_ts=now_ts,
            inbound_signature=inbound_signature,
        )
        decision, updated_vars = process_inbound_message(
            client=client,
            runtime=runtime,
            msg=inbound_msg,
            context=context,
        )

        multi_message_enabled = is_multi_message_enabled()
        can_emit_multi = multi_message_enabled and supports_respond_tool(tools_payload)
        is_opening = session_vars.get("conversation_turn_count") == 1 and _is_pure_greeting(msg["text"])
        split_parts = choose_reply_bubbles(decision.reply, can_emit_multi, is_opening)

        # Two client messages sent seconds apart are processed in parallel and
        # both read the session before either saved its reply, so both sent
        # the same text (audit 2026-09). Re-read the session right before
        # persisting and drop the reply if a concurrent request already sent it.
        latest = try_session_get(session_base_url, msg["conversation_id"])
        latest_vars = latest.get("variables") if isinstance(latest, dict) else None
        if isinstance(latest_vars, dict) and is_recent_duplicate_reply(decision.reply, latest_vars, int(time.time())):
            decision.reply = ""
            decision.outbound_suppressed = True
            split_parts = []
            updated_vars["last_assistant_reply"] = latest_vars.get("last_assistant_reply")
            updated_vars["last_assistant_reply_ts"] = latest_vars.get("last_assistant_reply_ts")
        if isinstance(latest_vars, dict) and "recent_turns" in latest_vars:
            # Build on the freshest transcript so a parallel request's turn is kept.
            updated_vars["recent_turns"] = append_recent_turns(
                latest_vars.get("recent_turns"), msg["text"], decision.reply
            )

        try_session_upsert(
            session_base_url,
            msg,
            runtime["session_agent_id"],
            updated_vars,
        )
        if decision.handoff_sent:
            try_session_append_event(
                session_base_url,
                msg["conversation_id"],
                "handoff_email",
                {
                    "to": runtime.get("handoff_email_to"),
                    "status": decision.handoff_status,
                    "provider": runtime.get("handoff_email_provider"),
                    "response": decision.handoff_data,
                },
            )
        if context.email_suspicious_alert_sent:
            try_session_append_event(
                session_base_url,
                msg["conversation_id"],
                "suspicious_email_alert",
                {
                    "email": context.suspicious_email_value,
                    "status": "sent_to_admin",
                    "reason": "Email appears unverified or new, requires manual validation",
                    "method": updated_vars.get("suspicious_email_alert_method", "security_alert"),
                },
            )
        if decision.reply.strip():
            try_session_append_event(
                session_base_url,
                msg["conversation_id"],
                "outbound_message",
                {
                    "text": decision.reply,
                    "source": "acomara-orchestrator-chat-completions",
                    "faq_sources": [h["id"] for h in decision.hits],
                    "llm_model": effective_chat_model,
                    "llm_model_source": effective_chat_model_source,
                },
            )

        if len(split_parts) >= 2:
            completion = {
                "id": f"chatcmpl-{uuid4().hex[:24]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": effective_chat_model,
                "choices": [
                    {
                        "index": 0,
                        "message": build_respond_tool_call_message(split_parts),
                        "finish_reason": "tool_calls",
                        "logprobs": None,
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
        else:
            completion = {
                "id": f"chatcmpl-{uuid4().hex[:24]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": effective_chat_model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": decision.reply},
                        "finish_reason": "stop",
                        "logprobs": None,
                    }
                ],
                "usage": {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                },
            }
        return jsonify(completion)
    except Exception as exc:  # pragma: no cover
        print(f"[ERROR] /v1/chat/completions: {exc}", flush=True)
        return (
            jsonify(
                {
                    "error": {
                        "message": "An internal error occurred. Please try again later.",
                        "type": "server_error",
                    }
                }
            ),
            500,
        )


if __name__ == "__main__":
    load_local_env()
    port = int(_env("ORCHESTRATOR_PORT", "8080") or "8080")
    app.run(host="0.0.0.0", port=port)
