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
import smtplib
import sys
import time
import unicodedata
from email.message import EmailMessage
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

    if en_count > es_count and en_count > pt_count and en_count > 0:
        return "en"

    if es_count > pt_count and es_count > 0:
        return "es"
    if pt_count > 0:
        return "pt"
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


def find_text_candidate(obj: Any, preferred_keys: list[str]) -> str:
    if isinstance(obj, dict):
        for key in preferred_keys:
            value = obj.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for value in obj.values():
            text = find_text_candidate(value, preferred_keys)
            if text:
                return text
    elif isinstance(obj, list):
        for item in obj:
            text = find_text_candidate(item, preferred_keys)
            if text:
                return text
    return ""


def validate_and_normalize_headers(headers: Any, max_length: int = 1000) -> dict[str, str]:
    """Validate and normalize HTTP headers with size limits."""
    def safe_get(key: str, default: str = "") -> str:
        value = headers.get(key, default)
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        if len(value) > max_length:
            raise ValueError(f"Header '{key}' exceeds max length of {max_length}")
        return value

    return {
        "conversation_id": safe_get("conversation-id", "openbsp-conversation"),
        "organization_id": safe_get("organization-id", "openbsp-org"),
        "organization_address": safe_get("organization-address", "openbsp-org-address"),
        "contact_id": safe_get("contact-id", headers.get("x-contact-id", "openbsp-contact")),
        "contact_address": safe_get("contact-address", headers.get("x-contact-address", "openbsp-contact-address")),
        "channel": safe_get("x-channel", "whatsapp"),
    }


def normalize_inbound(payload: dict[str, Any]) -> dict[str, str]:
    text = find_text_candidate(payload, ["text", "body", "message", "content"])

    conversation_id = (
        str(
            payload.get("conversation_id")
            or payload.get("conversationId")
            or payload.get("conversation", {}).get("id")
            or payload.get("chat_id")
            or payload.get("thread_id")
            or ""
        ).strip()
        or "unknown-conversation"
    )

    organization_id = (
        str(
            payload.get("organization_id")
            or payload.get("organizationId")
            or payload.get("organization", {}).get("id")
            or "default-org"
        ).strip()
        or "default-org"
    )

    organization_address = (
        str(
            payload.get("organization_address")
            or payload.get("organizationAddress")
            or payload.get("organization", {}).get("address")
            or payload.get("account")
            or "default-org-address"
        ).strip()
        or "default-org-address"
    )

    contact_id = (
        str(
            payload.get("contact_id")
            or payload.get("contactId")
            or payload.get("contact", {}).get("id")
            or payload.get("from")
            or "unknown-contact"
        ).strip()
        or "unknown-contact"
    )

    contact_address = (
        str(
            payload.get("contact_address")
            or payload.get("contactAddress")
            or payload.get("contact", {}).get("address")
            or payload.get("phone")
            or payload.get("from")
            or "unknown-contact-address"
        ).strip()
        or "unknown-contact-address"
    )

    channel = (
        str(payload.get("channel") or payload.get("service") or "whatsapp").strip()
        or "whatsapp"
    )

    return {
        "text": text,
        "conversation_id": conversation_id,
        "organization_id": organization_id,
        "organization_address": organization_address,
        "contact_id": contact_id,
        "contact_address": contact_address,
        "channel": channel,
    }


def normalize_inbound_message(payload: dict[str, Any]) -> InboundMessage:
    """Typed wrapper over normalize_inbound for safer downstream wiring."""
    return InboundMessage(**normalize_inbound(payload))


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
    return {
        "organization-id": msg["organization_id"],
        "organization-address": msg["organization_address"],
        "conversation-id": msg["conversation_id"],
        "agent-id": agent_id,
        "contact-id": msg["contact_id"],
        "contact-address": msg["contact_address"],
    }


def session_get(session_base_url: str, conversation_id: str) -> dict[str, Any] | None:
    status, data = http_json(
        method="GET",
        url=f"{session_base_url.rstrip('/')}/v1/sessions/{conversation_id}",
        timeout=45,
    )
    if status == 200 and isinstance(data, dict):
        return data
    if status == 404:
        # New conversation — no session yet, not an error
        return None
    app.logger.warning("session_get failed", extra={"status": status, "data": data})
    return None


def session_delete(session_base_url: str, conversation_id: str) -> None:
    status, data = http_json(
        method="DELETE",
        url=f"{session_base_url.rstrip('/')}/v1/sessions/{conversation_id}",
        timeout=45,
    )
    if status not in (0, 200, 204):
        app.logger.warning("session_delete failed", extra={"status": status, "data": data})


def session_append_event(
    session_base_url: str,
    conversation_id: str,
    event_type: str,
    event_data: dict[str, Any],
) -> None:
    status, data = http_json(
        method="POST",
        url=f"{session_base_url.rstrip('/')}/v1/sessions/{conversation_id}/events",
        body={"event_type": event_type, "event_data": event_data},
        timeout=45,
    )
    if status not in (0, 200):
        app.logger.warning(
            "session_append_event failed",
            extra={"status": status, "data": data, "event_type": event_type},
        )


def session_upsert(
    session_base_url: str,
    msg: dict[str, str],
    agent_id: str,
    variables: dict[str, Any],
) -> None:
    status, data = http_json(
        method="POST",
        url=f"{session_base_url.rstrip('/')}/v1/sessions/upsert",
        body={
            "conversation_id": msg["conversation_id"],
            "organization_id": msg["organization_id"],
            "agent_id": agent_id,
            "contact_id": msg["contact_id"],
            "variables": variables,
        },
        timeout=45,
    )
    if status not in (0, 200):
        app.logger.warning("session_upsert failed", extra={"status": status, "data": data})


def try_session_get(session_base_url: str | None, conversation_id: str) -> dict[str, Any] | None:
    if not session_base_url:
        return None
    try:
        return session_get(session_base_url, conversation_id)
    except Exception as exc:  # pragma: no cover
        app.logger.warning("session_get exception: %s", exc)
        return None


def try_session_append_event(
    session_base_url: str | None,
    conversation_id: str,
    event_type: str,
    event_data: dict[str, Any],
) -> None:
    if not session_base_url:
        return
    try:
        session_append_event(session_base_url, conversation_id, event_type, event_data)
    except Exception as exc:  # pragma: no cover
        app.logger.warning("session_append_event exception: %s", exc)


def try_session_upsert(
    session_base_url: str | None,
    msg: dict[str, str],
    agent_id: str,
    variables: dict[str, Any],
) -> None:
    if not session_base_url:
        return
    try:
        session_upsert(session_base_url, msg, agent_id, variables)
    except Exception as exc:  # pragma: no cover
        app.logger.warning("session_upsert exception: %s", exc)


def try_session_delete(
    session_base_url: str | None,
    conversation_id: str,
) -> None:
    if not session_base_url:
        return
    try:
        session_delete(session_base_url, conversation_id)
    except Exception as exc:  # pragma: no cover
        app.logger.warning("session_delete exception: %s", exc)


def build_reset_session_vars(now_ts: int) -> dict[str, Any]:
    """Build a canonical clean session state for /reset.

    Defaults conversation_language to Spanish.
    """
    return {
        "conversation_language": "es",
        "conversation_language_source": "reset",
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
                "Es su primer contacto, sé bienvenido y explica bien los servicios."
            )
    else:
        crm_client_context = "\n👥 PROSPECTO DESCONOCIDO: Este cliente no está registrado en nuestro sistema."

    # Override conversation_language in the dumped state so the LLM does not
    # see a stale/contradictory signal vs the explicit lang_instruction.
    session_vars_for_llm = {**session_vars, "conversation_language": user_lang}

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
        "- Si compartes fechas de salida y el canal es WhatsApp, muéstralas en formato de lista, con una fecha por línea (no en un solo bloque).\n"
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
    )

    resp = client.responses.create(
        model=chat_model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return resp.output_text.strip()


def maybe_send_openbsp(
    send_url: str | None,
    api_key: str | None,
    msg: dict[str, str],
    reply_text: str,
) -> tuple[bool, int, dict[str, Any]]:
    if not send_url:
        return False, 0, {"info": "OPENBSP_SEND_URL not configured"}

    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    status, data = http_json(
        method="POST",
        url=send_url,
        headers=headers,
        body={
            "conversation_id": msg["conversation_id"],
            "contact_id": msg["contact_id"],
            "contact_address": msg["contact_address"],
            "channel": msg["channel"],
            "text": reply_text,
        },
    )
    return True, status, data


def format_whatsapp_departure_dates(reply_text: str, channel: str) -> str:
    """Render departure-date blocks as line-by-line lists for WhatsApp readability."""
    if not reply_text or channel.strip().lower() != "whatsapp":
        return reply_text

    text = reply_text
    looks_like_dates_response = (
        "|" in text
        and any(
            token in text.lower()
            for token in (
                "fechas",
                "salidas",
                "departure",
                "departures",
            )
        )
    )
    if not looks_like_dates_response:
        return reply_text

    month_pattern = re.compile(
        r"\b("
        r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre|"
        r"january|february|march|april|may|june|july|august|september|october|november|december"
        r")\s*:\s*([0-9]{1,2}(?:\s*\|\s*[0-9]{1,2})+)",
        flags=re.IGNORECASE,
    )

    def _expand_month_block(match: re.Match[str]) -> str:
        month_label = match.group(1)
        raw_days = match.group(2)
        days = [d.strip() for d in raw_days.split("|") if d.strip()]
        if len(days) < 2:
            return match.group(0)
        return "\n" + "\n".join(f"- {month_label} {day}" for day in days)

    formatted = month_pattern.sub(_expand_month_block, text)
    formatted = re.sub(r"[ \t]+\n", "\n", formatted)
    formatted = re.sub(r"\n{3,}", "\n\n", formatted)
    return formatted.strip()


def normalize_for_intent(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.lower().split())


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


def send_handoff_email(
    runtime: dict[str, Any],
    msg: dict[str, str],
    session_vars: dict[str, Any],
) -> tuple[bool, int, dict[str, Any]]:
    provider = str(runtime.get("handoff_email_provider") or "resend").strip().lower()
    from_email = runtime.get("handoff_email_from")
    to_email = runtime.get("handoff_email_to")
    if not from_email or not to_email:
        return False, 0, {"info": "handoff email not configured"}

    def sanitize_for_email(text: str) -> str:
        return text.replace("\r", "").replace("\n", " ")

    subject = f"[Acomara] Solicitud de asesor humano - {msg['conversation_id']}"
    text_body = "\n".join(
        [
            "Un cliente solicito contacto con asesor humano.",
            "",
            f"conversation_id: {sanitize_for_email(msg['conversation_id'])}",
            f"organization_id: {sanitize_for_email(msg['organization_id'])}",
            f"contact_id: {sanitize_for_email(msg['contact_id'])}",
            f"contact_address: {sanitize_for_email(msg['contact_address'])}",
            f"channel: {sanitize_for_email(msg['channel'])}",
            f"conversation_turn_count: {sanitize_for_email(str(session_vars.get('conversation_turn_count', '')))}",
            f"verified_email: {sanitize_for_email(str(session_vars.get('verified_email', '')))}",
            f"email_verified_real: {sanitize_for_email(str(session_vars.get('email_verified_real', False)))}",
            f"pause_reason: {sanitize_for_email(str(session_vars.get('pause_reason', 'human_handoff_in_progress')))}",
            "",
            f"ultimo_mensaje_cliente: {sanitize_for_email(msg['text'])}",
            f"ultimo_reply_bot: {sanitize_for_email(session_vars.get('last_assistant_reply', ''))}",
        ]
    )

    if provider == "smtp":
        smtp_host = runtime.get("handoff_smtp_host")
        smtp_port = int(runtime.get("handoff_smtp_port") or 587)
        smtp_user = runtime.get("handoff_smtp_user")
        smtp_password = runtime.get("handoff_smtp_password")
        smtp_starttls = bool(runtime.get("handoff_smtp_starttls"))
        if not smtp_host or not smtp_user or not smtp_password:
            return False, 0, {"info": "smtp handoff email not configured"}

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = from_email
        message["To"] = to_email
        message.set_content(text_body)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
            if smtp_starttls:
                smtp.starttls()
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
        return True, 200, {"ok": True, "provider": "smtp"}

    if provider != "resend":
        return False, 0, {"info": f"unsupported handoff email provider: {provider}"}

    api_key = runtime.get("handoff_email_api_key")
    if not api_key:
        return False, 0, {"info": "handoff email not configured"}

    status, data = http_json(
        method="POST",
        url="https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        body={
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "text": text_body,
        },
        timeout=20,
    )
    return True, status, data


def try_send_handoff_email(
    runtime: dict[str, Any],
    msg: dict[str, str],
    session_vars: dict[str, Any],
) -> tuple[bool, int, dict[str, Any]]:
    try:
        return send_handoff_email(runtime, msg, session_vars)
    except Exception as exc:  # pragma: no cover
        app.logger.warning("send_handoff_email exception: %s", exc)
        return True, 0, {"error": str(exc)}


def send_compromised_email_alert(
    runtime: dict[str, Any],
    msg: dict[str, str],
    email: str,
    session_vars: dict[str, Any],
) -> tuple[bool, int, dict[str, Any]]:
    """Send alert to admin when prospect's email is suspicious/unverified."""
    provider = str(runtime.get("handoff_email_provider") or "resend").strip().lower()
    from_email = runtime.get("handoff_email_from")
    to_email = runtime.get("handoff_email_to")
    if not from_email or not to_email:
        return False, 0, {"info": "alert email not configured"}

    subject = f"[ACOMARA SECURITY] Email sospechoso detectado - {msg['conversation_id']}"
    text_body = "\n".join(
        [
            "⚠️ ALERTA DE SEGURIDAD",
            "",
            "Se detectó que el email proporcionado por un prospecto NO tiene historial en bases de datos de breaches.",
            "",
            f"Email sospechoso: {email}",
            f"conversation_id: {msg['conversation_id']}",
            f"organization_id: {msg['organization_id']}",
            f"contact_id: {msg['contact_id']}",
            f"contact_address: {msg['contact_address']}",
            f"channel: {msg['channel']}",
            "",
            f"La conversación ha sido PAUSADA automáticamente.",
            f"El prospecto deberá ser contactado por un asesor humano.",
            "",
            f"Último mensaje del cliente: {msg['text']}",
        ]
    )

    if provider == "smtp":
        smtp_host = runtime.get("handoff_smtp_host")
        smtp_port = int(runtime.get("handoff_smtp_port") or 587)
        smtp_user = runtime.get("handoff_smtp_user")
        smtp_password = runtime.get("handoff_smtp_password")
        smtp_starttls = bool(runtime.get("handoff_smtp_starttls"))
        if not smtp_host or not smtp_user or not smtp_password:
            return False, 0, {"info": "smtp alert email not configured"}

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = from_email
        message["To"] = to_email
        message.set_content(text_body)

        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
            if smtp_starttls:
                smtp.starttls()
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
        return True, 200, {"ok": True, "provider": "smtp"}

    if provider != "resend":
        return False, 0, {"info": f"unsupported alert email provider: {provider}"}

    api_key = runtime.get("handoff_email_api_key")
    if not api_key:
        return False, 0, {"info": "alert email not configured"}

    status, data = http_json(
        method="POST",
        url="https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}"},
        body={
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "text": text_body,
        },
        timeout=20,
    )
    return True, status, data


def try_send_compromised_email_alert(
    runtime: dict[str, Any],
    msg: dict[str, str],
    email: str,
    session_vars: dict[str, Any],
) -> tuple[bool, int, dict[str, Any]]:
    try:
        return send_compromised_email_alert(runtime, msg, email, session_vars)
    except Exception as exc:  # pragma: no cover
        app.logger.warning("send_compromised_email_alert exception: %s", exc)
        return True, 0, {"error": str(exc)}


def try_send_suspicious_admin_alert(
    runtime: dict[str, Any],
    msg: dict[str, str],
    email: str,
    session_vars: dict[str, Any],
) -> tuple[bool, int, dict[str, Any], bool, str]:
    """Send suspicious-email admin alert with a fallback notification path.

    Returns: (attempted, status, response, sent, method)
    """
    attempted, status, data = try_send_compromised_email_alert(
        runtime,
        msg,
        email,
        session_vars,
    )
    if attempted and status in (200, 201, 202):
        return attempted, status, data, True, "security_alert"

    fallback_attempted, fallback_status, fallback_data = try_send_handoff_email(
        runtime,
        msg,
        {
            **session_vars,
            "verified_email": email,
            "email_verified_real": False,
            "pause_reason": "suspicious_email_requires_manual_validation",
        },
    )
    fallback_sent = fallback_attempted and fallback_status in (200, 201, 202)
    return (
        attempted or fallback_attempted,
        fallback_status if fallback_attempted else status,
        {
            "primary": {"attempted": attempted, "status": status, "response": data},
            "fallback": {
                "attempted": fallback_attempted,
                "status": fallback_status,
                "response": fallback_data,
            },
        },
        fallback_sent,
        "handoff_fallback",
    )


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
        "openbsp_send_url": _env("OPENBSP_SEND_URL"),
        "openbsp_api_key": _env("OPENBSP_API_KEY"),
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


def _env_bool(name: str, default: str = "false") -> bool:
    return str(_env(name, default) or default).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def build_version_payload() -> dict[str, Any]:
    commit_sha = (
        _env("VERCEL_GIT_COMMIT_SHA")
        or _env("COMMIT_SHA")
        or _env("GIT_COMMIT")
        or "unknown"
    )
    deployment = (
        _env("VERCEL_DEPLOYMENT_ID")
        or _env("VERCEL_URL")
        or _env("RENDER_SERVICE_ID")
        or "unknown"
    )
    return {
        "service": "acomara-orchestrator",
        "environment": _env("VERCEL_ENV", _env("ENV", "unknown")),
        "runtime_mode": "cloud" if is_cloud_runtime() else "local",
        "version": _env("APP_VERSION", "dev"),
        "commit": commit_sha,
        "commit_short": commit_sha[:12] if commit_sha != "unknown" else "unknown",
        "deployed_at": _env("BUILD_TIMESTAMP", "unknown"),
        "deployment": deployment,
        "python": sys.version.split(" ")[0],
        "features": {
            "email_verification_enabled": _env_bool("EMAIL_VERIFICATION_ENABLED", "true"),
            "has_hibp_api_key": bool(_env("HIBP_API_KEY")),
            "has_session_agent": bool(_env("SESSION_AGENT_BASE_URL")),
            "handoff_provider": _env("HANDOFF_EMAIL_PROVIDER", "resend"),
            "openbsp_send_configured": bool(_env("OPENBSP_SEND_URL")),
        },
    }


def build_version_text() -> str:
    payload = build_version_payload()
    features = payload["features"]
    return "\n".join(
        [
            f"Servicio: {payload['service']}",
            f"Environment: {payload['environment']}",
            f"Version: {payload['version']}",
            f"Commit: {payload['commit_short']}",
            f"Python: {payload['python']}",
            f"Email verification: {'on' if features['email_verification_enabled'] else 'off'}",
            f"HIBP key: {'configured' if features['has_hibp_api_key'] else 'missing'}",
            f"Session agent: {'configured' if features['has_session_agent'] else 'missing'}",
            f"Handoff provider: {features['handoff_provider']}",
        ]
    )


def build_paused_reply(session_vars: dict[str, Any]) -> str:
    """Build paused-conversation reply in conversation language."""
    lang = get_session_language(session_vars)
    reason = str(session_vars.get("pause_reason") or "").strip().lower()
    if reason == "human_handoff_in_progress":
        return get_phrase("paused_handoff", lang)
    if reason == "proactive_email_request":
        return get_phrase("paused_proactive_email", lang)
    return get_phrase("paused_suspicious", lang)


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
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


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
    return jsonify(
        {
            "status": "ok",
            "service": payload["service"],
            "version": payload["version"],
            "commit": payload["commit_short"],
        }
    )


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

        totals = report.get("totals", {})
        issue_counts = report.get("issue_counts", {})
        status_counts = report.get("status_counts", {})
        message_stats = report.get("message_stats", {})
        problematic = report.get("problematic_conversations", [])

        issue_rows = "".join(
                f"<tr><td>{issue}</td><td>{count}</td></tr>"
                for issue, count in sorted(issue_counts.items(), key=lambda item: item[1], reverse=True)
        )
        if not issue_rows:
                issue_rows = "<tr><td colspan='2'>No issues detected</td></tr>"

        problem_rows = "".join(
                "<tr>"
                f"<td>{row.get('conversation_id', '-')}</td>"
                f"<td>{row.get('message_count', 0)}</td>"
                f"<td>{', '.join(row.get('issues', []))}</td>"
                "</tr>"
                for row in problematic[:20]
        )
        if not problem_rows:
                problem_rows = "<tr><td colspan='3'>No problematic conversations in current window</td></tr>"

        html = f"""
<!doctype html>
<html lang='es'>
<head>
    <meta charset='utf-8' />
    <meta name='viewport' content='width=device-width, initial-scale=1' />
    <title>Acomara Audit Dashboard</title>
    <style>
        :root {{
            --bg: #f6f7f9;
            --panel: #ffffff;
            --ink: #1a2433;
            --muted: #6a7485;
            --accent: #0b6db7;
            --warn: #d9480f;
            --ok: #1b7f3b;
        }}
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif; background: radial-gradient(circle at top right, #e6f2fb 0%, var(--bg) 45%); color: var(--ink); }}
        .wrap {{ max-width: 1160px; margin: 0 auto; padding: 28px 20px 40px; }}
        h1 {{ margin: 0; font-size: 1.7rem; letter-spacing: 0.2px; }}
        .meta {{ margin-top: 6px; color: var(--muted); font-size: 0.95rem; }}
        .grid {{ margin-top: 18px; display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; }}
        .card {{ background: var(--panel); border: 1px solid #dde3ea; border-radius: 12px; padding: 14px; box-shadow: 0 4px 14px rgba(14, 33, 53, 0.05); }}
        .label {{ color: var(--muted); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em; }}
        .value {{ margin-top: 6px; font-size: 1.45rem; font-weight: 700; }}
        .value.ok {{ color: var(--ok); }}
        .value.warn {{ color: var(--warn); }}
        h2 {{ margin: 22px 0 10px; font-size: 1.05rem; }}
        table {{ width: 100%; border-collapse: collapse; background: var(--panel); border-radius: 12px; overflow: hidden; border: 1px solid #dde3ea; }}
        th, td {{ padding: 10px 12px; border-bottom: 1px solid #edf1f5; text-align: left; font-size: 0.92rem; vertical-align: top; }}
        th {{ background: #f2f7fc; color: #314257; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.04em; }}
        tr:last-child td {{ border-bottom: 0; }}
        .foot {{ margin-top: 14px; color: var(--muted); font-size: 0.85rem; }}
    </style>
</head>
<body>
    <div class='wrap'>
        <h1>Acomara Conversation Audit</h1>
        <div class='meta'>Generado: {report.get('generated_at', '-')} | Organization: {report.get('organization_id', '-')}</div>

        <div class='grid'>
            <div class='card'><div class='label'>Conversaciones auditadas</div><div class='value'>{totals.get('audited_conversations', 0)}</div></div>
            <div class='card'><div class='label'>Con problemas</div><div class='value warn'>{totals.get('conversations_with_issues', 0)}</div></div>
            <div class='card'><div class='label'>Quality rate</div><div class='value ok'>{totals.get('quality_rate_percent', 0)}%</div></div>
            <div class='card'><div class='label'>Mensajes totales</div><div class='value'>{message_stats.get('total_messages', 0)}</div></div>
            <div class='card'><div class='label'>Promedio mensajes</div><div class='value'>{message_stats.get('avg', 0)}</div></div>
            <div class='card'><div class='label'>Estado OK</div><div class='value'>{status_counts.get('OK', 0)}</div></div>
        </div>

        <h2>Problemas por tipo</h2>
        <table>
            <thead><tr><th>Tipo</th><th>Cantidad</th></tr></thead>
            <tbody>{issue_rows}</tbody>
        </table>

        <h2>Conversaciones problemáticas (top 20 por tamaño)</h2>
        <table>
            <thead><tr><th>Conversation ID</th><th>Mensajes</th><th>Issues</th></tr></thead>
            <tbody>{problem_rows}</tbody>
        </table>

        <div class='foot'>
            Query options: days_back, include_test, organization_id, api_key
        </div>
    </div>
</body>
</html>
"""
        return html


@app.get("/version")
def version() -> Any:
    payload = build_version_payload()
    safe_payload = {
        "service": payload["service"],
        "environment": payload["environment"],
        "runtime_mode": payload["runtime_mode"],
        "version": payload["version"],
        "commit": payload["commit_short"],
        "features": {
            "email_verification_enabled": payload["features"]["email_verification_enabled"],
            "has_hibp_api_key": payload["features"]["has_hibp_api_key"],
            "has_session_agent": payload["features"]["has_session_agent"],
            "handoff_provider": payload["features"]["handoff_provider"],
            "openbsp_send_configured": payload["features"]["openbsp_send_configured"],
        },
    }
    return jsonify(safe_payload)


# NOTE: legacy `/webhooks/openbsp` handler removed (2026-05-20).
# In production OpenBSP integrates via Chat Completions custom-model mode and
# only `/v1/chat/completions` receives traffic. The webhook required
# `OPENBSP_SEND_URL` (not configured) to deliver replies, so it could not work
# even if hit. Keeping a single entry point eliminates the duplicated logic
# that caused recurring email/language regressions.


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
) -> str:
    """Fix #7: prepend an out-of-season heads-up once per conversation."""
    if mentions_out_of_season(user_text) and not session_vars.get("out_of_season_warned"):
        reply = f"{get_phrase('out_of_season', lang)}\n\n{reply}"
        session_vars["out_of_season_warned"] = True
    return reply


def apply_language_commit_policy(user_text: str, session_vars: dict[str, Any]) -> None:
    """Fix #2: only commit conversation_language when the new user message
    has a confident language signal; otherwise keep the previous value.
    """
    confident_lang = detect_language_confident(user_text)
    if confident_lang and confident_lang in I18N_PHRASES:
        session_vars["conversation_language"] = confident_lang
        session_vars["conversation_language_source"] = "message_detected"
    elif not session_vars.get("conversation_language"):
        session_vars["conversation_language"] = get_session_language(session_vars, user_text)
        session_vars["conversation_language_source"] = "message_detected_low_confidence"


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
        lang = get_session_language(session_vars, msg.text)
        decision.reply = apply_email_ack_or_request_policy(
            decision.reply, session_vars, context.extracted_email, lang
        )
        decision.reply = apply_out_of_season_policy(decision.reply, msg.text, session_vars, lang)

    decision.reply = format_whatsapp_departure_dates(decision.reply, msg.channel)
    apply_language_commit_policy(msg.text, session_vars)

    updated_vars = {
        **session_vars,
        "last_user_message": msg.text,
        "last_assistant_reply": decision.reply,
        "channel": msg.channel,
        "contact_address": msg.contact_address,
        "handoff_requested": context.handoff_requested,
        "last_inbound_signature": context.inbound_signature,
        "last_inbound_signature_ts": context.now_ts,
    }

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
        reset_session_state(session_base_url, inbound_msg.as_dict(), session_agent_id)
        
        # Return success response with reset message
        reply = "Conversación reiniciada. Idioma reiniciado a español. ¿En qué te puedo ayudar?"
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
