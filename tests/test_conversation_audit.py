#!/usr/bin/env python3
"""Unit tests for the conversation audit helpers."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.conversation_audit import _count_language_drift, _detect_language, _dominant_language  # noqa: E402


class ConversationAuditLanguageDetectionTests(unittest.TestCase):
    def test_detects_spanish(self):
        self.assertEqual(
            _detect_language("Quisiera información sobre la expedición y fechas disponibles"),
            "es",
        )

    def test_detects_english(self):
        self.assertEqual(
            _detect_language("I would like information about the expedition and departure dates"),
            "en",
        )

    def test_detects_portuguese(self):
        self.assertEqual(
            _detect_language("Gostaria de informações sobre a expedição e as datas disponíveis"),
            "pt",
        )

    def test_detects_italian(self):
        self.assertEqual(
            _detect_language("Vorrei informazioni sulla spedizione e sulle date disponibili"),
            "it",
        )

    def test_detects_italian_with_aconcagua_context(self):
        self.assertEqual(
            _detect_language("Ciao è possibile avere delle informazioni sull'aconcagua?"),
            "it",
        )

    def test_detects_french(self):
        self.assertEqual(
            _detect_language("Je voudrais des informations sur lexpedition et les dates disponibles"),
            "fr",
        )

    def test_short_greetings_stay_unknown(self):
        self.assertEqual(_detect_language("Hola"), "unknown")
        self.assertEqual(_detect_language("Ciao"), "unknown")

    def test_dominant_language_ignores_unknown_when_signal_exists(self):
        self.assertEqual(_dominant_language(["unknown", "unknown", "en", "unknown", "en"]), "en")
        self.assertEqual(_dominant_language(["unknown", "unknown"]), "unknown")

    def test_turn_level_drift_uses_user_preference_lock(self):
        messages = [
            {"role": "user", "text": "English please"},
            {"role": "assistant", "text": "Hola, te paso información de fechas disponibles y precio."},
            {"role": "assistant", "text": "I can help you with dates and price options."},
        ]
        mismatches, _ = _count_language_drift(messages)
        self.assertEqual(mismatches, 1)

    def test_turn_level_drift_resets_by_segment(self):
        messages = [
            {"role": "user", "text": "English please"},
            {"role": "assistant", "text": "Hola, te paso información de fechas disponibles y precio."},
            {"role": "user", "text": "/reset"},
            {"role": "user", "text": "Hola, por favor en español"},
            {"role": "assistant", "text": "Claro, seguimos en español con información de fechas y precio."},
        ]
        mismatches, _ = _count_language_drift(messages)
        self.assertEqual(mismatches, 1)


if __name__ == "__main__":
    unittest.main()