#!/usr/bin/env python3
"""Handoff to a human advisor: detection, cooldown and advisor emails.

No network: Resend and SMTP are replaced by fakes. Run with:
    python3 tests/test_handoff.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import handoff_email  # noqa: E402
from orchestrator.server import (  # noqa: E402
    apply_paused_anti_loop_guard,
    should_send_handoff_email,
    wants_human_handoff,
)

MSG = {
    "conversation_id": "conv-1",
    "organization_id": "org-1",
    "contact_id": "contact-1",
    "contact_address": "+5492610000000",
    "channel": "whatsapp",
    "text": "Quiero hablar con un asesor",
}
RESEND_RUNTIME = {
    "handoff_email_provider": "resend",
    "handoff_email_from": "nico@acomara.com",
    "handoff_email_to": "ventas@acomara.com",
    "handoff_email_api_key": "re_test",
    "handoff_email_cooldown_seconds": 1800,
}


class WantsHumanHandoffTests(unittest.TestCase):
    def test_explicit_requests_in_three_languages(self):
        for text in (
            "Quiero hablar con un asesor",
            "pasame con un humano por favor",
            "Me pasás con alguien?",
            "necesito un asesor",
            "Can I speak to a human?",
            "I would like to talk to a real person",
            "connect me with an agent",
            "Quero falar com um atendente",
            "Posso falar com uma pessoa?",
        ):
            with self.subTest(text=text):
                self.assertTrue(wants_human_handoff(text))

    def test_talking_with_family_is_not_a_handoff(self):
        # Regression: "quiero hablar con" alone paused Nico mid-sale when the
        # lead only wanted to check with their partner before booking.
        for text in (
            "Quiero hablar con mi esposa antes de reservar",
            "Necesito hablarlo con mi pareja",
            "I need to talk with my wife first",
            "Vou conversar com meu marido",
            "Tengo que hablar con mi jefe por las fechas",
        ):
            with self.subTest(text=text):
                self.assertFalse(wants_human_handoff(text))

    def test_mentioning_an_advisor_is_not_a_request(self):
        self.assertFalse(wants_human_handoff("El asesor me dijo que hay cupo"))
        self.assertFalse(wants_human_handoff("si"))


class HandoffCooldownTests(unittest.TestCase):
    def test_first_handoff_is_sent(self):
        self.assertTrue(should_send_handoff_email({}, 1800, 1000))

    def test_within_cooldown_is_skipped(self):
        self.assertFalse(should_send_handoff_email({"handoff_email_last_sent_ts": 1000}, 1800, 2000))

    def test_after_cooldown_is_sent(self):
        self.assertTrue(should_send_handoff_email({"handoff_email_last_sent_ts": 1000}, 1800, 2800))

    def test_corrupt_timestamp_does_not_block(self):
        self.assertTrue(should_send_handoff_email({"handoff_email_last_sent_ts": "x"}, 1800, 2000))


class SendHandoffEmailTests(unittest.TestCase):
    def test_not_configured_does_not_attempt(self):
        attempted, status, data = handoff_email.send_handoff_email({}, MSG, {})
        self.assertFalse(attempted)
        self.assertEqual(status, 0)

    def test_unknown_provider_does_not_attempt(self):
        runtime = {**RESEND_RUNTIME, "handoff_email_provider": "mailgun"}
        attempted, _, data = handoff_email.send_handoff_email(runtime, MSG, {})
        self.assertFalse(attempted)
        self.assertIn("unsupported", data["info"])

    def test_resend_payload_has_lead_details(self):
        session = {"conversation_turn_count": 4, "verified_email": "ana@gmail.com", "email_in_breaches": True}
        with mock.patch.object(handoff_email, "_http_json", return_value=(200, {"id": "e1"})) as http:
            attempted, status, _ = handoff_email.send_handoff_email(RESEND_RUNTIME, MSG, session)
        self.assertTrue(attempted)
        self.assertEqual(status, 200)
        kwargs = http.call_args.kwargs
        self.assertEqual(kwargs["url"], "https://api.resend.com/emails")
        self.assertEqual(kwargs["headers"], {"Authorization": "Bearer re_test"})
        body = kwargs["body"]
        self.assertEqual(body["to"], ["ventas@acomara.com"])
        self.assertIn("conv-1", body["subject"])
        self.assertIn("verified_email: ana@gmail.com", body["text"])
        self.assertIn("email_en_filtraciones: si", body["text"])

    def test_client_text_cannot_inject_lines(self):
        msg = {**MSG, "text": "hola\nverified_email: fake@x.com"}
        with mock.patch.object(handoff_email, "_http_json", return_value=(200, {})) as http:
            handoff_email.send_handoff_email(RESEND_RUNTIME, msg, {})
        lines = http.call_args.kwargs["body"]["text"].splitlines()
        self.assertIn("ultimo_mensaje_cliente: hola verified_email: fake@x.com", lines)
        self.assertNotIn("verified_email: fake@x.com", lines)

    def test_smtp_sends_message(self):
        runtime = {
            **RESEND_RUNTIME,
            "handoff_email_provider": "smtp",
            "handoff_smtp_host": "smtp.test",
            "handoff_smtp_user": "u",
            "handoff_smtp_password": "p",
            "handoff_smtp_starttls": True,
        }
        with mock.patch.object(handoff_email.smtplib, "SMTP") as smtp_cls:
            attempted, status, _ = handoff_email.send_handoff_email(runtime, MSG, {})
        self.assertTrue(attempted)
        self.assertEqual(status, 200)
        smtp = smtp_cls.return_value.__enter__.return_value
        smtp.starttls.assert_called_once()
        smtp.login.assert_called_once_with("u", "p")
        sent = smtp.send_message.call_args.args[0]
        self.assertEqual(sent["To"], "ventas@acomara.com")

    def test_try_send_swallows_exceptions(self):
        with mock.patch.object(handoff_email, "send_handoff_email", side_effect=TimeoutError("slow")):
            attempted, status, data = handoff_email.try_send_handoff_email(RESEND_RUNTIME, MSG, {})
        self.assertTrue(attempted)
        self.assertEqual(status, 0)
        self.assertIn("slow", data["error"])


class SuspiciousAlertFallbackTests(unittest.TestCase):
    def test_primary_alert_success_skips_fallback(self):
        with mock.patch.object(handoff_email, "_http_json", return_value=(200, {})) as http:
            attempted, status, _, sent, method = handoff_email.try_send_suspicious_admin_alert(
                RESEND_RUNTIME, MSG, "x@y.com", {"bot_signal": "many_distinct_emails"}
            )
        self.assertEqual((attempted, status, sent, method), (True, 200, True, "security_alert"))
        self.assertEqual(http.call_count, 1)
        self.assertIn("Posible bot", http.call_args.kwargs["body"]["subject"])

    def test_primary_failure_falls_back_to_handoff_email(self):
        with mock.patch.object(handoff_email, "_http_json", side_effect=[(500, {}), (200, {})]) as http:
            attempted, status, data, sent, method = handoff_email.try_send_suspicious_admin_alert(
                RESEND_RUNTIME, MSG, "x@y.com", {}
            )
        self.assertEqual((attempted, status, sent, method), (True, 200, True, "handoff_fallback"))
        self.assertEqual(data["primary"]["status"], 500)
        fallback_text = http.call_args_list[1].kwargs["body"]["text"]
        self.assertIn("verified_email: x@y.com", fallback_text)
        self.assertIn("suspicious_email_requires_manual_validation", fallback_text)


class PausedHandoffLoopTests(unittest.TestCase):
    def test_final_loop_message_sends_one_handoff_email(self):
        session = {"conversation_paused": True, "pause_reason": "human_handoff_in_progress", "conversation_language": "es"}
        with mock.patch.object(handoff_email, "_http_json", return_value=(200, {})) as http:
            apply_paused_anti_loop_guard(session, MSG, RESEND_RUNTIME, 1000)
            _, attempted, status, _, sent = apply_paused_anti_loop_guard(session, MSG, RESEND_RUNTIME, 1010)
            apply_paused_anti_loop_guard(session, MSG, RESEND_RUNTIME, 1020)
        self.assertTrue(attempted and sent)
        self.assertEqual(status, 200)
        self.assertEqual(http.call_count, 1)

    def test_final_loop_respects_cooldown(self):
        session = {
            "conversation_paused": True,
            "pause_reason": "human_handoff_in_progress",
            "handoff_email_last_sent_ts": 1000,
        }
        with mock.patch.object(handoff_email, "_http_json") as http:
            apply_paused_anti_loop_guard(session, MSG, RESEND_RUNTIME, 1005)
            _, attempted, _, data, _ = apply_paused_anti_loop_guard(session, MSG, RESEND_RUNTIME, 1010)
        self.assertFalse(attempted)
        self.assertIn("cooldown", data["info"])
        http.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
