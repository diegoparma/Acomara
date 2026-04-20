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

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "docs" / "knowledge" / "faq_cloud_index.jsonl"
SYSTEM_PROMPT_PATH = ROOT / "docs" / "sales-agent" / "02-system-prompt.md"

app = Flask(__name__)


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
    user_prompt = (
        "Canal: {channel}\n"
        "Conversation ID: {conversation_id}\n"
        "Cliente pregunta:\n{question}\n\n"
        "Variables de sesion actuales:\n{session_vars}\n\n"
        "Evidencia interna recuperada:\n{context}\n\n"
        "Instrucciones:\n"
        "- Responde SOLO con datos respaldados por evidencia recuperada.\n"
        "- Si falta informacion, dilo y ofrece pasar a asesor humano.\n"
        "- Cierra con una sola accion siguiente concreta.\n"
        "- Se muy breve: maximo 3 bullets o 4 lineas cortas.\n"
        "- Limita la respuesta a ~450 caracteres, salvo que el usuario pida detalle.\n"
        "- Haz como maximo 1 pregunta final opcional.\n"
        "- Responde exactamente en el mismo idioma del ultimo mensaje del usuario, sin mezclar idiomas.\n"
        "- Mantiene tono comercial profesional y claro."
    ).format(
        channel=msg["channel"],
        conversation_id=msg["conversation_id"],
        question=msg["text"],
        session_vars=json.dumps(session_vars, ensure_ascii=False),
        context=context,
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
            "session_agent_base_url": _env("SESSION_AGENT_BASE_URL"),
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
            f"Deployment: {payload['deployment']}",
            f"Python: {payload['python']}",
            f"Email verification: {'on' if features['email_verification_enabled'] else 'off'}",
            f"HIBP key: {'configured' if features['has_hibp_api_key'] else 'missing'}",
            f"Session agent: {features['session_agent_base_url'] or 'missing'}",
            f"Handoff provider: {features['handoff_provider']}",
        ]
    )


def build_paused_reply(session_vars: dict[str, Any]) -> str:
    reason = str(session_vars.get("pause_reason") or "").strip().lower()
    if reason == "human_handoff_in_progress":
        return (
            "Tu solicitud ya fue derivada a un asesor humano. "
            "En breve te va a contactar un miembro del equipo por este medio."
        )
    return (
        "Thank you for your interest. We detected a security concern with your email. "
        "A member of our team will contact you shortly to verify your information and proceed safely."
    )


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
    return jsonify(build_version_payload())


@app.post("/webhooks/openbsp")
def webhook_openbsp() -> Any:
    payload = request.get_json(silent=True) or {}
    msg = normalize_inbound(payload)

    if not msg["text"]:
        return jsonify({"error": "Could not extract inbound message text"}), 400

    text_lower = msg["text"].strip().lower()
    
    # Commands are case-insensitive and can have trailing text
    if text_lower.startswith("/new"):
        session_base_url = _env("SESSION_AGENT_BASE_URL")
        try_session_delete(session_base_url, msg["conversation_id"])
        return jsonify(
            {
                "ok": True,
                "conversation_id": msg["conversation_id"],
                "contact_id": msg["contact_id"],
                "reply": "Conversación reiniciada. ¿En qué te puedo ayudar?",
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
    if text_lower.startswith("/version"):
        return jsonify(
            {
                "ok": True,
                "conversation_id": msg["conversation_id"],
                "contact_id": msg["contact_id"],
                "reply": build_version_text(),
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

        # Email verification logic
        email_verification_enabled = runtime.get("email_verification_enabled", True)
        email_suspicious = False
        email_suspicious_alert_sent = False
        suspicious_email_value = ""
        extracted_email = extract_email_from_text(msg["text"])
        conversation_paused = bool(session_vars.get("conversation_paused"))
        
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
                            alert_attempted, alert_status, alert_data = try_send_compromised_email_alert(
                                runtime,
                                msg,
                                extracted_email,
                                session_vars,
                            )
                            email_suspicious_alert_sent = (
                                alert_attempted and alert_status in (200, 201, 202)
                            )
                        
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
            reply = (
                "Para conectarte con un asesor, primero necesito tu correo electrónico "
                "para poder derivarte correctamente. ¿Cuál es tu correo?"
            )
            session_vars["handoff_pending_confirmation"] = True
            session_vars["email_requested"] = True
            handoff_data = {"info": "handoff pending email verification"}
            hits = []
        elif handoff_requested:
            # Email already verified – execute handoff immediately, skip LLM.
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
            reply = (
                "Perfecto, ya derivé tu solicitud a un asesor humano. "
                "En breve te va a contactar un miembro del equipo por este medio."
            )
            session_vars["conversation_paused"] = True
            session_vars["pause_reason"] = "human_handoff_in_progress"
            session_vars["handoff_pending_confirmation"] = False
            session_vars["paused_at_ts"] = now_ts
            handoff_sent = cooldown_ok and handoff_attempted and handoff_status in (200, 201, 202)
            hits = []
        elif session_vars.get("handoff_pending_confirmation"):
            # Handoff was requested earlier but user didn't provide email yet.
            reply = (
                "Todavía necesito tu correo electrónico para derivarte con el asesor. "
                "¿Cuál es tu correo?"
            )
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

        updated_vars = {
            **session_vars,
            "last_user_message": msg["text"],
            "last_assistant_reply": reply,
            "channel": msg["channel"],
            "contact_address": msg["contact_address"],
            "handoff_requested": handoff_requested,
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

    # Handle commands (case-insensitive, allow trailing text)
    text_lower = user_text.strip().lower()
    if text_lower.startswith("/new"):
        headers = request.headers
        conversation_id = headers.get("conversation-id", "openbsp-conversation")
        session_base_url = _env("SESSION_AGENT_BASE_URL")
        try_session_delete(session_base_url, conversation_id)
        
        # Return success response with reset message
        reply = "Conversación reiniciada. ¿En qué te puedo ayudar?"
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
    if text_lower.startswith("/version"):
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

    headers_dict = validate_and_normalize_headers(request.headers)
    msg = {
        "text": user_text,
        "conversation_id": headers_dict["conversation_id"],
        "organization_id": headers_dict["organization_id"],
        "organization_address": headers_dict["organization_address"],
        "contact_id": headers_dict["contact_id"],
        "contact_address": headers_dict["contact_address"],
        "channel": headers_dict["channel"],
    }

    try:
        runtime = ensure_runtime()
        client = OpenAI(api_key=runtime["api_key"])

        session_vars: dict[str, Any] = {}
        session_base_url = runtime["session_base_url"]
        snapshot = try_session_get(session_base_url, msg["conversation_id"])
        if snapshot and isinstance(snapshot.get("variables"), dict):
            session_vars = snapshot["variables"]

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

        # Email verification logic
        email_verification_enabled = runtime.get("email_verification_enabled", True)
        email_suspicious = False
        email_suspicious_alert_sent = False
        suspicious_email_value = ""
        extracted_email = extract_email_from_text(msg["text"])
        conversation_paused = bool(session_vars.get("conversation_paused"))

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
                            alert_attempted, alert_status, alert_data = try_send_compromised_email_alert(
                                runtime,
                                msg,
                                extracted_email,
                                session_vars,
                            )
                            email_suspicious_alert_sent = (
                                alert_attempted and alert_status in (200, 201, 202)
                            )

                        if email_suspicious_alert_sent:
                            session_vars["suspicious_email_alert_sent_ts"] = int(time.time())
                    else:
                        session_vars["email_verified_real"] = True
                else:
                    session_vars["email_check_failed"] = True
                    session_vars["email_check_failed_at_ts"] = int(time.time())

        now_ts = int(time.time())

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
            reply = (
                "Para conectarte con un asesor, primero necesito tu correo electrónico "
                "para poder derivarte correctamente. ¿Cuál es tu correo?"
            )
            session_vars["handoff_pending_confirmation"] = True
            session_vars["email_requested"] = True
            handoff_data = {"info": "handoff pending email verification"}
            hits = []
        elif handoff_requested:
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
            reply = (
                "Perfecto, ya derivé tu solicitud a un asesor humano. "
                "En breve te va a contactar un miembro del equipo por este medio."
            )
            session_vars["conversation_paused"] = True
            session_vars["pause_reason"] = "human_handoff_in_progress"
            session_vars["handoff_pending_confirmation"] = False
            session_vars["paused_at_ts"] = now_ts
            handoff_sent = cooldown_ok and handoff_attempted and handoff_status in (200, 201, 202)
            hits = []
        elif session_vars.get("handoff_pending_confirmation"):
            reply = (
                "Todavía necesito tu correo electrónico para derivarte con el asesor. "
                "¿Cuál es tu correo?"
            )
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

        updated_vars = {
            **session_vars,
            "last_user_message": msg["text"],
            "last_assistant_reply": reply,
            "channel": msg["channel"],
            "contact_address": msg["contact_address"],
            "handoff_requested": handoff_requested,
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
