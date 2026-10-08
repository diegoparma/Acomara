#!/usr/bin/env python3
"""Season readiness: out-of-season detection and today's date in the prompt.

No network, no OpenAI. Run with:
    python3 tests/test_season.py
"""
from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.server import (  # noqa: E402
    apply_out_of_season_policy,
    generate_reply,
    mentions_out_of_season,
    today_in_argentina,
)


class OutOfSeasonFalsePositiveTests(unittest.TestCase):
    def test_ambiguous_numeric_date_in_season_is_not_flagged(self):
        # Regression: "5/12" is 5 December (a real 14+2 departure) for a
        # Spanish speaker, but was read as 12 May and got the warning.
        self.assertFalse(mentions_out_of_season("quiero la salida del 5/12"))
        self.assertFalse(mentions_out_of_season("salida del 4/1 para la expedicion"))

    def test_group_size_and_duration_ranges_are_not_dates(self):
        self.assertFalse(mentions_out_of_season("somos 4-6 personas para la expedicion"))
        self.assertFalse(mentions_out_of_season("expedicion de 5-7 dias"))
        self.assertFalse(mentions_out_of_season("we are 4-5 people for the expedition"))
        self.assertFalse(mentions_out_of_season("expedição para 4/6 pessoas"))

    def test_english_modal_may_is_not_the_month(self):
        self.assertFalse(mentions_out_of_season("May I climb Aconcagua in January?"))
        self.assertFalse(mentions_out_of_season("We may do the expedition in December"))

    def test_in_season_dates_are_not_flagged(self):
        for text in (
            "salida 20/12 para la expedicion",
            "expedition on 01/15",
            "expedicion el 15/01/2027",
            "expedition starting 2027-01-10",
        ):
            with self.subTest(text=text):
                self.assertFalse(mentions_out_of_season(text))


class OutOfSeasonTruePositiveTests(unittest.TestCase):
    def test_english_may_as_month(self):
        for text in ("expedition in may", "climb on May 12", "expedition 12th of May"):
            with self.subTest(text=text):
                self.assertTrue(mentions_out_of_season(text))

    def test_unambiguous_numeric_dates(self):
        for text in (
            "quiero subir el 15/05",  # only DD/MM is valid
            "expedition 05/27",  # only MM/DD is valid
            "salida 15/05/2027 expedicion",
            "expedicion el 4/6",  # both readings out of season
        ):
            with self.subTest(text=text):
                self.assertTrue(mentions_out_of_season(text))

    def test_month_names_in_three_languages(self):
        self.assertTrue(mentions_out_of_season("expedicion en septiembre"))
        self.assertTrue(mentions_out_of_season("trekking in october"))
        self.assertTrue(mentions_out_of_season("viagem em setembro"))


class OutOfSeasonPolicyTests(unittest.TestCase):
    def test_warns_once_per_conversation(self):
        session: dict = {}
        first = apply_out_of_season_policy("Respuesta.", "expedicion en julio", session, "es")
        second = apply_out_of_season_policy("Otra.", "y en agosto? expedicion", session, "es")
        self.assertTrue(first.startswith("Importante: las expediciones"))
        self.assertTrue(first.endswith("Respuesta."))
        self.assertEqual(second, "Otra.")
        self.assertTrue(session["out_of_season_warned"])

    def test_no_warning_for_in_season_request(self):
        session: dict = {}
        out = apply_out_of_season_policy("Respuesta.", "quiero la salida del 5/12", session, "es")
        self.assertEqual(out, "Respuesta.")
        self.assertNotIn("out_of_season_warned", session)

    def test_warning_follows_language(self):
        out = apply_out_of_season_policy("Reply.", "expedition in june", {}, "en")
        self.assertTrue(out.startswith("Heads up: Aconcagua expeditions"))


class TodayInArgentinaTests(unittest.TestCase):
    def test_converts_utc_to_argentina(self):
        # 02:00 UTC on 1 Dec is still 30 Nov in Mendoza (UTC-3).
        self.assertEqual(today_in_argentina(datetime(2026, 12, 1, 2, 0, tzinfo=timezone.utc)), date(2026, 11, 30))
        self.assertEqual(today_in_argentina(datetime(2026, 12, 1, 3, 0, tzinfo=timezone.utc)), date(2026, 12, 1))


class _FakeResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="  Respuesta  ")


class GenerateReplyDateTests(unittest.TestCase):
    def _run(self, **kwargs):
        client = SimpleNamespace(responses=_FakeResponses())
        msg = {"channel": "whatsapp", "conversation_id": "c1", "text": "Que fechas de salida tienen?"}
        reply = generate_reply(client, "model-x", "SYSTEM", msg, [], {"conversation_language": "es"}, **kwargs)
        user_prompt = client.responses.calls[0]["input"][1]["content"]
        return reply, user_prompt

    def test_prompt_includes_today_and_past_departure_rule(self):
        reply, prompt = self._run(today=date(2026, 12, 10))
        self.assertEqual(reply, "Respuesta")
        self.assertIn("Fecha de hoy (Argentina): 2026-12-10", prompt)
        self.assertIn("omite las que ya pasaron", prompt)

    def test_defaults_to_current_date(self):
        _, prompt = self._run()
        self.assertIn(f"Fecha de hoy (Argentina): {today_in_argentina().isoformat()}", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
