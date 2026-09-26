#!/usr/bin/env python3
"""Unit tests for bot detection when a client shares an email."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.security import bot_signal  # noqa: E402


class BotSignalTests(unittest.TestCase):
    def test_real_lead_without_breach_history_is_not_a_bot(self):
        # Regression (audit 2026-09): 29 of 33 paused leads had chatted 3+ times first.
        session = {"conversation_turn_count": 5}
        self.assertIsNone(bot_signal(session, "si, por favor! ana@gmail.com", "ana@gmail.com", email_in_breaches=False))

    def test_bare_email_first_without_breach_history_is_a_bot(self):
        session = {"conversation_turn_count": 1}
        self.assertEqual(
            bot_signal(session, "x7k2@gmail.com", "x7k2@gmail.com", email_in_breaches=False),
            "bare_email_without_conversation",
        )

    def test_bare_email_first_with_breach_history_is_not_a_bot(self):
        session = {"conversation_turn_count": 1}
        self.assertIsNone(bot_signal(session, "ana@gmail.com", "ana@gmail.com", email_in_breaches=True))

    def test_early_email_with_real_message_is_not_a_bot(self):
        session = {"conversation_turn_count": 1}
        text = "Hola, quiero info de la expedición de enero, mi mail es ana@gmail.com"
        self.assertIsNone(bot_signal(session, text, "ana@gmail.com", email_in_breaches=False))

    def test_many_distinct_emails_is_a_bot(self):
        session = {"conversation_turn_count": 6, "emails_seen": ["a@x.com", "b@x.com"]}
        self.assertEqual(
            bot_signal(session, "c@x.com", "c@x.com", email_in_breaches=True),
            "many_distinct_emails",
        )

    def test_same_email_repeated_is_not_many(self):
        session = {"conversation_turn_count": 6, "emails_seen": ["Ana@Gmail.com"]}
        self.assertIsNone(bot_signal(session, "ana@gmail.com", "ana@gmail.com", email_in_breaches=True))


if __name__ == "__main__":
    unittest.main()
