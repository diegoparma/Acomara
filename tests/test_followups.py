#!/usr/bin/env python3
"""Regressions found running Nico with the real model (simulation 2026-10-08).

- Follow-ups like "¿Y cuánto sale?" found nothing: retrieval used only the
  latest message.
- A repeated reply was dropped and the client got nothing.
- The email was asked twice in one message.
- "¿Sos un bot?" was dodged with "no lo tengo a mano".

No network. Run with:
    python3 tests/test_followups.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import json  # noqa: E402
from datetime import date  # noqa: E402

from orchestrator.departures import (  # noqa: E402
    ensure_departure_hit,
    filter_past_departures,
    is_departure_dates_entry,
    is_departure_dates_question,
)
from orchestrator.humanize import append_recent_turns  # noqa: E402
from orchestrator.server import (  # noqa: E402
    OUTBOUND_DUPLICATE_BURST_SECONDS,
    apply_email_ack_or_request_policy,
    asks_if_bot,
    is_generic_opening,
    is_thanks_only,
    build_contextual_query,
    resolve_duplicate_reply,
    retrieve_with_context,
)

ROWS = [
    {"id": "price-18", "question": "Precio 18+2", "answer": "USD 6.990", "embedding": [1.0, 0.0, 0.0]},
    {"id": "permit", "question": "Permiso", "answer": "No incluido", "embedding": [0.0, 1.0, 0.0]},
    {"id": "gear", "question": "Equipo", "answer": "Lista", "embedding": [0.0, 0.0, 1.0]},
]


class _FakeEmbeddings:
    """Embeds by keyword: '18+2' → price, 'permiso' → permit; a vague text is equally far from all."""

    def __init__(self) -> None:
        self.calls: list = []

    @staticmethod
    def _vector(text: str) -> list[float]:
        text = text.lower()
        return [0.1 + (1.0 if "18+2" in text else 0.0), 0.1 + (1.0 if "permiso" in text else 0.0), 0.1]

    def create(self, model, input):
        self.calls.append(input)
        inputs = input if isinstance(input, list) else [input]
        return SimpleNamespace(data=[SimpleNamespace(embedding=self._vector(t)) for t in inputs])


class ContextualRetrievalTests(unittest.TestCase):
    def test_query_includes_recent_turns(self):
        turns = append_recent_turns([], "Somos 3", "Para ustedes el 18+2 es ideal.")
        query = build_contextual_query("¿Y cuánto sale?", turns)
        self.assertTrue(query.startswith("¿Y cuánto sale?"))
        self.assertIn("18+2", query)

    def test_no_history_means_plain_query(self):
        self.assertEqual(build_contextual_query("Hola", None), "Hola")

    def test_follow_up_finds_what_was_being_discussed(self):
        # Regression: "¿Y cuánto sale?" after recommending the 18+2 found nothing.
        emb = _FakeEmbeddings()
        client = SimpleNamespace(embeddings=emb)
        turns = append_recent_turns([], "Somos 3 amigos", "Para ustedes el 18+2 es ideal.")
        hits = retrieve_with_context(client, "m", ROWS, "¿Y cuánto sale?", turns, top_k=1)
        self.assertEqual(hits[0]["id"], "price-18")
        self.assertEqual(len(emb.calls), 1, "one embeddings call with both inputs")
        self.assertEqual(len(emb.calls[0]), 2)

    def test_new_topic_is_not_pulled_back_to_the_old_one(self):
        client = SimpleNamespace(embeddings=_FakeEmbeddings())
        turns = append_recent_turns([], "Somos 3", "Para ustedes el 18+2 es ideal.")
        hits = retrieve_with_context(client, "m", ROWS, "¿El permiso está incluido?", turns, top_k=2)
        self.assertEqual({h["id"] for h in hits}, {"permit", "price-18"})
        self.assertEqual(len({h["id"] for h in hits}), len(hits), "no duplicated FAQ entries")


class DuplicateReplyTests(unittest.TestCase):
    def test_burst_duplicate_is_dropped(self):
        session = {"last_assistant_reply_ts": 1000}
        self.assertEqual(resolve_duplicate_reply("Sale USD 6.990.", session, 1000 + OUTBOUND_DUPLICATE_BURST_SECONDS, "es"), "")

    def test_asked_again_later_gets_an_answer(self):
        # Regression: the repeated reply was dropped and the client got nothing.
        session = {"last_assistant_reply_ts": 1000}
        out = resolve_duplicate_reply("Eso no lo tengo confirmado.", session, 1100, "es")
        self.assertEqual(out, "Como te decía, eso no lo tengo confirmado.")
        self.assertEqual(resolve_duplicate_reply("It's USD 6,990.", session, 1100, "en"), "As I mentioned, it's USD 6,990.")


class EmailAskedOnceTests(unittest.TestCase):
    def test_no_second_ask_when_the_reply_already_asks(self):
        session = {"conversation_turn_count": 3}
        reply = "Sale USD 6.990. Si querés, pasame tu email y te mando el detalle."
        out = apply_email_ack_or_request_policy(reply, session, None, "es")
        self.assertEqual(out, reply)
        self.assertTrue(session["email_requested"])

    def test_ask_is_added_when_the_reply_does_not(self):
        session = {"conversation_turn_count": 3}
        out = apply_email_ack_or_request_policy("Sale USD 6.990.", session, None, "es")
        self.assertIn("pasame tu email", out)


class BotQuestionTests(unittest.TestCase):
    def test_detects_the_question_in_three_languages(self):
        for text in (
            "¿Sos un bot o una persona?",
            "Eres un robot?",
            "sos una IA?",
            "hablo con una persona?",
            "Are you a bot?",
            "Am I talking to a real person?",
            "Você é um robô?",
        ):
            with self.subTest(text=text):
                self.assertTrue(asks_if_bot(text))

    def test_ordinary_questions_are_not_bot_questions(self):
        for text in (
            "Quiero hablar con una persona",
            "Somos 3 personas",
            "es un programa de 18 días?",
            "Is this a good program?",
            "E aí, tudo bem?",
            "El bot de la página no anda",
        ):
            with self.subTest(text=text):
                self.assertFalse(asks_if_bot(text))


FAQ_ROWS = [json.loads(line) for line in (ROOT / "docs" / "knowledge" / "faq_cloud_index.jsonl").open()]
DATES_ES = next(r for r in FAQ_ROWS if r["id"] == "faq-060")


class DepartureDatesTests(unittest.TestCase):
    def test_finds_the_dates_entries_in_the_real_faq(self):
        self.assertEqual({r["id"] for r in FAQ_ROWS if is_departure_dates_entry(r)}, {"faq-060", "faq-061"})

    def test_nothing_is_removed_before_the_season(self):
        # Regression: on 2026-10-08 the model dropped every Nov/Dec departure.
        self.assertEqual(filter_past_departures(DATES_ES["answer"], date(2026, 10, 8)), DATES_ES["answer"])

    def test_past_days_and_empty_months_are_removed(self):
        out = filter_past_departures(DATES_ES["answer"], date(2026, 12, 6))
        self.assertNotIn("Noviembre", out)
        self.assertNotIn("Diciembre: 5 |", out)  # 14+2 on 5 Dec is gone...
        self.assertIn("Diciembre: 10", out)  # ...10 Dec is still ahead
        self.assertIn("Diciembre: 7 | 12 | 26", out)
        self.assertIn("Enero: 2 | 10 | 31", out)

    def test_january_belongs_to_the_second_year_of_the_season(self):
        out = filter_past_departures(DATES_ES["answer"], date(2027, 1, 9))
        self.assertNotIn("Diciembre", out)
        self.assertIn("Enero: 10 | 31", out)

    def test_text_without_a_season_is_untouched(self):
        text = "Noviembre: 1 | 2 Diciembre: 3"
        self.assertEqual(filter_past_departures(text, date(2027, 1, 1)), text)

    def test_date_questions(self):
        for text in ("¿Qué fechas tienen?", "When are the departures?", "Quais são as datas?", "me interesa la del 5/12"):
            with self.subTest(text=text):
                self.assertTrue(is_departure_dates_question(text))
        self.assertFalse(is_departure_dates_question("¿Cuánto sale el 18+2?"))

    def test_dates_entry_is_forced_into_the_evidence(self):
        # Regression: "¿Qué fechas tienen?" alone did not retrieve the dates.
        other = [{"id": "gear", "question": "Equipo", "answer": "Lista", "score": 0.4}]
        hits = ensure_departure_hit(other, FAQ_ROWS, "¿Qué fechas tienen?", "es", top_k=4)
        self.assertEqual(hits[0]["id"], "faq-060")
        self.assertNotIn("embedding", hits[0])
        hits_en = ensure_departure_hit(other, FAQ_ROWS, "What dates do you have?", "en", top_k=4)
        self.assertEqual(hits_en[0]["id"], "faq-061")
        self.assertEqual(ensure_departure_hit(other, FAQ_ROWS, "¿Cuánto sale?", "es", top_k=4), other)


class SmallTalkTests(unittest.TestCase):
    def test_bare_thanks(self):
        for text in ("Thanks!", "gracias!!", "Muchas gracias por la info 🙏", "Thank you so much", "Obrigado!"):
            with self.subTest(text=text):
                self.assertTrue(is_thanks_only(text))
        for text in ("Gracias, y cuánto sale?", "gracias, somos 3 de Córdoba", "dale"):
            with self.subTest(text=text):
                self.assertFalse(is_thanks_only(text))

    def test_generic_first_message(self):
        for text in ("Hi, I'm interested in climbing Aconcagua", "Hola, quiero info", "Olá, gostaria de saber mais"):
            with self.subTest(text=text):
                self.assertTrue(is_generic_opening(text))
        for text in ("Hola, cuánto sale el 18+2?", "Hola, somos 3 y queremos ir en enero", "Info del 18+2"):
            with self.subTest(text=text):
                self.assertFalse(is_generic_opening(text))


if __name__ == "__main__":
    unittest.main(verbosity=2)
