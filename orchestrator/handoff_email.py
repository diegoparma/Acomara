from __future__ import annotations

import json
import logging
import smtplib
from email.message import EmailMessage
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

LOGGER = logging.getLogger(__name__)


def _http_json(
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

    status, data = _http_json(
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
        LOGGER.warning("send_handoff_email exception: %s", exc)
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
            "Se detecto que el email proporcionado por un prospecto NO tiene historial en bases de datos de breaches.",
            "",
            f"Email sospechoso: {email}",
            f"conversation_id: {msg['conversation_id']}",
            f"organization_id: {msg['organization_id']}",
            f"contact_id: {msg['contact_id']}",
            f"contact_address: {msg['contact_address']}",
            f"channel: {msg['channel']}",
            "",
            "La conversacion ha sido PAUSADA automaticamente.",
            "El prospecto debera ser contactado por un asesor humano.",
            "",
            f"Ultimo mensaje del cliente: {msg['text']}",
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

    status, data = _http_json(
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
        LOGGER.warning("send_compromised_email_alert exception: %s", exc)
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
