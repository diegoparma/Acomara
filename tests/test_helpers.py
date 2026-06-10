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
    apply_email_ack_or_request_policy,
    apply_language_commit_policy,
    apply_out_of_season_policy,
    build_inbound_signature,
    build_crm_client_context,
    build_respond_tool_call_message,
    detect_language_confident,
    format_whatsapp_departure_dates,
    get_session_language,
    mentions_out_of_season,
    normalize_for_intent,
    split_reply_into_messages,
    supports_respond_tool,
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

    def test_hola_does_not_substring_match_portuguese(self):
        # Regression: "ola" used to be a strong_pt substring token, so any
        # message containing "hola" or "español" got mis-detected as PT.
        from orchestrator.server import detect_language_from_text
        self.assertEqual(detect_language_from_text("hola que tal"), "es")
        self.assertEqual(detect_language_from_text("perdón? sabes hablar español?"), "es")
        self.assertEqual(detect_language_from_text("si español por favor"), "es")

    def test_colloquial_english_not_defaulted_to_spanish(self):
        from orchestrator.server import detect_language_from_text
        self.assertEqual(detect_language_from_text("Do u have 12 days sir?"), "en")

    def test_mixed_spanish_with_single_pt_token_stays_spanish(self):
        from orchestrator.server import detect_language_from_text
        self.assertEqual(
            detect_language_from_text("Aun no te había hecho ninguna pergunta aun"),
            "es",
        )

    def test_email_payload_is_not_confident_language_signal(self):
        self.assertIsNone(detect_language_confident("kfmcdonnell@yahoo.co.uk"))


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

    def test_compacts_pipe_dates_into_single_line(self):
        original = "Fechas confirmadas: diciembre: 1 | 4 | 20 | 27"
        out = format_whatsapp_departure_dates(original, "whatsapp")
        self.assertIn("Dic 1, 4, 20, 27", out)
        self.assertNotIn("|", out)

    def test_handles_english_month_in_dates_block(self):
        original = "Departures: december: 1 | 4 | 20"
        out = format_whatsapp_departure_dates(original, "whatsapp")
        self.assertIn("Dec 1, 4, 20", out)

    def test_no_change_when_single_day(self):
        original = "Salidas confirmadas: enero: 5"
        out = format_whatsapp_departure_dates(original, "whatsapp")
        self.assertEqual(out, original)

    def test_collapses_multiline_program_block(self):
        original = (
            "Fechas confirmadas:\n"
            "18+2 DÍAS | NORMAL EXTENDIDO (recomendado)\n"
            "- Noviembre: 14 | 22\n"
            "-\n"
            "- Diciembre: 1 | 4 | 20 | 27\n"
            "- Enero: 2 | 10 | 31\n"
            "- Febrero: 7\n"
        )
        out = format_whatsapp_departure_dates(original, "whatsapp")
        self.assertIn("*18+2 días - Normal Extendido* _(recomendado)_", out)
        self.assertIn(
            "Nov 14, 22 · Dic 1, 4, 20, 27 · Ene 2, 10, 31 · Feb 7",
            out,
        )
        self.assertNotIn("\n-\n", out)

    def test_formats_inline_programs_as_numbered_list(self):
        original = (
            "Para subir Aconcagua, tenemos salidas 2026/27: "
            "Normal Extendido (18+2 días) Nov14,22 Dic1,4,20,27 Ene2,10,31 Feb7; "
            "Ascenso Rápido (14+2 días) Nov18,26 Dic5,10 Ene6,14 Feb11; "
            "Ascenso Extremo (12+2 días) Nov20,28 Dic7,12,26 Ene2,8,16 Feb6,13."
        )
        out = format_whatsapp_departure_dates(original, "whatsapp")
        self.assertIn("1. *Normal Extendido* (18+2 días): Nov 14, 22", out)
        self.assertIn("2. *Ascenso Rápido* (14+2 días): Nov 18, 26", out)
        self.assertIn("3. *Ascenso Extremo* (12+2 días): Nov 20, 28", out)
        self.assertIn("Dic 1, 4, 20, 27 · Ene 2, 10, 31 · Feb 7", out)
        self.assertNotIn("; ", out)


class CRMClientContextTests(unittest.TestCase):
    def test_first_contact_requests_two_blocks(self):
        out = build_crm_client_context(
            {
                "crm_client_found": True,
                "crm_client_contacted": False,
                "crm_client_name": "Diego",
                "crm_consultation_count": 0,
            }
        )
        self.assertIn("CLIENTE NUEVO", out)
        self.assertIn("dos bloques breves", out)
        self.assertIn("línea en blanco", out)

    def test_returning_client_keeps_vip_context(self):
        out = build_crm_client_context(
            {
                "crm_client_found": True,
                "crm_client_contacted": True,
                "crm_client_name": "Diego",
                "crm_consultation_count": 2,
            }
        )
        self.assertIn("CLIENTE REGISTRADO", out)
        self.assertIn("trato VIP", out)


class MultiMessageHelpersTests(unittest.TestCase):
    def test_supports_respond_tool_true(self):
        tools = [{"type": "function", "function": {"name": "respond"}}]
        self.assertTrue(supports_respond_tool(tools))

    def test_supports_respond_tool_false(self):
        tools = [{"type": "function", "function": {"name": "other_tool"}}]
        self.assertFalse(supports_respond_tool(tools))

    def test_split_reply_by_blank_lines(self):
        out = split_reply_into_messages("Hola\n\nTe paso opciones")
        self.assertEqual(out, ["Hola", "Te paso opciones"])

    def test_build_respond_tool_call_message(self):
        msg = build_respond_tool_call_message(["Hola", "Te paso opciones"])
        self.assertEqual(msg["role"], "assistant")
        self.assertEqual(msg["tool_calls"][0]["function"]["name"], "respond")
        self.assertIn("messages", msg["tool_calls"][0]["function"]["arguments"])


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


class EmailAckOrRequestPolicyTests(unittest.TestCase):
    def test_email_present_replaces_reply_and_marks_captured(self):
        sv: dict = {}
        out = apply_email_ack_or_request_policy(
            "LLM original reply", sv, "jacques@orange.fr", "es"
        )
        self.assertIn("jacques@orange.fr", out)
        self.assertNotIn("LLM original reply", out)
        self.assertTrue(sv["email_received_acked"])
        self.assertTrue(sv["email_captured"])
        self.assertEqual(sv["captured_email"], "jacques@orange.fr")
        self.assertTrue(sv["email_requested"])
        self.assertFalse(sv["proactive_email_capture_pending"])

    def test_email_already_acked_keeps_llm_reply(self):
        sv: dict = {"email_received_acked": True, "email_captured": True}
        out = apply_email_ack_or_request_policy("LLM reply", sv, "x@y.com", "es")
        self.assertEqual(out, "LLM reply")

    def test_no_email_in_window_appends_proactive_ask(self):
        sv: dict = {"conversation_turn_count": 3}
        out = apply_email_ack_or_request_policy("Info útil", sv, None, "es")
        self.assertIn("Info útil", out)
        self.assertIn("correo", out.lower())
        self.assertTrue(sv["email_requested"])
        self.assertTrue(sv["proactive_email_capture_pending"])

    def test_no_email_outside_window_is_passthrough(self):
        sv: dict = {"conversation_turn_count": 1}
        out = apply_email_ack_or_request_policy("Hola!", sv, None, "es")
        self.assertEqual(out, "Hola!")
        self.assertNotIn("email_requested", sv)

    def test_email_already_captured_blocks_proactive_request(self):
        sv: dict = {
            "conversation_turn_count": 3,
            "email_captured": True,
            "email_received_acked": True,
        }
        out = apply_email_ack_or_request_policy("Reply", sv, None, "es")
        self.assertEqual(out, "Reply")


class OutOfSeasonPolicyTests(unittest.TestCase):
    def test_prepends_warning_when_out_of_season_intent(self):
        sv: dict = {}
        out = apply_out_of_season_policy(
            "Detalle de la expedición",
            "Quiero hacer la expedición en mayo",
            sv,
            "es",
        )
        self.assertTrue(out.startswith("Importante"))
        self.assertIn("Detalle de la expedición", out)
        self.assertTrue(sv["out_of_season_warned"])

    def test_only_once_per_conversation(self):
        sv: dict = {"out_of_season_warned": True}
        out = apply_out_of_season_policy("Reply", "passeio em julho", sv, "pt")
        self.assertEqual(out, "Reply")

    def test_in_season_does_not_warn(self):
        sv: dict = {}
        out = apply_out_of_season_policy("Reply", "expedición en diciembre", sv, "es")
        self.assertEqual(out, "Reply")
        self.assertNotIn("out_of_season_warned", sv)


class LanguageCommitPolicyTests(unittest.TestCase):
    def test_confident_signal_commits(self):
        sv: dict = {"conversation_language": "es"}
        apply_language_commit_policy("I would like info about Aconcagua expedition", sv)
        self.assertEqual(sv["conversation_language"], "en")
        self.assertEqual(sv["conversation_language_source"], "message_detected")

    def test_short_ambiguous_keeps_existing_without_overwriting_source(self):
        sv: dict = {"conversation_language": "en"}
        apply_language_commit_policy("Hola", sv)
        self.assertEqual(sv["conversation_language"], "en")
        self.assertNotIn("conversation_language_source", sv)

    def test_no_existing_lang_uses_low_confidence_fallback(self):
        sv: dict = {}
        apply_language_commit_policy("Hola", sv)
        self.assertIn(sv["conversation_language"], {"es", "en", "pt"})
        self.assertEqual(sv["conversation_language_source"], "message_detected_low_confidence")

    def test_explicit_english_preference_locks_language(self):
        sv: dict = {"conversation_language": "es"}
        apply_language_commit_policy("I don't speak Spanish, English please", sv)
        self.assertEqual(sv["conversation_language"], "en")
        self.assertEqual(sv["conversation_language_source"], "user_preference_explicit")
        self.assertTrue(sv["conversation_language_locked"])

    def test_explicit_lock_survives_email_message(self):
        sv: dict = {
            "conversation_language": "en",
            "conversation_language_source": "user_preference_explicit",
            "conversation_language_locked": True,
        }
        apply_language_commit_policy("kfmcdonnell@yahoo.co.uk", sv)
        self.assertEqual(sv["conversation_language"], "en")
        self.assertEqual(sv["conversation_language_source"], "user_preference_explicit")
        self.assertTrue(sv["conversation_language_locked"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
