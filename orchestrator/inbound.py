from __future__ import annotations

from typing import Any


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
