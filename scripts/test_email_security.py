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

    # 1) Generic flow should request email around turns 3-4.
    r1 = client.post("/webhooks/openbsp", json={**base_payload, "text": "hola"})
    j1 = r1.get_json() or {}
    t1 = j1.get("reply", "")
    _print_case("openbsp turn1", t1)
    _assert(r1.status_code == 200, "openbsp turn1 should return 200")

    r1b = client.post("/webhooks/openbsp", json={**base_payload, "text": "contame del equipo"})
    t1b = (r1b.get_json() or {}).get("reply", "")
    _print_case("openbsp turn2", t1b)

    r1c = client.post("/webhooks/openbsp", json={**base_payload, "text": "y la logistica?"})
    t1c = (r1c.get_json() or {}).get("reply", "")
    _print_case("openbsp turn3", t1c)
    _assert("correo" in t1c.lower(), "openbsp turn3 should request email")

    # 2) Handoff request – executed immediately without requiring email first.
    r2 = client.post(
        "/webhooks/openbsp",
        json={**base_payload, "text": "quiero hablar con un asesor"},
    )
    j2 = r2.get_json() or {}
    t2 = j2.get("reply", "")
    _print_case("openbsp handoff", t2)
    _assert(r2.status_code == 200, "openbsp handoff should return 200")
    _assert("asesor humano" in t2.lower() or "derivé" in t2.lower(), "handoff reply must be deterministic")
    handoff2 = j2.get("human_handoff_email") or {}
    _assert(handoff2.get("requested") is True, "handoff_requested should be True")
    email_ver2 = j2.get("email_verification") or {}
    _assert(email_ver2.get("conversation_paused") is True, "conversation should pause after handoff")

    # 3) After handoff, any further message must get the paused-reply (not LLM).
    r3 = client.post(
        "/webhooks/openbsp",
        json={**base_payload, "text": "mi correo es test@example.com"},
    )
    j3 = r3.get_json() or {}
    t3 = j3.get("reply", "")
    _print_case("openbsp post-handoff message", t3)
    _assert("asesor humano" in t3.lower() or "derivad" in t3.lower(), "paused reply must be deterministic")


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

    t1b = send("contame del equipo")
    _print_case("chat turn2", t1b)

    t1c = send("y la logistica?")
    _print_case("chat turn3", t1c)
    _assert("correo" in t1c.lower(), "chat turn3 should request email")

    t2 = send("quiero hablar con un asesor")
    _print_case("chat handoff", t2)
    _assert("asesor humano" in t2.lower() or "derivé" in t2.lower(), "chat handoff reply must be deterministic")

    t3 = send("mi correo es test@example.com")
    _print_case("chat post-handoff message", t3)
    _assert("asesor humano" in t3.lower() or "derivad" in t3.lower(), "chat paused reply must be deterministic")


if __name__ == "__main__":
    load_dotenv(Path(".env"))

    print("Running regression tests for email/handoff flows...")
    test_openbsp_flow()
    test_chat_completions_flow()
    print("All regression checks passed.")
