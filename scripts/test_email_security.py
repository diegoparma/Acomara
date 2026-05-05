#!/usr/bin/env python3
"""Regression tests for email verification + handoff flows.

This script validates behavior in both endpoints:
- /webhooks/openbsp
- /v1/chat/completions
"""

from __future__ import annotations

from pathlib import Path
import sys
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request, urlopen
from uuid import uuid4
import json

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orchestrator.server import app
import orchestrator.server as server


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
    _assert(r1c.status_code == 200, "openbsp turn3 should return 200")
    _assert("correo" in t1c.lower(), "openbsp turn3 should proactively request email")

    # 2) Handoff request without email → must ask for email, NOT execute handoff yet.
    r2 = client.post(
        "/webhooks/openbsp",
        json={**base_payload, "text": "quiero hablar con un asesor humano"},
    )
    j2 = r2.get_json() or {}
    t2 = j2.get("reply", "")
    _print_case("openbsp handoff triggers email request", t2)
    _assert(r2.status_code == 200, "openbsp handoff should return 200")
    _assert("correo" in t2.lower(), "handoff must ask for email before executing")
    email_ver2 = j2.get("email_verification") or {}
    _assert(email_ver2.get("conversation_paused") is not True, "conversation must NOT be paused yet")

    # 3) User provides email → HIBP check passes → handoff executes.
    r3 = client.post(
        "/webhooks/openbsp",
        json={**base_payload, "text": "mi correo es test@example.com"},
    )
    j3 = r3.get_json() or {}
    t3 = j3.get("reply", "")
    _print_case("openbsp email provided → handoff executed", t3)
    _assert("asesor humano" in t3.lower() or "derivé" in t3.lower(), "handoff reply must be deterministic")
    email_ver3 = j3.get("email_verification") or {}
    _assert(email_ver3.get("conversation_paused") is True, "conversation should pause after handoff")

    # 4) Any further message must get the paused-reply.
    r4 = client.post(
        "/webhooks/openbsp",
        json={**base_payload, "text": "hola de nuevo"},
    )
    t4 = (r4.get_json() or {}).get("reply", "")
    _print_case("openbsp post-handoff", t4)
    _assert("asesor humano" in t4.lower() or "derivad" in t4.lower(), "paused reply must be deterministic")


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
    _assert(len(t1c) > 0, "chat turn3 should return a reply")
    _assert("correo" in t1c.lower() or "email" in t1c.lower(), "chat turn3 should proactively request email")

    t2 = send("quiero hablar con un asesor humano")
    _print_case("chat handoff triggers email request", t2)
    _assert("correo" in t2.lower(), "chat handoff must ask for email first")

    t3 = send("mi correo es test@example.com")
    _print_case("chat email provided → handoff executed", t3)
    _assert("asesor humano" in t3.lower() or "derivé" in t3.lower(), "chat handoff reply must be deterministic")

    t4 = send("hola de nuevo")
    _print_case("chat post-handoff", t4)
    _assert("asesor humano" in t4.lower() or "derivad" in t4.lower(), "chat paused reply must be deterministic")


def test_reset_command_openbsp() -> None:
    client = app.test_client()
    conv_id = f"reg-reset-openbsp-{uuid4()}"
    base_payload = {
        "conversation_id": conv_id,
        "organization_id": "test-org",
        "organization_address": "test-org-address",
        "contact_id": "test-contact",
        "contact_address": "+5491111111111",
        "channel": "whatsapp",
    }

    # Drive the session into paused state via handoff.
    client.post("/webhooks/openbsp", json={**base_payload, "text": "hola"})
    client.post("/webhooks/openbsp", json={**base_payload, "text": "quiero hablar con un asesor humano"})
    client.post("/webhooks/openbsp", json={**base_payload, "text": "mi correo es test@example.com"})
    paused_reply = (client.post("/webhooks/openbsp", json={**base_payload, "text": "seguimos"}).get_json() or {}).get("reply", "")
    _assert("derivad" in paused_reply.lower(), "session should be paused before /reset")

    # Reset command should delete session and return fresh-start reply.
    reset_reply = (client.post("/webhooks/openbsp", json={**base_payload, "text": "/reset hola"}).get_json() or {}).get("reply", "")
    _print_case("openbsp /reset", reset_reply)
    _assert("reiniciada" in reset_reply.lower(), "/reset should acknowledge reset")

    # Next message should behave like a new conversation (not paused reply).
    fresh_reply = (client.post("/webhooks/openbsp", json={**base_payload, "text": "hola"}).get_json() or {}).get("reply", "")
    _print_case("openbsp post-/reset", fresh_reply)
    _assert("bienvenido" in fresh_reply.lower(), "conversation should restart after /reset")


def test_reset_command_chat_completions() -> None:
    client = app.test_client()
    conv_id = f"reg-reset-chat-{uuid4()}"
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

    # Drive the session into paused state via handoff.
    send("hola")
    send("quiero hablar con un asesor humano")
    send("mi correo es test@example.com")
    paused_reply = send("seguimos")
    _assert("derivad" in paused_reply.lower(), "session should be paused before /reset")

    # Reset command should clear session.
    reset_reply = send("/reset hola")
    _print_case("chat /reset", reset_reply)
    _assert("reiniciada" in reset_reply.lower(), "chat /reset should acknowledge reset")

    # Next message should behave like a new conversation.
    fresh_reply = send("hola")
    _print_case("chat post-/reset", fresh_reply)
    _assert("bienvenido" in fresh_reply.lower(), "chat conversation should restart after /reset")


def test_suspicious_email_uses_spanish_and_admin_fallback() -> None:
    client = app.test_client()
    conv_id = f"reg-suspicious-{uuid4()}"
    base_payload = {
        "conversation_id": conv_id,
        "organization_id": "test-org",
        "organization_address": "test-org-address",
        "contact_id": "test-contact",
        "contact_address": "+5491111111111",
        "channel": "whatsapp",
    }

    with patch("orchestrator.server.check_email_reputation", return_value=(True, True)):
        with patch(
            "orchestrator.server.try_send_compromised_email_alert",
            return_value=(True, 500, {"error": "smtp failed"}),
        ) as primary_alert_mock:
            with patch(
                "orchestrator.server.try_send_handoff_email",
                return_value=(True, 200, {"ok": True, "provider": "smtp"}),
            ) as fallback_alert_mock:
                client.post(
                    "/webhooks/openbsp",
                    json={**base_payload, "text": "quiero hablar con un asesor humano"},
                )
                suspicious_resp = client.post(
                    "/webhooks/openbsp",
                    json={**base_payload, "text": "mi correo es ake-prospect-xyz@testing.invalid"},
                )

    suspicious_reply = (suspicious_resp.get_json() or {}).get("reply", "")
    _print_case("openbsp suspicious email paused reply", suspicious_reply)
    _assert(suspicious_resp.status_code == 200, "suspicious email flow should return 200")
    _assert("gracias" in suspicious_reply.lower(), "suspicious paused reply must stay in spanish")
    _assert("thank you" not in suspicious_reply.lower(), "suspicious paused reply must not switch to english")
    _assert(primary_alert_mock.call_count == 1, "primary suspicious alert should be attempted once")
    _assert(fallback_alert_mock.call_count == 1, "fallback admin email should be attempted when primary fails")


def test_proactive_email_capture_enables_direct_handoff() -> None:
    client = app.test_client()
    conv_id = f"reg-proactive-openbsp-{uuid4()}"
    base_payload = {
        "conversation_id": conv_id,
        "organization_id": "test-org",
        "organization_address": "test-org-address",
        "contact_id": "test-contact",
        "contact_address": "+5491111111111",
        "channel": "whatsapp",
    }

    client.post("/webhooks/openbsp", json={**base_payload, "text": "hola"})
    client.post("/webhooks/openbsp", json={**base_payload, "text": "contame del equipo"})
    turn3 = client.post("/webhooks/openbsp", json={**base_payload, "text": "y la logistica?"})
    turn3_reply = (turn3.get_json() or {}).get("reply", "")
    _print_case("openbsp proactive email prompt", turn3_reply)
    _assert("correo" in turn3_reply.lower(), "turn3 should ask for email proactively")

    email_reply = (
        client.post(
            "/webhooks/openbsp",
            json={**base_payload, "text": "mi correo es test@example.com"},
        ).get_json()
        or {}
    ).get("reply", "")
    _print_case("openbsp proactive email saved", email_reply)
    _assert("verifiqu" in email_reply.lower() or "registrado" in email_reply.lower(), "verified proactive email should get deterministic acknowledgement")

    handoff_reply = (
        client.post(
            "/webhooks/openbsp",
            json={**base_payload, "text": "quiero hablar con un asesor humano"},
        ).get_json()
        or {}
    ).get("reply", "")
    _print_case("openbsp direct handoff after proactive email", handoff_reply)
    _assert("derivé" in handoff_reply.lower() or "advisor" in handoff_reply.lower() or "asesor humano" in handoff_reply.lower(), "handoff should execute directly after proactive verified email")


def test_proactive_email_capture_chat_flow() -> None:
    client = app.test_client()
    conv_id = f"reg-proactive-chat-{uuid4()}"
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

    send("hola")
    send("contame del equipo")
    turn3 = send("y la logistica?")
    _print_case("chat proactive email prompt", turn3)
    _assert("correo" in turn3.lower() or "email" in turn3.lower(), "chat turn3 should ask for email proactively")

    email_reply = send("mi correo es test@example.com")
    _print_case("chat proactive email saved", email_reply)
    _assert("verifiqu" in email_reply.lower() or "registrado" in email_reply.lower(), "chat should acknowledge proactive verified email")

    handoff_reply = send("quiero hablar con un asesor humano")
    _print_case("chat direct handoff after proactive email", handoff_reply)
    _assert("derivé" in handoff_reply.lower() or "asesor humano" in handoff_reply.lower(), "chat handoff should execute directly after proactive verified email")


def test_multilanguage_fixed_phrases() -> None:
    """Test that fixed phrases respect conversation_language from session."""
    client = app.test_client()
    conv_id = f"reg-lang-en-{uuid4()}"
    base_payload = {
        "conversation_id": conv_id,
        "organization_id": "test-org",
        "organization_address": "test-org-address",
        "contact_id": "test-contact",
        "contact_address": "+5491111111111",
        "channel": "whatsapp",
    }

    # Mock session_get to return conversation_language="en" for this test
    with patch("orchestrator.server.try_session_get") as mock_get:
        def get_side_effect(base_url, cid):
            if cid == conv_id:
                return {
                    "variables": {
                        "conversation_language": "en",
                        "conversation_language_source": "manual",
                        "conversation_turn_count": 0,
                    },
                }
            return None
        
        mock_get.side_effect = get_side_effect
        
        # 1. Trigger handoff in English session
        resp1 = client.post(
            "/webhooks/openbsp",
            json={**base_payload, "text": "quiero hablar con un asesor humano"},
        )
        reply1 = (resp1.get_json() or {}).get("reply", "")
        _print_case("English handoff trigger", reply1)
        _assert("email" in reply1.lower(), "handoff should ask for email")
        _assert("To connect" in reply1 or "email" in reply1.lower(), "handoff message should be in English")
        _assert("correo" not in reply1.lower(), "message should not have Spanish words")

    # 2. After reset, language should go back to Spanish (default)
    reset_resp = client.post(
        "/webhooks/openbsp",
        json={**base_payload, "text": "/reset"},
    )
    reset_reply = (reset_resp.get_json() or {}).get("reply", "")
    _print_case("post-reset (Spanish default)", reset_reply)
    _assert("reiniciada" in reset_reply.lower(), "reset should be in Spanish by default")

    # 3. Next handoff after reset should be in Spanish
    resp2 = client.post(
        "/webhooks/openbsp",
        json={**base_payload, "text": "quiero hablar con un asesor humano"},
    )
    reply2 = (resp2.get_json() or {}).get("reply", "")
    _print_case("Spanish handoff after reset", reply2)
    _assert("correo" in reply2.lower(), "handoff should ask for email in Spanish")
    _assert("Para conectarte" in reply2 or "correo" in reply2.lower(), "handoff message should be in Spanish after reset")


def test_public_version_command_disabled_on_webhook() -> None:
    client = app.test_client()
    conv_id = f"reg-version-disabled-{uuid4()}"
    payload = {
        "conversation_id": conv_id,
        "organization_id": "test-org",
        "organization_address": "test-org-address",
        "contact_id": "test-contact",
        "contact_address": "+5491111111111",
        "channel": "whatsapp",
        "text": "/version",
    }

    with patch("orchestrator.server._env_bool", return_value=False):
        with patch("orchestrator.server.ensure_runtime", return_value={"api_key": "test-key", "session_base_url": None}):
            response = client.post("/webhooks/openbsp", json=payload)

    body = response.get_json() or {}
    _assert(response.status_code == 200, "webhook /version should return 200")
    _assert("no disponible" in (body.get("reply") or "").lower(), "public /version should be disabled")
    _assert((body.get("openbsp_send") or {}).get("response", {}).get("info") == "command_disabled", "disabled command must expose command_disabled info")


def test_deduplicate_inbound_webhook_replays_last_reply() -> None:
    client = app.test_client()
    conv_id = f"reg-dedup-openbsp-{uuid4()}"
    msg = {
        "text": "hola equipo",
        "conversation_id": conv_id,
        "organization_id": "test-org",
        "organization_address": "test-org-address",
        "contact_id": "test-contact",
        "contact_address": "+5491111111111",
        "channel": "whatsapp",
    }
    now_ts = 2_000_000_000
    sig = server.build_inbound_signature(msg)

    with patch("orchestrator.server.time.time", return_value=now_ts):
        with patch("orchestrator.server.ensure_runtime", return_value={"api_key": "test-key", "session_base_url": "http://session"}):
            with patch(
                "orchestrator.server.try_session_get",
                return_value={
                    "variables": {
                        "last_assistant_reply": "respuesta previa",
                        "last_inbound_signature": sig,
                        "last_inbound_signature_ts": now_ts,
                    }
                },
            ):
                response = client.post("/webhooks/openbsp", json=msg)

    body = response.get_json() or {}
    _assert(response.status_code == 200, "dedup webhook should return 200")
    _assert(body.get("deduplicated") is True, "webhook should flag deduplicated=true")
    _assert(body.get("reply") == "respuesta previa", "webhook dedup should replay last assistant reply")


def test_deduplicate_inbound_chat_replays_last_reply() -> None:
    client = app.test_client()
    conv_id = f"reg-dedup-chat-{uuid4()}"
    headers = {
        "Authorization": "Bearer test-orchestrator-key",
        "conversation-id": conv_id,
        "organization-id": "test-org",
        "organization-address": "test-org-address",
        "contact-id": "test-contact",
        "contact-address": "+5491111111111",
        "channel": "whatsapp",
    }
    user_text = "hola equipo"
    msg = {
        "text": user_text,
        "conversation_id": conv_id,
        "organization_id": headers["organization-id"],
        "organization_address": headers["organization-address"],
        "contact_id": headers["contact-id"],
        "contact_address": headers["contact-address"],
        "channel": headers["channel"],
    }
    now_ts = 2_000_000_000
    sig = server.build_inbound_signature(msg)

    payload = {
        "model": "gpt-5.4",
        "messages": [{"role": "user", "content": user_text}],
        "stream": False,
    }

    with patch("orchestrator.server.time.time", return_value=now_ts):
        with patch("orchestrator.server.is_authorized_for_chat", return_value=True):
            with patch("orchestrator.server.ensure_runtime", return_value={"api_key": "test-key", "session_base_url": "http://session"}):
                with patch(
                    "orchestrator.server.try_session_get",
                    return_value={
                        "variables": {
                            "last_assistant_reply": "chat previa",
                            "last_inbound_signature": sig,
                            "last_inbound_signature_ts": now_ts,
                        }
                    },
                ):
                    response = client.post("/v1/chat/completions", headers=headers, json=payload)

    body = response.get_json() or {}
    choice_content = (((body.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
    _assert(response.status_code == 200, "dedup chat should return 200")
    _assert(body.get("deduplicated") is True, "chat should flag deduplicated=true")
    _assert(choice_content == "chat previa", "chat dedup should replay last assistant reply")


if __name__ == "__main__":
    load_dotenv(Path(".env"))

    print("Running regression tests for email/handoff flows...")
    test_openbsp_flow()
    test_chat_completions_flow()
    test_reset_command_openbsp()
    test_reset_command_chat_completions()
    test_suspicious_email_uses_spanish_and_admin_fallback()
    test_proactive_email_capture_enables_direct_handoff()
    test_proactive_email_capture_chat_flow()
    test_multilanguage_fixed_phrases()
    test_public_version_command_disabled_on_webhook()
    test_deduplicate_inbound_webhook_replays_last_reply()
    test_deduplicate_inbound_chat_replays_last_reply()
    print("All regression checks passed.")
