#!/usr/bin/env python3
"""Unit tests for deterministic helpers used by the orchestrator pipeline.

These tests pin down current behavior of the small, pure functions that the
upcoming `process_inbound_message` refactor will move/regroup. As long as
their signatures and outputs stay stable, the refactor cannot regress them.

No network, no OpenAI, no Supabase. Run with:
    python3 tests/test_helpers.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.security import (  # noqa: E402
    extract_email_from_text,
    should_request_email,
)
from orchestrator.server import (  # noqa: E402
    build_inbound_signature,
    detect_language_confident,
    format_whatsapp_departure_dates,
    get_session_language,
    mentions_out_of_season,
    normalize_for_intent,
)


class ShouldRequestEmailTests(unittest.TestCase):
    def test_request_within_window(self):
        self.assertTrue(should_request_email({"conversation_turn_count": 3}))
        self.assertTrue(should_request_email({"conversation_turn_count": 4}))

    def test_no_request_outside_window(self):
        self.assertFalse(should_request_email({"conversation_turn_count": 1}))
        self.assertFalse(should_request_email({"conversation_turn_count": 2}))
        self.assertFalse(should_request_email({"conversation_turn_count": 5}))

    def test_each_email_flag_blocks_request(self):
        for flag in (
            "email_captured",
            "captured_email",
            "verified_email",
            "email_requested",
            "email_verified",
            "email_compromised",
        ):
            with self.subTest(flag=flag):
                self.assertFalse(
                    should_request_email({"conversation_turn_count": 3, flag: "x@y.z" if "email" in flag else True}),
                    f"{flag} should block re-request",
                )


class ExtractEmailTests(unittest.TestCase):
    def test_extracts_basic_email(self):
        self.assertEqual(extract_email_from_text("Mi mail es jacques@orange.fr"), "jacques@orange.fr")

    def test_returns_none_when_absent(self):
        self.assertIsNone(extract_email_from_text("hola, sin email aqui"))

    def test_picks_first_when_many(self):
        out = extract_email_from_text("contact a@b.com or c@d.com")
        self.assertEqual(out, "a@b.com")


class LanguageDetectionTests(unittest.TestCase):
    def test_short_ambiguous_greeting_returns_none(self):
        self.assertIsNone(detect_language_confident("Hola"))
        self.assertIsNone(detect_language_confident("Hi"))
        self.assertIsNone(detect_language_confident("Olá"))

    def test_strong_english_tokens(self):
        self.assertEqual(
            detect_language_confident("I would like information about Aconcagua expeditions"),
            "en",
        )

    def test_strong_spanish_tokens(self):
        self.assertEqual(
            detect_language_confident("Quisiera información sobre la expedición"),
            "es",
        )

    def test_strong_portuguese_tokens(self):
        self.assertEqual(
            detect_language_confident("Gostaria de informações sobre o passeio"),
            "pt",
        )


class SessionLanguageTests(unittest.TestCase):
    def test_default_when_empty(self):
        self.assertEqual(get_session_language(None), "es")
        self.assertEqual(get_session_language({}), "es")

    def test_uses_stored_when_no_signal(self):
        self.assertEqual(get_session_language({"conversation_language": "en"}), "en")

    def test_user_message_overrides_when_confident(self):
        # Stored es but user wrote a confident english sentence → switch to en.
        out = get_session_language(
            {"conversation_language": "es"},
            "I would like to climb Aconcagua next February",
        )
        self.assertEqual(out, "en")

    def test_short_ambiguous_keeps_stored(self):
        out = get_session_language({"conversation_language": "en"}, "Hola")
        self.assertEqual(out, "en")


class OutOfSeasonTests(unittest.TestCase):
    def test_in_season_month_returns_false(self):
        self.assertFalse(mentions_out_of_season("expedition in december"))
        self.assertFalse(mentions_out_of_season("subir en enero"))

    def test_out_of_season_with_intent(self):
        self.assertTrue(mentions_out_of_season("expedition in june"))
        self.assertTrue(mentions_out_of_season("quiero ir de trekking en mayo"))
        self.assertTrue(mentions_out_of_season("passeio em julho"))

    def test_out_of_season_without_intent_returns_false(self):
        self.assertFalse(mentions_out_of_season("hola, soy de mayo"))

    def test_numeric_date_pattern(self):
        self.assertTrue(mentions_out_of_season("quiero hacer la expedicion 27/05"))


class FormatWhatsappDatesTests(unittest.TestCase):
    def test_passthrough_for_non_whatsapp(self):
        text = "Fechas de salida: enero: 1 | 5 | 10"
        self.assertEqual(format_whatsapp_departure_dates(text, "web"), text)

    def test_passthrough_when_text_lacks_date_markers(self):
        text = "Hola, ¿en qué puedo ayudarte?"
        self.assertEqual(format_whatsapp_departure_dates(text, "whatsapp"), text)

    def test_expands_pipe_dates_into_list(self):
        original = "Fechas confirmadas: diciembre: 1 | 4 | 20 | 27"
        out = format_whatsapp_departure_dates(original, "whatsapp")
        for expected in ("- diciembre 1", "- diciembre 4", "- diciembre 20", "- diciembre 27"):
            self.assertIn(expected, out)

    def test_handles_english_month_in_dates_block(self):
        original = "Departures: december: 1 | 4 | 20"
        out = format_whatsapp_departure_dates(original, "whatsapp")
        self.assertIn("- december 1", out)
        self.assertIn("- december 20", out)

    def test_no_change_when_single_day(self):
        original = "Salidas confirmadas: enero: 5"
        out = format_whatsapp_departure_dates(original, "whatsapp")
        self.assertEqual(out, original)


class NormalizeAndSignatureTests(unittest.TestCase):
    def test_normalize_strips_accents_and_lowercases(self):
        out = normalize_for_intent("Información Aconcagüa  ")
        self.assertEqual(out, "informacion aconcagua")

    def test_signature_is_stable(self):
        msg = {"conversation_id": "abc", "text": "hola", "channel": "whatsapp"}
        self.assertEqual(build_inbound_signature(msg), build_inbound_signature(dict(msg)))

    def test_signature_changes_with_text(self):
        a = {"conversation_id": "abc", "text": "hola", "channel": "whatsapp"}
        b = {"conversation_id": "abc", "text": "chau", "channel": "whatsapp"}
        self.assertNotEqual(build_inbound_signature(a), build_inbound_signature(b))


if __name__ == "__main__":
    unittest.main(verbosity=2)
