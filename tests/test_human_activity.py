#!/usr/bin/env python3
"""Unit tests for the human-activity silence rule."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.human_activity import (  # noqa: E402
    human_replied_recently,
    is_human_message,
    last_human_message_at,
)

NICO = "nico-agent"
CLIENT = {"agent_id": None, "sender_address": "5491100000000", "timestamp": "2026-09-26T10:00:00+00:00"}
NICO_MSG = {"agent_id": NICO, "sender_address": None, "timestamp": "2026-09-26T10:01:00+00:00"}
PHONE_APP = {"agent_id": None, "sender_address": None, "timestamp": "2026-09-26T10:05:00+00:00"}
PLATFORM = {"agent_id": "fer-agent", "sender_address": None, "timestamp": "2026-09-26T10:03:00+00:00"}


class IsHumanMessageTests(unittest.TestCase):
    def test_client_message_is_not_human_reply(self):
        self.assertFalse(is_human_message(CLIENT, NICO))

    def test_nico_message_is_not_human_reply(self):
        self.assertFalse(is_human_message(NICO_MSG, NICO))

    def test_phone_app_message_is_human_reply(self):
        self.assertTrue(is_human_message(PHONE_APP, NICO))

    def test_platform_agent_message_is_human_reply(self):
        self.assertTrue(is_human_message(PLATFORM, NICO))

    def test_last_human_message_at_picks_latest_human(self):
        latest = last_human_message_at([CLIENT, NICO_MSG, PLATFORM, PHONE_APP], NICO)
        self.assertEqual(latest, datetime(2026, 9, 26, 10, 5, tzinfo=timezone.utc))

    def test_last_human_message_at_none_without_humans(self):
        self.assertIsNone(last_human_message_at([CLIENT, NICO_MSG], NICO))


class HumanRepliedRecentlyTests(unittest.TestCase):
    def call(self, **overrides):
        kwargs = {
            "supabase_url": "https://example.supabase.co",
            "supabase_key": "key",
            "conversation_id": "conv-1",
            "window_hours": 12,
            "nico_agent_id": NICO,
        }
        kwargs.update(overrides)
        return human_replied_recently(**kwargs)

    def mock_rows(self, rows):
        response = mock.Mock()
        response.json.return_value = rows
        response.raise_for_status.return_value = None
        return mock.patch("orchestrator.human_activity.requests.get", return_value=response)

    def test_silences_when_human_replied_in_window(self):
        with self.mock_rows([PHONE_APP, CLIENT]) as get:
            silenced, info = self.call()
        self.assertTrue(silenced)
        self.assertTrue(info["checked"])
        self.assertEqual(get.call_args.kwargs["params"]["conversation_id"], "eq.conv-1")

    def test_does_not_silence_without_human_messages(self):
        with self.mock_rows([CLIENT, NICO_MSG]):
            silenced, _ = self.call()
        self.assertFalse(silenced)

    def test_fails_open_on_error(self):
        with mock.patch("orchestrator.human_activity.requests.get", side_effect=TimeoutError()):
            silenced, info = self.call()
        self.assertFalse(silenced)
        self.assertFalse(info["checked"])

    def test_disabled_without_config_or_window(self):
        self.assertFalse(self.call(supabase_key=None)[0])
        self.assertFalse(self.call(window_hours=0)[0])


if __name__ == "__main__":
    unittest.main()
