from __future__ import annotations

from typing import Any


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
