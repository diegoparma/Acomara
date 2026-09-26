#!/usr/bin/env python3
"""Unit tests for the conversation audit helpers."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.conversation_audit import (  # noqa: E402
    _count_language_drift,
    _detect_language,
    _dominant_language,
    _paused_unanswered,
)


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


class PausedUnansweredTests(unittest.TestCase):
    PAUSED = {"extra": {"paused": "2026-09-10T12:00:00+00:00"}}

    def test_flags_user_messages_after_pause(self):
        messages = [
            {"role": "user", "text": "Hola", "timestamp": "2026-09-10T11:00:00+00:00"},
            {"role": "assistant", "text": "Te deriva un asesor", "timestamp": "2026-09-10T11:59:00+00:00"},
            {"role": "user", "text": "¿Hay novedades?", "timestamp": "2026-09-12T09:00:00+00:00"},
            {"role": "user", "text": "¿Hola?", "timestamp": "2026-09-14T09:00:00+00:00"},
        ]
        result = _paused_unanswered(self.PAUSED, messages)
        self.assertEqual(result["pending_user_messages"], 2)
        self.assertEqual(result["waiting_since"], "2026-09-12T09:00:00+00:00")

    def test_ignores_when_someone_replied_last(self):
        messages = [
            {"role": "user", "text": "¿Hay novedades?", "timestamp": "2026-09-12T09:00:00+00:00"},
            {"role": "assistant", "text": "Sí, te escribo por mail", "timestamp": "2026-09-12T10:00:00+00:00"},
        ]
        self.assertIsNone(_paused_unanswered(self.PAUSED, messages))

    def test_ignores_messages_sent_before_pause(self):
        messages = [{"role": "user", "text": "Hola", "timestamp": "2026-09-10T11:00:00+00:00"}]
        self.assertIsNone(_paused_unanswered(self.PAUSED, messages))

    def test_ignores_conversations_not_paused(self):
        messages = [{"role": "user", "text": "Hola", "timestamp": "2026-09-12T09:00:00+00:00"}]
        self.assertIsNone(_paused_unanswered({"extra": {}}, messages))
        self.assertIsNone(_paused_unanswered({"extra": None}, messages))


if __name__ == "__main__":
    unittest.main()