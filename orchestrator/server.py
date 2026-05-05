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

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "docs" / "knowledge" / "faq_cloud_index.jsonl"
SYSTEM_PROMPT_PATH = ROOT / "docs" / "sales-agent" / "02-system-prompt.md"

app = Flask(__name__)


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
    },
}


def detect_language_from_text(text: str) -> str:
    """Simple language detection from message content.

    Looks for common keywords in Spanish, Portuguese, and English.
    Returns detected language code (es/pt/en) or 'es' as conservative default.
    """
    text_lower = text.lower()
    normalized_text = unicodedata.normalize("NFKD", text_lower)
    normalized_text = normalized_text.encode("ascii", "ignore").decode("ascii")

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


def get_session_language(session_vars: dict[str, Any] | None, fallback_text: str = "") -> str:
    """Get conversation language from session variables. Default: Spanish.

    Reads conversation_language field set by session agent.
    Falls back to language detection from message text if not set.
    Falls back to 'es' if detection fails.
    """
    if not session_vars or not isinstance(session_vars, dict):
        if fallback_text:
            return detect_language_from_text(fallback_text)
        return "es"
    lang = session_vars.get("conversation_language", "").strip().lower()
    if lang in I18N_PHRASES:
        return lang
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
        "- NO hagas preguntas de cierre ni acciones siguientes que no vengan del FAQ.\n"
        "- Si no hay evidencia suficiente, di claramente que esa información no está en la documentación."
    ).format(
        channel=msg["channel"],
        conversation_id=msg["conversation_id"],
        question=msg["text"],
        session_vars=json.dumps(session_vars, ensure_ascii=False),
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


@app.post("/webhooks/openbsp")
def webhook_openbsp() -> Any:
    payload = request.get_json(silent=True) or {}
    msg = normalize_inbound(payload)

    if not msg["text"]:
        return jsonify({"error": "Could not extract inbound message text"}), 400

    command = extract_command(msg["text"])

    # /reset is the canonical reset command. /new remains as backward-compatible alias.
    if command in ("/reset", "/new"):
        session_base_url = _env("SESSION_AGENT_BASE_URL")
        session_agent_id = _env("SESSION_AGENT_ID", "sales-agent-v1") or "sales-agent-v1"
        reset_session_state(session_base_url, msg, session_agent_id)
        return jsonify(
            {
                "ok": True,
                "conversation_id": msg["conversation_id"],
                "contact_id": msg["contact_id"],
                "reply": "Conversación reiniciada. Idioma reiniciado a español. ¿En qué te puedo ayudar?",
                "sources": [],
                "openbsp_send": {"attempted": False, "status": 0, "response": {"info": "command"}},
                "human_handoff_email": {
                    "requested": False,
                    "attempted": False,
                    "sent": False,
                    "status": 0,
                    "response": {"info": "command"},
                },
                "email_verification": {
                    "enabled": True,
                    "suspicious": False,
                    "alert_sent": False,
                    "conversation_paused": False,
                },
            }
        )
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
                return jsonify(
                    {
                        "ok": True,
                        "conversation_id": msg["conversation_id"],
                        "contact_id": msg["contact_id"],
                        "reply": replay_reply,
                        "sources": [],
                        "deduplicated": True,
                        "openbsp_send": {
                            "attempted": False,
                            "status": 0,
                            "response": {"info": "duplicate_inbound"},
                        },
                    }
                )

        if command == "/version":
            if not _env_bool("ENABLE_PUBLIC_VERSION_COMMAND", "false"):
                return jsonify(
                    {
                        "ok": True,
                        "conversation_id": msg["conversation_id"],
                        "contact_id": msg["contact_id"],
                        "reply": "Comando no disponible en este canal.",
                        "sources": [],
                        "openbsp_send": {
                            "attempted": False,
                            "status": 0,
                            "response": {"info": "command_disabled"},
                        },
                    }
                )
            detected_lang = get_session_language(session_vars, msg["text"])
            version_text = build_version_text()
            client_status_text = ""
            if session_vars.get("crm_client_found"):
                client_status = "✅ CONTACTED" if session_vars.get("crm_client_contacted") else "👤 NEW CLIENT"
                client_status_text = f"\nCRM Client: {client_status} ({session_vars.get('crm_client_name', 'Unknown')})"
            else:
                client_status_text = "\nCRM Client: Not found in system"

            version_with_lang = f"{version_text}{client_status_text}\nConversation Language: {detected_lang}\nDetected from: {get_language_source(session_vars)}"
            return jsonify(
                {
                    "ok": True,
                    "conversation_id": msg["conversation_id"],
                    "contact_id": msg["contact_id"],
                    "reply": version_with_lang,
                    "sources": [],
                    "openbsp_send": {"attempted": False, "status": 0, "response": {"info": "command"}},
                    "human_handoff_email": {
                        "requested": False,
                        "attempted": False,
                        "sent": False,
                        "status": 0,
                        "response": {"info": "command"},
                    },
                    "email_verification": {
                        "enabled": True,
                        "suspicious": False,
                        "alert_sent": False,
                        "conversation_paused": False,
                    },
                    "crm_client": {
                        "found": session_vars.get("crm_client_found", False),
                        "contacted": session_vars.get("crm_client_contacted", False),
                        "name": session_vars.get("crm_client_name"),
                        "search_method": session_vars.get("crm_search_method"),
                    },
                }
            )

        # Increment conversation turn counter
        current_turn = session_vars.get("conversation_turn_count", 0)
        session_vars["conversation_turn_count"] = current_turn + 1

        # Ensure the session exists in the store before appending events.
        # For new conversations (404 on GET) this creates the session record.
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

        # Check CRM client status by phone (from contact_address) first, fallback to email
        phone = msg.get("contact_address", "").strip()
        print(f"[SERVER_DEBUG] Checking CRM for phone={phone}")
        if phone:  # Only check if we have a phone number
            extracted_email_temp = extract_email_from_text(msg["text"])
            print(f"[SERVER_DEBUG] Calling check_client_status with phone={phone}, email={extracted_email_temp}")
            crm_status = check_client_status(phone=phone, email=extracted_email_temp)
            print(f"[SERVER_DEBUG] CRM Status result: {crm_status}")
            session_vars["crm_client_found"] = crm_status.get("found", False)
            session_vars["crm_client_contacted"] = crm_status.get("contacted", False)
            session_vars["crm_client_id"] = crm_status.get("client_id")
            session_vars["crm_client_name"] = crm_status.get("client_name")
            session_vars["crm_consultation_count"] = crm_status.get("consultation_count", 0)
            session_vars["crm_last_consultation_date"] = crm_status.get("last_consultation_date")
            session_vars["crm_search_method"] = crm_status.get("search_by")
        else:
            print(f"[SERVER_DEBUG] No phone number in contact_address, skipping CRM check")

        # Email verification logic
        email_verification_enabled = runtime.get("email_verification_enabled", True)
        email_suspicious = False
        email_suspicious_alert_sent = False
        suspicious_email_value = ""
        extracted_email = extract_email_from_text(msg["text"])
        conversation_paused = bool(session_vars.get("conversation_paused"))

        # Check CRM client status if we have an email
        if extracted_email and not session_vars.get("crm_client_found"):
            crm_status = check_client_status(email=extracted_email)
            session_vars["crm_client_found"] = crm_status.get("found", False)
            session_vars["crm_client_contacted"] = crm_status.get("contacted", False)
            session_vars["crm_client_id"] = crm_status.get("client_id")
            session_vars["crm_client_name"] = crm_status.get("client_name")
            session_vars["crm_consultation_count"] = crm_status.get("consultation_count", 0)
            session_vars["crm_last_consultation_date"] = crm_status.get("last_consultation_date")

        if email_verification_enabled and not conversation_paused:
            if extracted_email and not session_vars.get("email_verified"):
                # Check email reputation against Have I Been Pwned
                is_suspicious, check_succeeded = check_email_reputation(
                    extracted_email,
                    runtime.get("hibp_api_key") or "",
                    timeout=runtime.get("hibp_timeout_seconds", 10),
                )
                
                if check_succeeded:
                    session_vars["email_verified"] = True
                    session_vars["verified_email"] = extracted_email
                    session_vars["email_checked_at_ts"] = int(time.time())
                    
                    if is_suspicious:
                        # Email is suspicious (new/unverified) - pause conversation
                        email_suspicious = True
                        suspicious_email_value = extracted_email
                        session_vars = pause_conversation(
                            session_vars,
                            extracted_email,
                            "Email appears to be unverified or new, requires manual validation",
                        )
                        
                        # Send alert to admin once when suspicious email is detected.
                        if not session_vars.get("suspicious_email_alert_sent"):
                            alert_attempted, alert_status, alert_data, alert_sent, alert_method = try_send_suspicious_admin_alert(
                                runtime,
                                msg,
                                extracted_email,
                                session_vars,
                            )
                            email_suspicious_alert_sent = alert_sent
                            if alert_attempted:
                                session_vars["suspicious_email_alert_last_status"] = alert_status
                                session_vars["suspicious_email_alert_method"] = alert_method
                                session_vars["suspicious_email_alert_last_response"] = alert_data
                        
                        if email_suspicious_alert_sent:
                            session_vars["suspicious_email_alert_sent_ts"] = int(time.time())
                    else:
                        # Email is verified (has real history)
                        session_vars["email_verified_real"] = True
                else:
                    # Check failed (likely API error or rate limit)
                    session_vars["email_check_failed"] = True
                    session_vars["email_check_failed_at_ts"] = int(time.time())

        now_ts = int(time.time())
        proactive_email_capture_pending = bool(session_vars.get("proactive_email_capture_pending"))
        proactive_email_verified = (
            bool(extracted_email)
            and proactive_email_capture_pending
            and not bool(session_vars.get("handoff_pending_confirmation"))
            and bool(session_vars.get("email_verified_real"))
        )
        proactive_email_check_failed = (
            bool(extracted_email)
            and proactive_email_capture_pending
            and not bool(session_vars.get("handoff_pending_confirmation"))
            and bool(session_vars.get("email_check_failed"))
            and not email_suspicious
        )

        # --- HANDOFF DETECTION (before LLM) ---
        # Detect explicit handoff requests. Affirmative detection was removed to
        # avoid false positives when the LLM casually mentions "asesor".
        handoff_requested = wants_human_handoff(msg["text"], session_vars)
        # If user already triggered handoff and email was just verified, proceed.
        if (
            not handoff_requested
            and session_vars.get("handoff_pending_confirmation")
            and session_vars.get("email_verified_real")
        ):
            handoff_requested = True

        handoff_attempted = False
        handoff_status = 0
        handoff_data: dict[str, Any] = {}
        handoff_sent = False

        if session_vars.get("conversation_paused"):
            # Conversation already paused – deterministic reply, skip LLM.
            reply = build_paused_reply(session_vars)
            hits = []
        elif handoff_requested and not session_vars.get("email_verified_real"):
            # Need email before executing handoff.
            lang = get_session_language(session_vars, msg.get("text", ""))
            reply = get_phrase("handoff_ask_email", lang)
            session_vars["handoff_pending_confirmation"] = True
            session_vars["email_requested"] = True
            handoff_data = {"info": "handoff pending email verification"}
            hits = []
        elif handoff_requested:
            # Email already verified – execute handoff immediately, skip LLM.
            lang = get_session_language(session_vars, msg.get("text", ""))
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
            else:
                handoff_data = {"info": "handoff email skipped by cooldown"}
            # Deterministic reply regardless of whether the email succeeded.
            reply = get_phrase("handoff_executed", lang)
            session_vars["conversation_paused"] = True
            session_vars["pause_reason"] = "human_handoff_in_progress"
            session_vars["handoff_pending_confirmation"] = False
            session_vars["paused_at_ts"] = now_ts
            handoff_sent = cooldown_ok and handoff_attempted and handoff_status in (200, 201, 202)
            hits = []
        elif proactive_email_verified:
            lang = get_session_language(session_vars, msg.get("text", ""))
            reply = get_phrase("proactive_email_saved", lang)
            session_vars["proactive_email_capture_pending"] = False
            session_vars["email_requested"] = False
            session_vars["conversation_paused"] = False
            hits = []
        elif proactive_email_check_failed:
            lang = get_session_language(session_vars, msg.get("text", ""))
            reply = get_phrase("proactive_email_check_failed", lang)
            session_vars["proactive_email_capture_pending"] = False
            session_vars["email_requested"] = False
            hits = []
        elif session_vars.get("handoff_pending_confirmation"):
            # Handoff was requested earlier but user didn't provide email yet.
            lang = get_session_language(session_vars, msg.get("text", ""))
            reply = get_phrase("handoff_pending", lang)
            hits = []
        elif session_vars.get("conversation_paused"):
            # Conversation paused for other reasons (e.g., suspicious email)
            reply = build_paused_reply(session_vars)
            hits = []
        else:
            # Normal LLM path.
            hits = retrieve_top_k(
                client,
                runtime["embed_model"],
                runtime["rows"],
                msg["text"],
                runtime["top_k"],
            )
            reply = generate_reply(
                client,
                runtime["chat_model"],
                runtime["system_prompt"],
                msg,
                hits,
                session_vars,
            )
            if should_request_email(session_vars):
                lang = get_session_language(session_vars, msg.get("text", ""))
                reply = f"{reply}\n\n{get_phrase('proactive_email_request', lang)}"
                session_vars["email_requested"] = True
                session_vars["proactive_email_capture_pending"] = True

        # Update conversation_language based on detected language from current message
        detected_lang = get_session_language(session_vars, msg["text"])
        session_vars["conversation_language"] = detected_lang
        session_vars["conversation_language_source"] = "message_detected"

        updated_vars = {
            **session_vars,
            "last_user_message": msg["text"],
            "last_assistant_reply": reply,
            "channel": msg["channel"],
            "contact_address": msg["contact_address"],
            "handoff_requested": handoff_requested,
            "last_inbound_signature": inbound_signature,
            "last_inbound_signature_ts": now_ts,
        }
        if handoff_sent:
            updated_vars["handoff_email_last_sent_ts"] = now_ts
            updated_vars["handoff_email_last_to"] = runtime.get("handoff_email_to")
            updated_vars["handoff_pending_confirmation"] = False
        
        if email_suspicious:
            updated_vars["email_suspicious"] = True
            updated_vars["suspicious_email"] = suspicious_email_value
        
        if email_suspicious_alert_sent:
            updated_vars["suspicious_email_alert_sent"] = True
            updated_vars["suspicious_email_alert_sent_ts"] = now_ts

        try_session_upsert(
            session_base_url,
            msg,
            runtime["session_agent_id"],
            updated_vars,
        )
        if handoff_sent:
            try_session_append_event(
                session_base_url,
                msg["conversation_id"],
                "handoff_email",
                {
                    "to": runtime.get("handoff_email_to"),
                    "status": handoff_status,
                    "provider": runtime.get("handoff_email_provider"),
                },
            )
        
        if email_suspicious_alert_sent:
            try_session_append_event(
                session_base_url,
                msg["conversation_id"],
                "suspicious_email_alert",
                {
                    "email": suspicious_email_value,
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
                "text": reply,
                "source": "acomara-orchestrator",
            },
        )

        sent, send_status, send_data = maybe_send_openbsp(
            runtime["openbsp_send_url"],
            runtime["openbsp_api_key"],
            msg,
            reply,
        )

        return jsonify(
            {
                "ok": True,
                "conversation_id": msg["conversation_id"],
                "contact_id": msg["contact_id"],
                "reply": reply,
                "sources": [
                    {
                        "id": h["id"],
                        "topic": h.get("topic", "general"),
                        "score": round(float(h["score"]), 4),
                    }
                    for h in hits
                ],
                "openbsp_send": {
                    "attempted": sent,
                    "status": send_status,
                    "response": send_data,
                },
                "human_handoff_email": {
                    "requested": handoff_requested,
                    "attempted": handoff_attempted,
                    "sent": handoff_sent,
                    "status": handoff_status,
                    "response": handoff_data,
                },
                "email_verification": {
                    "enabled": email_verification_enabled,
                    "suspicious": email_suspicious,
                    "alert_sent": email_suspicious_alert_sent,
                    "conversation_paused": bool(session_vars.get("conversation_paused", False)),
                },
            }
        )
    except Exception as exc:  # pragma: no cover
        return jsonify({"ok": False, "error": str(exc)}), 500


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
    if stream is True:
        return (
            jsonify(
                {
                    "error": {
                        "message": "Streaming is not supported in this endpoint.",
                        "type": "invalid_request_error",
                    }
                }
            ),
            400,
        )

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
    command = extract_command(user_text)
    if command in ("/reset", "/new"):
        session_base_url = _env("SESSION_AGENT_BASE_URL")
        session_agent_id = _env("SESSION_AGENT_ID", "sales-agent-v1") or "sales-agent-v1"
        command_msg = {
            "text": user_text,
            "conversation_id": headers_dict["conversation_id"],
            "organization_id": headers_dict["organization_id"],
            "organization_address": headers_dict["organization_address"],
            "contact_id": headers_dict["contact_id"],
            "contact_address": headers_dict["contact_address"],
            "channel": headers_dict["channel"],
        }
        reset_session_state(session_base_url, command_msg, session_agent_id)
        
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
    msg = {
        "text": user_text,
        "conversation_id": headers_dict["conversation_id"],
        "organization_id": headers_dict["organization_id"],
        "organization_address": headers_dict["organization_address"],
        "contact_id": headers_dict["contact_id"],
        "contact_address": headers_dict["contact_address"],
        "channel": headers_dict["channel"],
    }

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

        # Check CRM client status by phone (from contact_address) first, fallback to email
        phone = msg.get("contact_address", "").strip()
        print(f"[SERVER_DEBUG] Checking CRM for phone={phone}")
        if phone:  # Only check if we have a phone number
            extracted_email_temp = extract_email_from_text(msg["text"])
            print(f"[SERVER_DEBUG] Calling check_client_status with phone={phone}, email={extracted_email_temp}")
            crm_status = check_client_status(phone=phone, email=extracted_email_temp)
            print(f"[SERVER_DEBUG] CRM Status result: {crm_status}")
            session_vars["crm_client_found"] = crm_status.get("found", False)
            session_vars["crm_client_contacted"] = crm_status.get("contacted", False)
            session_vars["crm_client_id"] = crm_status.get("client_id")
            session_vars["crm_client_name"] = crm_status.get("client_name")
            session_vars["crm_consultation_count"] = crm_status.get("consultation_count", 0)
            session_vars["crm_last_consultation_date"] = crm_status.get("last_consultation_date")
            session_vars["crm_search_method"] = crm_status.get("search_by")
        else:
            print(f"[SERVER_DEBUG] No phone number in contact_address, skipping CRM check")

        # Email verification logic
        email_verification_enabled = runtime.get("email_verification_enabled", True)
        email_suspicious = False
        email_suspicious_alert_sent = False
        suspicious_email_value = ""
        extracted_email = extract_email_from_text(msg["text"])
        conversation_paused = bool(session_vars.get("conversation_paused"))

        # Check CRM client status if we have an email
        if extracted_email and not session_vars.get("crm_client_found"):
            crm_status = check_client_status(email=extracted_email)
            session_vars["crm_client_found"] = crm_status.get("found", False)
            session_vars["crm_client_contacted"] = crm_status.get("contacted", False)
            session_vars["crm_client_id"] = crm_status.get("client_id")
            session_vars["crm_client_name"] = crm_status.get("client_name")
            session_vars["crm_consultation_count"] = crm_status.get("consultation_count", 0)
            session_vars["crm_last_consultation_date"] = crm_status.get("last_consultation_date")

        if email_verification_enabled and not conversation_paused:
            if extracted_email and not session_vars.get("email_verified"):
                is_suspicious, check_succeeded = check_email_reputation(
                    extracted_email,
                    runtime.get("hibp_api_key") or "",
                    timeout=runtime.get("hibp_timeout_seconds", 10),
                )

                if check_succeeded:
                    session_vars["email_verified"] = True
                    session_vars["verified_email"] = extracted_email
                    session_vars["email_checked_at_ts"] = int(time.time())

                    if is_suspicious:
                        email_suspicious = True
                        suspicious_email_value = extracted_email
                        session_vars = pause_conversation(
                            session_vars,
                            extracted_email,
                            "Email appears to be unverified or new, requires manual validation",
                        )

                        if not session_vars.get("suspicious_email_alert_sent"):
                            alert_attempted, alert_status, alert_data, alert_sent, alert_method = try_send_suspicious_admin_alert(
                                runtime,
                                msg,
                                extracted_email,
                                session_vars,
                            )
                            email_suspicious_alert_sent = alert_sent
                            if alert_attempted:
                                session_vars["suspicious_email_alert_last_status"] = alert_status
                                session_vars["suspicious_email_alert_method"] = alert_method
                                session_vars["suspicious_email_alert_last_response"] = alert_data

                        if email_suspicious_alert_sent:
                            session_vars["suspicious_email_alert_sent_ts"] = int(time.time())
                    else:
                        session_vars["email_verified_real"] = True
                else:
                    session_vars["email_check_failed"] = True
                    session_vars["email_check_failed_at_ts"] = int(time.time())

        now_ts = int(time.time())
        proactive_email_capture_pending = bool(session_vars.get("proactive_email_capture_pending"))
        proactive_email_verified = (
            bool(extracted_email)
            and proactive_email_capture_pending
            and not bool(session_vars.get("handoff_pending_confirmation"))
            and bool(session_vars.get("email_verified_real"))
        )
        proactive_email_check_failed = (
            bool(extracted_email)
            and proactive_email_capture_pending
            and not bool(session_vars.get("handoff_pending_confirmation"))
            and bool(session_vars.get("email_check_failed"))
            and not email_suspicious
        )

        # --- HANDOFF DETECTION (before LLM) ---
        handoff_requested = wants_human_handoff(msg["text"], session_vars)
        if (
            not handoff_requested
            and session_vars.get("handoff_pending_confirmation")
            and session_vars.get("email_verified_real")
        ):
            handoff_requested = True

        handoff_attempted = False
        handoff_status = 0
        handoff_data: dict[str, Any] = {}
        handoff_sent = False

        if session_vars.get("conversation_paused"):
            reply = build_paused_reply(session_vars)
            hits = []
        elif handoff_requested and not session_vars.get("email_verified_real"):
            lang = get_session_language(session_vars, msg.get("text", ""))
            reply = get_phrase("handoff_ask_email", lang)
            session_vars["handoff_pending_confirmation"] = True
            session_vars["email_requested"] = True
            handoff_data = {"info": "handoff pending email verification"}
            hits = []
        elif handoff_requested:
            lang = get_session_language(session_vars, msg.get("text", ""))
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
            else:
                handoff_data = {"info": "handoff email skipped by cooldown"}
            reply = get_phrase("handoff_executed", lang)
            session_vars["conversation_paused"] = True
            session_vars["pause_reason"] = "human_handoff_in_progress"
            session_vars["handoff_pending_confirmation"] = False
            session_vars["paused_at_ts"] = now_ts
            handoff_sent = cooldown_ok and handoff_attempted and handoff_status in (200, 201, 202)
            hits = []
        elif proactive_email_verified:
            lang = get_session_language(session_vars, msg.get("text", ""))
            reply = get_phrase("proactive_email_saved", lang)
            session_vars["proactive_email_capture_pending"] = False
            session_vars["email_requested"] = False
            session_vars["conversation_paused"] = False
            hits = []
        elif proactive_email_check_failed:
            lang = get_session_language(session_vars, msg.get("text", ""))
            reply = get_phrase("proactive_email_check_failed", lang)
            session_vars["proactive_email_capture_pending"] = False
            session_vars["email_requested"] = False
            hits = []
        elif session_vars.get("handoff_pending_confirmation"):
            lang = get_session_language(session_vars, msg.get("text", ""))
            reply = get_phrase("handoff_pending", lang)
            hits = []
        elif session_vars.get("conversation_paused"):
            # Conversation paused for other reasons (e.g., suspicious email)
            reply = build_paused_reply(session_vars)
            hits = []
        else:
            hits = retrieve_top_k(
                client,
                runtime["embed_model"],
                runtime["rows"],
                msg["text"],
                runtime["top_k"],
            )
            reply = generate_reply(
                client,
                runtime["chat_model"],
                runtime["system_prompt"],
                msg,
                hits,
                session_vars,
            )
            if should_request_email(session_vars):
                lang = get_session_language(session_vars, msg.get("text", ""))
                reply = f"{reply}\n\n{get_phrase('proactive_email_request', lang)}"
                session_vars["email_requested"] = True
                session_vars["proactive_email_capture_pending"] = True

        # Update conversation_language based on detected language from current message
        detected_lang = get_session_language(session_vars, msg["text"])
        session_vars["conversation_language"] = detected_lang
        session_vars["conversation_language_source"] = "message_detected"

        updated_vars = {
            **session_vars,
            "last_user_message": msg["text"],
            "last_assistant_reply": reply,
            "channel": msg["channel"],
            "contact_address": msg["contact_address"],
            "handoff_requested": handoff_requested,
            "last_inbound_signature": inbound_signature,
            "last_inbound_signature_ts": now_ts,
        }
        if handoff_sent:
            updated_vars["handoff_email_last_sent_ts"] = now_ts
            updated_vars["handoff_email_last_to"] = runtime.get("handoff_email_to")
            updated_vars["handoff_pending_confirmation"] = False

        if email_suspicious:
            updated_vars["email_suspicious"] = True
            updated_vars["suspicious_email"] = suspicious_email_value

        if email_suspicious_alert_sent:
            updated_vars["suspicious_email_alert_sent"] = True
            updated_vars["suspicious_email_alert_sent_ts"] = now_ts

        try_session_upsert(
            session_base_url,
            msg,
            runtime["session_agent_id"],
            updated_vars,
        )
        if handoff_sent:
            try_session_append_event(
                session_base_url,
                msg["conversation_id"],
                "handoff_email",
                {
                    "to": runtime.get("handoff_email_to"),
                    "status": handoff_status,
                    "provider": runtime.get("handoff_email_provider"),
                    "response": handoff_data,
                },
            )
        if email_suspicious_alert_sent:
            try_session_append_event(
                session_base_url,
                msg["conversation_id"],
                "suspicious_email_alert",
                {
                    "email": suspicious_email_value,
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
                "text": reply,
                "source": "acomara-orchestrator-chat-completions",
                "faq_sources": [h["id"] for h in hits],
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
