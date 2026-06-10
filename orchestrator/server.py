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
    check_email_reputation,
    extract_email_from_text,
    pause_conversation,
    should_request_email,
)
from orchestrator.handoff_email import (
    try_send_handoff_email,
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
from orchestrator.conversation_audit import DEFAULT_ORG_ID, run_conversation_audit

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "docs" / "knowledge" / "faq_cloud_index.jsonl"
SYSTEM_PROMPT_PATH = ROOT / "docs" / "sales-agent" / "02-system-prompt.md"

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
        "handoff_ask_email": "Para conectarte con un asesor, primero necesito tu correo electrónico para poder derivarte correctamente. ¿Cuál es tu correo?",
        "handoff_executed": "Perfecto, ya derivé tu solicitud a un asesor humano. En breve te va a contactar un miembro del equipo por este medio.",
        "handoff_pending": "Todavía necesito tu correo electrónico para derivarte con el asesor. ¿Cuál es tu correo?",
        "proactive_email_request": "Si te parece, compartime tu correo electrónico ahora y lo verifico para dejar lista una posible derivación con un asesor.",
        "proactive_email_saved": "Gracias. Ya verifiqué tu correo y quedó registrado. Si después querés que te conecte con un asesor, ya lo tengo listo.",
        "proactive_email_check_failed": "Gracias. Ya recibí tu correo, pero no pude validarlo en este momento. Igual quedó registrado por si necesitás derivación con un asesor.",
        "paused_handoff": "Tu solicitud ya fue derivada a un asesor humano. En breve te va a contactar un miembro del equipo por este medio.",
        "paused_suspicious": "Excelente, te vamos a estar contactando en breve.",
        "paused_proactive_email": "Estoy esperando tu correo electrónico para poder verificarlo y continuar la conversación de forma segura.",
        "paused_loop_final": "Ya registramos tu solicitud y un asesor humano va a continuar por este medio. Para evitar mensajes repetitivos, cierro este hilo automático hasta que el equipo te contacte.",
        "email_received_ack": "¡Gracias! Ya tengo tu correo ({email}) registrado. Un asesor humano va a revisar tu consulta y te contacta en breve por este medio. Mientras tanto, si querés agregar más detalles (fechas, número de personas, experiencia previa), escribilos y los sumamos a la derivación.",
        "out_of_season": "Importante: las expediciones al Aconcagua se realizan únicamente entre noviembre y marzo (temporada del hemisferio sur). Para la fecha que mencionás no tenemos salidas. Si querés, te paso el calendario disponible de la próxima temporada.",
        "opening_welcome": "Hola! Gracias por contactarnos. ¿En qué te puedo ayudar?\n\nPara orientarte mejor, además de responder tus preguntas, si te parece te envío más información por email: precios, fechas, servicios, lista de equipo, referencias y recomendaciones.",
    },
    "en": {
        "reset_acknowledge": "Conversation restarted. How can I help you?",
        "handoff_ask_email": "To connect you with an advisor, I first need your email address. What is your email?",
        "handoff_executed": "Perfect, I've forwarded your request to a human advisor. A team member will contact you shortly.",
        "handoff_pending": "I still need your email address to connect you with an advisor. What is your email?",
        "proactive_email_request": "If you'd like, share your email now and I'll verify it so a possible handoff to an advisor is ready.",
        "proactive_email_saved": "Thanks. I already verified your email and saved it. If you want me to connect you with an advisor later, it's ready.",
        "proactive_email_check_failed": "Thanks. I received your email, but I couldn't validate it right now. It was still saved in case you need a handoff to an advisor.",
        "paused_handoff": "Your request has been forwarded to a human advisor. A team member will contact you shortly.",
        "paused_suspicious": "Great! We'll be in touch shortly.",
        "paused_proactive_email": "I'm waiting for your email address to verify it and continue the conversation securely.",
        "paused_loop_final": "We have already registered your request and a human advisor will continue through this channel. To avoid repetitive messages, I'm now closing this automated thread until the team contacts you.",
        "email_received_ack": "Thanks! I've saved your email ({email}). A human advisor will review your request and contact you shortly through this channel. In the meantime, feel free to add any extra details (dates, number of people, previous experience) and I'll include them in the handoff.",
        "out_of_season": "Heads up: Aconcagua expeditions run only between November and March (Southern Hemisphere season). We don't have departures on the date you mentioned. If you'd like, I can share the available calendar for the next season.",
        "opening_welcome": "Hi! Thanks for reaching out. How can I help you?\n\nTo guide you better, besides answering your questions here, if you'd like I can send you more info by email: prices, dates, services, gear list, references and recommendations.",
    },
    "pt": {
        "reset_acknowledge": "Conversa reiniciada. Como posso ajudá-lo?",
        "handoff_ask_email": "Para conectá-lo com um consultor, primeiro preciso do seu endereço de email. Qual é o seu email?",
        "handoff_executed": "Perfeito, encaminhei sua solicitação para um consultor humano. Um membro da equipe o contatará em breve.",
        "handoff_pending": "Ainda preciso do seu endereço de email para conectá-lo com um consultor. Qual é o seu email?",
        "proactive_email_request": "Se você quiser, compartilhe seu email agora e eu o verifico para deixar pronta uma possível transferência para um consultor.",
        "proactive_email_saved": "Obrigado. Já verifiquei seu email e ele ficou registrado. Se depois você quiser falar com um consultor, já está pronto.",
        "proactive_email_check_failed": "Obrigado. Recebi seu email, mas não consegui validá-lo agora. Mesmo assim ele ficou registrado caso você precise de transferência para um consultor.",
        "paused_handoff": "Sua solicitação foi encaminhada para um consultor humano. Um membro da equipe o contatará em breve.",
        "paused_suspicious": "Excelente, vamos estar em contato em breve.",
        "paused_proactive_email": "Estou esperando seu endereço de email para verificá-lo e continuar a conversa com segurança.",
        "paused_loop_final": "Sua solicitação já foi registrada e um consultor humano continuará por este canal. Para evitar mensagens repetitivas, vou encerrar este fluxo automático até que a equipe entre em contato.",
        "email_received_ack": "Obrigado! Já registrei seu email ({email}). Um consultor humano vai revisar sua consulta e entrar em contato em breve por este canal. Enquanto isso, se quiser adicionar mais detalhes (datas, número de pessoas, experiência prévia), me envie e os incluo na transferência.",
        "out_of_season": "Atenção: as expedições ao Aconcágua acontecem somente entre novembro e março (temporada do hemisfério sul). Para a data que você mencionou não temos saídas. Se quiser, posso te passar o calendário disponível da próxima temporada.",
        "opening_welcome": "Olá! Obrigado por entrar em contato. Como posso te ajudar?\n\nPara te orientar melhor, além de responder suas perguntas aqui, se quiser te envio mais informações por email: preços, datas, serviços, lista de equipamentos, referências e recomendações.",
    },
}


def detect_language_from_text(text: str) -> str:
    """Simple language detection from message content.

    Returns detected language code (es/pt/en) or 'es' as conservative default.
    Treats short ambiguous greetings ("hola"/"olá"/"hi") as unknown -> caller
    keeps the previous session language instead of locking in on the first
    greeting (which historically caused language drift).
    """
    if not text:
        return "es"

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
        "aconcagua",
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

    return "es"


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

    # Fallback: only commit if the heuristic returns something other than the
    # blind "es" default. A non-trivial message with mostly english/portuguese
    # keywords is reasonable evidence; a single "hola" is not.
    detected = detect_language_from_text(text)
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
    # English
    "april", "may", "june", "july", "august", "september", "october",
    # Spanish (normalized: no accents)
    "abril", "mayo", "junio", "julio", "agosto", "septiembre", "setiembre", "octubre",
    # Portuguese
    "maio", "junho", "julho", "agosto", "setembro", "outubro",
)
# Numeric date patterns indicating month 04-10 in DD/MM or MM/DD form.
_OUT_OF_SEASON_DATE_PATTERNS = (
    re.compile(r"\b\d{1,2}[/-](0?[4-9]|10)\b"),  # 27/05, 03-09
    re.compile(r"\b(0?[4-9]|10)[/-]\d{1,2}\b"),  # 05/27, 09-03
)
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
    for pattern in _OUT_OF_SEASON_DATE_PATTERNS:
        if pattern.search(normalized):
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
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


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


def generate_reply(
    client: OpenAI,
    chat_model: str,
    system_prompt: str,
    msg: dict[str, str],
    hits: list[dict[str, Any]],
    session_vars: dict[str, Any],
) -> str:
    context = hits_to_context(hits)
    user_lang = get_session_language(session_vars, msg["text"])

    lang_instruction = {
        "es": "Responde en español.",
        "en": "Respond in English.",
        "pt": "Responda em português.",
    }.get(user_lang, "Respond in the user's language.")

    crm_client_context = build_crm_client_context(session_vars)

    # Override conversation_language in the dumped state so the LLM does not
    # see a stale/contradictory signal vs the explicit lang_instruction.
    session_vars_for_llm = {**session_vars, "conversation_language": user_lang}

    is_whatsapp = str(msg.get("channel", "")).strip().lower() == "whatsapp"
    response_length_instruction = (
        "Mantén la respuesta muy corta: máximo 2 líneas y 280 caracteres."
        if is_whatsapp
        else "Mantén la respuesta corta: máximo 3 líneas y 450 caracteres."
    )

    user_prompt = (
        "Canal: {channel}\n"
        "Conversation ID: {conversation_id}\n"
        "Cliente pregunta:\n{question}\n\n"
        "Variables de sesion actuales:\n{session_vars}\n\n"
        "{crm_context}"
        "\n\nEvidencia interna recuperada:\n{context}\n\n"
        "Instrucciones CRÍTICAS:\n"
        "- {lang_instruction}\n"
        "- Basa tu respuesta ÚNICAMENTE en la evidencia recuperada.\n"
        "- Puedes traducir la respuesta del FAQ al idioma del usuario si es necesario.\n"
        "- Pero NO INVENTES, NO AGREGUES ni NO EMBELLEZCAS información más allá de lo que dice el FAQ.\n"
        "- La estructura y contenido de la respuesta debe ser fiel al FAQ, solo adaptado en idioma y claridad.\n"
        "- {response_length_instruction}\n"
        "- Si compartes fechas de salida y el canal es WhatsApp, usa lista numerada: una línea por programa con meses abreviados y días agrupados.\n"
        "- NO hagas preguntas de cierre ni acciones siguientes que no vengan del FAQ.\n"
        "- Si no hay evidencia suficiente, di claramente que esa información no está en la documentación."
    ).format(
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
            {"role": "user", "content": user_prompt},
        ],
    )
    return resp.output_text.strip()


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


def wants_human_handoff(text: str, session_vars: dict[str, Any] | None = None) -> bool:
    """Return True only when the user *explicitly* requests a human agent.

    Affirmative detection ("si", "ok", etc.) was deliberately removed because
    the LLM often mentions "asesor" in normal replies, which caused every
    short affirmative to be misdetected as a handoff request.
    """
    normalized = normalize_for_intent(text)
    triggers = (
        "contactar con un asesor",
        "contactar asesor",
        "hablar con un asesor",
        "hablar con una persona",
        "hablar con alguien",
        "hablar con un humano",
        "pasame con un asesor",
        "pasame con un humano",
        "pasame con alguien",
        "quiero hablar con",
        "quiero un asesor",
        "quiero un humano",
        "necesito un asesor",
        "necesito hablar",
        "agente humano",
        "representante humano",
        "operador humano",
        "speak to human",
        "talk to a human",
        "talk to someone",
        "human agent",
        "connect me with",
    )
    return any(trigger in normalized for trigger in triggers)


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
        "También hay otras alternativas. Si quieres, te las listo en detalle."
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
        "embed_model": _env("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
        "chat_model": _env("OPENAI_CHAT_MODEL", "gpt-4.1-mini"),
        "top_k": int(_env("TOP_K", "4") or "4"),
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
        "paused_reply_threshold": int(_env("PAUSED_REPLY_THRESHOLD", "2") or "2"),
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
    raw_threshold = runtime.get("paused_reply_threshold", 2)
    try:
        threshold = max(1, int(raw_threshold))
    except (TypeError, ValueError):
        threshold = 2

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
        should_request_email=should_request_email,
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

                if is_suspicious:
                    context.email_suspicious = True
                    context.suspicious_email_value = context.extracted_email
                    session_vars = pause_conversation(
                        session_vars,
                        context.extracted_email,
                        "Email appears to be unverified or new, requires manual validation",
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
        if session_vars.get("conversation_turn_count") == 1 and _is_pure_greeting(msg.text):
            decision.reply = get_phrase("opening_welcome", lang)
        else:
            guided_reply = build_program_options_guidance_reply(msg.text, session_vars, lang)
            if guided_reply is not None:
                decision.reply = guided_reply
            else:
                decision.hits = retrieve_top_k(
                    client,
                    runtime["embed_model"],
                    runtime["rows"],
                    msg.text,
                    runtime["top_k"],
                )
                decision.reply = generate_reply(
                    client,
                    runtime["chat_model"],
                    runtime["system_prompt"],
                    msg_dict,
                    decision.hits,
                    session_vars,
                )
                decision.reply = apply_email_ack_or_request_policy(
                    decision.reply, session_vars, context.extracted_email, lang
                )
                decision.reply = apply_out_of_season_policy(decision.reply, msg.text, session_vars, lang)

    decision.reply = format_whatsapp_departure_dates(decision.reply, msg.channel)

    # Outbound safety filter: never send credential-like content.
    effective_lang = get_session_language(session_vars, msg.text)
    if contains_sensitive_outbound_content(decision.reply):
        decision.reply = build_sensitive_outbound_block_reply(effective_lang)
        decision.outbound_safety_blocked = True

    # Short-window anti-duplicate guard for same assistant reply bursts.
    last_reply = str(session_vars.get("last_assistant_reply") or "").strip()
    raw_last_ts = session_vars.get("last_assistant_reply_ts")
    try:
        last_reply_ts = int(raw_last_ts) if raw_last_ts is not None else 0
    except (TypeError, ValueError):
        last_reply_ts = 0
    if (
        decision.reply.strip()
        and last_reply
        and normalize_for_intent(decision.reply) == normalize_for_intent(last_reply)
        and last_reply_ts
        and (context.now_ts - last_reply_ts) <= 45
    ):
        decision.reply = ""
        decision.outbound_suppressed = True

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
                "model": model,
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
                "model": model,
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

            client_status_text = ""
            if session_vars.get("crm_client_found"):
                client_status = "✅ CONTACTED" if session_vars.get("crm_client_contacted") else "👤 NEW CLIENT"
                client_status_text = f"\nCRM Client: {client_status} ({session_vars.get('crm_client_name', 'Unknown')})"
            else:
                client_status_text = "\nCRM Client: Not found in system"

            reply = f"{version_text}{client_status_text}\nConversation Language: {detected_lang}\nDetected from: {get_language_source(session_vars)}"
        except Exception:
            reply = build_version_text()
        completion = {
            "id": f"chatcmpl-{uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
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
        client = OpenAI(api_key=runtime["api_key"])

        session_vars: dict[str, Any] = {}
        session_base_url = runtime["session_base_url"]
        snapshot = try_session_get(session_base_url, msg["conversation_id"])
        if snapshot and isinstance(snapshot.get("variables"), dict):
            session_vars = snapshot["variables"]

        now_ts = int(time.time())
        inbound_signature = build_inbound_signature(msg)
        if is_duplicate_inbound(session_vars, inbound_signature, now_ts):
            replay_reply = str(session_vars.get("last_assistant_reply") or "").strip()
            if replay_reply:
                completion = {
                    "id": f"chatcmpl-{uuid4().hex[:24]}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": replay_reply},
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
        should_split_opening = (
            can_emit_multi
            and session_vars.get("conversation_turn_count") == 1
            and _is_pure_greeting(msg["text"])
            and decision.reply.strip()
        )
        split_parts = split_reply_into_messages(decision.reply) if should_split_opening else []

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
                },
            )

        if len(split_parts) >= 2:
            completion = {
                "id": f"chatcmpl-{uuid4().hex[:24]}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": model,
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
                "model": model,
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
