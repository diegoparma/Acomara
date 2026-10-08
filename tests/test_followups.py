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

from orchestrator.humanize import append_recent_turns  # noqa: E402
from orchestrator.server import (  # noqa: E402
    OUTBOUND_DUPLICATE_BURST_SECONDS,
    apply_email_ack_or_request_policy,
    asks_if_bot,
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
