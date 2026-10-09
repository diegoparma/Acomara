#!/usr/bin/env python3
"""Fernando's sales rules applied in code (simulation 2026-10-09).

No network. Run with:
    python3 tests/test_sales_rules.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import json  # noqa: E402
from datetime import date  # noqa: E402

from orchestrator.departures import season_departures  # noqa: E402
from orchestrator.sales_rules import (  # noqa: E402
    apply_video_call_close,
    extended_alternative_note,
    short_program_reply,
)

FAQ_ROWS = [json.loads(line) for line in (ROOT / "docs" / "knowledge" / "faq_cloud_index.jsonl").open()]
DEPARTURES = season_departures(FAQ_ROWS)
TODAY = date(2026, 10, 9)


class ShortProgramRuleTests(unittest.TestCase):
    def test_kilimanjaro_climber_gets_the_18_plus_2(self):
        # Regression: the model said the 14+2 "can be suitable" after Kilimanjaro (5,895 m).
        out = short_program_reply("I have climbed Kilimanjaro, is the 14+2 ok for me?", "en")
        self.assertIn("above 6,000 m", out)
        self.assertIn("Kilimanjaro (5,895 m) doesn't reach that altitude", out)
        self.assertIn("I'd recommend the 18+2", out)

    def test_spanish_and_portuguese(self):
        self.assertIn("Te recomiendo el 18+2", short_program_reply("¿El 12+2 me sirve? Hice el Lanín", "es"))
        self.assertIn("el 12+2 es solo para", short_program_reply("¿El 12+2 me sirve? Hice el Lanín", "es"))
        self.assertIn("Recomendo o 18+2", short_program_reply("Posso fazer o 14+2?", "pt"))

    def test_people_above_6000_m_are_left_to_the_model(self):
        for text in ("Subí el Chimborazo, ¿puedo hacer el 14+2?", "Estuve a 6.400 m en Bolivia, ¿me conviene el 12+2?"):
            with self.subTest(text=text):
                self.assertIsNone(short_program_reply(text, "es"))

    def test_other_questions_about_short_programs_are_not_caught(self):
        for text in ("¿Qué diferencia hay entre el 14+2 y el 18+2?", "ok, y el 14+2 qué incluye?", "¿Cuánto sale el 14+2?", "Quiero el 18+2"):
            with self.subTest(text=text):
                self.assertIsNone(short_program_reply(text, "es"))


class VideoCallCloseTests(unittest.TestCase):
    def test_picking_a_date_gets_availability_note_and_invite(self):
        # Regression: "Me interesa la del 5/12" ended with "¿Querés que te cuente más sobre ese programa?".
        session: dict = {}
        out = apply_video_call_close(
            "El 5/12 corresponde al 14+2. ¿Querés que te cuente más sobre ese programa?", "Me interesa la del 5/12", session, "es"
        )
        self.assertNotIn("cuente más", out)
        self.assertIn("La disponibilidad de esa fecha te la confirma un asesor.", out)
        self.assertIn("videollamada", out)
        self.assertIn("pasame tu email", out)
        self.assertTrue(session["video_call_offered"])

    def test_availability_note_replaces_the_models_advisor_sentence(self):
        # Regression: the advisor was named twice in a row before the invite.
        reply = (
            "La salida del 5/12 es para el 14+2, para quienes ya estuvieron arriba de 6.000 m. "
            "Eso te lo puede ver un asesor del equipo y te guía con la mejor opción."
        )
        out = apply_video_call_close(reply, "Me interesa la del 5/12", {}, "es")
        self.assertEqual(out.count("asesor"), 1)
        self.assertIn("La salida del 5/12 es para el 14+2", out)

    def test_invite_with_email_counts_as_the_email_ask(self):
        # Regression: the next turn appended "pasame tu email" again.
        session: dict = {}
        apply_video_call_close("El 18+2 sale USD 7.250.", "quiero reservar", session, "es")
        self.assertTrue(session["email_requested"])
        from orchestrator.security import should_request_email

        session["conversation_turn_count"] = 3
        self.assertFalse(should_request_email(session))

    def test_talking_about_booking_gets_the_invite(self):
        out = apply_video_call_close("El 18+2 sale USD 7.250.", "Quiero hablar con mi esposa antes de reservar, ¿me pasás el precio?", {}, "es")
        self.assertTrue(out.startswith("El 18+2 sale USD 7.250.\n\nSi querés, armamos una videollamada"))

    def test_no_email_ask_when_we_already_have_it(self):
        out = apply_video_call_close("Dale.", "quiero reservar", {"captured_email": "a@b.com"}, "es")
        self.assertNotIn("email", out)
        out = apply_video_call_close("Dale.", "quiero reservar, mi mail es a@b.com", {}, "es", has_email=True)
        self.assertNotIn("email", out)

    def test_offered_once_per_conversation(self):
        session = {"video_call_offered": True}
        self.assertEqual(apply_video_call_close("Ok.", "quiero reservar", session, "es"), "Ok.")

    def test_reply_that_already_invites_is_left_alone(self):
        session: dict = {}
        reply = "Si querés hacemos una videollamada. ¿Qué día te queda bien?"
        self.assertEqual(apply_video_call_close(reply, "quiero reservar", session, "es"), reply)
        self.assertTrue(session["video_call_offered"])

    def test_plain_questions_get_no_invite(self):
        self.assertEqual(apply_video_call_close("No está incluido.", "¿El permiso está incluido?", {}, "es"), "No está incluido.")

    def test_english(self):
        out = apply_video_call_close("The 18+2 is USD 7,250.", "I want to book the 18+2", {}, "en")
        self.assertIn("short video call", out)


class ExtendedAlternativeTests(unittest.TestCase):
    def test_departures_are_parsed_per_program(self):
        self.assertEqual(set(DEPARTURES), {"18+2", "14+2", "12+2", "17+2"})
        self.assertIn(date(2026, 12, 5), DEPARTURES["14+2"])
        self.assertIn(date(2027, 1, 31), DEPARTURES["18+2"])

    def test_short_program_date_gets_the_nearest_18_plus_2(self):
        # Regression: picking 5/12 (14+2) never offered the 18+2 of 4/12.
        note = extended_alternative_note("Me interesa la del 5/12", DEPARTURES, TODAY, "es")
        self.assertIn("esa salida es del 14+2", note)
        self.assertIn("la salida más cercana es el 4/12", note)

    def test_no_note_for_18_plus_2_or_polish_dates_or_experienced_climbers(self):
        for text in ("Me interesa la del 4/12", "Me interesa la del 1/12", "Estuve a 6.400 m, me interesa la del 5/12", "¿Qué fechas tienen?"):
            with self.subTest(text=text):
                self.assertIsNone(extended_alternative_note(text, DEPARTURES, TODAY, "es"))

    def test_past_18_plus_2_departures_are_not_offered(self):
        # On 5 Dec the 18+2 of 4/12 is gone: the next one is 20/12.
        note = extended_alternative_note("I'm interested in the 5/12 one", DEPARTURES, date(2026, 12, 5), "en")
        self.assertIn("closest departure is on 20/12", note)

    def test_note_goes_between_the_answer_and_the_invite(self):
        note = extended_alternative_note("Me interesa la del 5/12", DEPARTURES, TODAY, "es")
        out = apply_video_call_close("El 5/12 es del 14+2.", "Me interesa la del 5/12", {}, "es", extra_note=note)
        self.assertLess(out.index("4/12"), out.index("videollamada"))
        self.assertIn("La disponibilidad de esa fecha te la confirma un asesor.", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
