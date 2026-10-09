#!/usr/bin/env python3
"""Key facts in the system prompt and the advisor-answer extractor.

No network. Run with:
    python3 tests/test_knowledge_sources.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from extract_advisor_answers import build_advisor_exchanges, redact  # noqa: E402
from orchestrator.server import load_system_prompt  # noqa: E402

NICO = "nico-agent"


def _msg(text: str, *, client: bool = False, agent: str | None = None, ts: str = "2026-10-01T10:00:00Z") -> dict:
    return {
        "agent_id": agent,
        "sender_address": "+5492610000000" if client else None,
        "content": {"kind": "text", "text": text},
        "timestamp": ts,
    }


class KeyFactsTests(unittest.TestCase):
    def test_system_prompt_carries_the_key_facts(self):
        # Regression (simulation 2026-10-08): the permit was "included" in one
        # run and "not included" in the next.
        prompt = load_system_prompt()
        self.assertIn("DATOS CLAVE", prompt)
        self.assertIn("NO está incluido", prompt)
        self.assertIn("18+2", prompt)
        self.assertIn("USD 6.990", prompt)

    def test_short_programs_are_not_described_as_extended(self):
        # Regression: the 14+2 was described as having extra acclimatization days.
        facts = (ROOT / "docs" / "knowledge" / "datos-clave.md").read_text(encoding="utf-8")
        line_14 = next(line for line in facts.splitlines() if line.startswith("- 14+2"))
        self.assertIn("Saltea", line_14)


class RedactTests(unittest.TestCase):
    def test_emails_and_phones_are_removed(self):
        out = redact("Escribime a ana.p@gmail.com o al +54 9 261 555-1234")
        self.assertEqual(out, "Escribime a [email] o al [telefono]")

    def test_prices_dates_and_programs_survive(self):
        text = "Sale USD 6.990, salida 14/11, programa 18+2, 4.200 m"
        self.assertEqual(redact(text), text)


class AdvisorExchangeTests(unittest.TestCase):
    def test_pairs_advisor_answer_with_client_question_and_previous_nico_reply(self):
        messages = [
            _msg("Hola, ¿el permiso está incluido?", client=True),
            _msg("Eso no lo tengo confirmado.", agent=NICO),
            _msg("Che, ¿me confirman?", client=True),
            _msg("Hola! No, el permiso se paga aparte.", agent=None),  # phone app: no agent, no sender
            _msg("Te paso el detalle por mail.", agent="fer-platform"),
            _msg("Gracias!", client=True),
        ]
        exchanges = build_advisor_exchanges(messages, NICO)
        self.assertEqual(len(exchanges), 1)
        ex = exchanges[0]
        self.assertEqual(ex["client_asked"], ["Che, ¿me confirman?"])
        self.assertEqual(ex["nico_said_before"], "Eso no lo tengo confirmado.")
        self.assertEqual(ex["advisor_answer"], ["Hola! No, el permiso se paga aparte.", "Te paso el detalle por mail."])

    def test_non_text_messages_are_skipped_and_text_is_redacted(self):
        messages = [
            {"agent_id": None, "sender_address": "+549", "content": {"kind": "image"}, "timestamp": "t"},
            _msg("mi mail es x@y.com", client=True),
            _msg("Te escribo a x@y.com", agent="fer-platform"),
        ]
        ex = build_advisor_exchanges(messages, NICO)[0]
        self.assertEqual(ex["client_asked"], ["mi mail es [email]"])
        self.assertEqual(ex["advisor_answer"], ["Te escribo a [email]"])

    def test_conversation_without_advisor_has_no_exchanges(self):
        messages = [_msg("Hola", client=True), _msg("¡Hola! ¿En qué te ayudo?", agent=NICO)]
        self.assertEqual(build_advisor_exchanges(messages, NICO), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
