#!/usr/bin/env python3
"""Session store adapters keep the contract the engine relies on.

Run with:
    python3 tests/test_adapters.py
"""
from __future__ import annotations

import logging
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nico_core.adapters import InMemorySessionStore, SessionAgentStore, SessionStore  # noqa: E402

MSG = {"conversation_id": "c1", "organization_id": "o1", "contact_id": "k1"}


class InMemorySessionStoreTests(unittest.TestCase):
    def test_round_trip_and_isolation(self) -> None:
        store = InMemorySessionStore()
        self.assertIsInstance(store, SessionStore)
        self.assertIsNone(store.get("c1"))
        variables = {"recent_turns": [{"role": "user", "content": "hola"}]}
        store.upsert(MSG, "agent", variables)
        variables["recent_turns"].append({"role": "assistant", "content": "x"})  # caller keeps mutating
        got = store.get("c1")
        self.assertEqual(got["variables"], {"recent_turns": [{"role": "user", "content": "hola"}]})
        got["variables"]["x"] = 1
        self.assertNotIn("x", store.get("c1")["variables"])
        store.append_event("c1", "inbound", {"text": "hola"})
        self.assertEqual(store.events["c1"], [("inbound", {"text": "hola"})])
        store.delete("c1")
        self.assertIsNone(store.get("c1"))


class SessionAgentStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.calls: list[dict] = []

        def http_json(**kwargs):
            self.calls.append(kwargs)
            if kwargs["method"] == "GET":
                return 200, {"conversation_id": "c1", "variables": {"a": 1}}
            return 200, {}

        self.store = SessionAgentStore("http://session.test/", http_json, logging.getLogger("t"))

    def test_uses_the_session_agent_api(self) -> None:
        self.assertIsInstance(self.store, SessionStore)
        self.assertEqual(self.store.get("c1")["variables"], {"a": 1})
        self.store.upsert(MSG, "agent", {"a": 2})
        self.assertEqual(self.calls[0]["url"], "http://session.test/v1/sessions/c1")
        self.assertEqual(self.calls[1]["url"], "http://session.test/v1/sessions/upsert")
        self.assertEqual(self.calls[1]["body"]["variables"], {"a": 2})

    def test_no_base_url_means_no_session_and_no_calls(self) -> None:
        store = SessionAgentStore(None, lambda **k: self.fail("no call expected"), logging.getLogger("t"))
        self.assertIsNone(store.get("c1"))
        store.upsert(MSG, "agent", {})
        store.append_event("c1", "x", {})
        store.delete("c1")


if __name__ == "__main__":
    unittest.main()
