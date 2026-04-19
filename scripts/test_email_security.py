#!/usr/bin/env python3
"""Regression tests for email verification + handoff flows.

This script validates behavior in both endpoints:
- /webhooks/openbsp
- /v1/chat/completions
"""

from __future__ import annotations

from pathlib import Path
import sys
from uuid import uuid4

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.server import app


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _print_case(title: str, response_text: str) -> None:
    print(f"\n[{title}]\n{response_text[:220]}\n")


def test_openbsp_flow() -> None:
    client = app.test_client()
    conv_id = f"reg-openbsp-{uuid4()}"
    base_payload = {
        "conversation_id": conv_id,
        "organization_id": "test-org",
        "organization_address": "test-org-address",
        "contact_id": "test-contact",
        "contact_address": "+5491111111111",
        "channel": "whatsapp",
    }

    # 1) Generic first message should ask for email eventually.
    r1 = client.post("/webhooks/openbsp", json={**base_payload, "text": "hola"})
    j1 = r1.get_json() or {}
    t1 = j1.get("reply", "")
    _print_case("openbsp turn1", t1)
    _assert(r1.status_code == 200, "openbsp turn1 should return 200")
    _assert("correo" in t1.lower(), "openbsp turn1 should request email")

    # 2) Handoff request without verified email must be blocked by email prompt.
    r2 = client.post(
        "/webhooks/openbsp",
        json={**base_payload, "text": "quiero hablar con un asesor"},
    )
    j2 = r2.get_json() or {}
    t2 = j2.get("reply", "")
    _print_case("openbsp handoff without email", t2)
    _assert("correo" in t2.lower(), "handoff must request email before escalation")

    # 3) Valid known email should allow flow to continue and handoff attempt.
    r3 = client.post(
        "/webhooks/openbsp",
        json={**base_payload, "text": "mi correo es test@example.com"},
    )
    j3 = r3.get_json() or {}
    t3 = j3.get("reply", "")
    _print_case("openbsp email provided", t3)
    email_ver = (j3.get("email_verification") or {})
    handoff = (j3.get("human_handoff_email") or {})
    _assert(email_ver.get("suspicious") is False, "known test email should not be suspicious")
    _assert(handoff.get("requested") is True, "handoff should be requested after pending + valid email")


def test_chat_completions_flow() -> None:
    client = app.test_client()
    conv_id = f"reg-chat-{uuid4()}"
    headers = {
        "Authorization": "Bearer test-orchestrator-key",
        "conversation-id": conv_id,
        "organization-id": "test-org",
        "organization-address": "test-org-address",
        "contact-id": "test-contact",
        "contact-address": "+5491111111111",
        "channel": "whatsapp",
    }

    def send(text: str) -> str:
        payload = {
            "model": "gpt-5.4",
            "messages": [{"role": "user", "content": text}],
            "stream": False,
        }
        response = client.post("/v1/chat/completions", headers=headers, json=payload)
        data = response.get_json() or {}
        content = (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        _assert(response.status_code == 200, f"chat endpoint failed for message: {text}")
        return content

    t1 = send("hola")
    _print_case("chat turn1", t1)
    _assert("correo" in t1.lower(), "chat turn1 should request email")

    t2 = send("quiero hablar con un asesor")
    _print_case("chat handoff without email", t2)
    _assert("correo" in t2.lower(), "chat handoff must request email")

    t3 = send("mi correo es test@example.com")
    _print_case("chat email provided", t3)
    _assert("asesor" in t3.lower(), "chat should proceed with human handoff after valid email")


if __name__ == "__main__":
    load_dotenv(Path(".env"))

    print("Running regression tests for email/handoff flows...")
    test_openbsp_flow()
    test_chat_completions_flow()
    print("All regression checks passed.")
