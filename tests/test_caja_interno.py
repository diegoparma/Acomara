#!/usr/bin/env python3
"""Tests for the team-phone route to the internal cash-flow agent.

A local HTTP stub plays the agent (aconcagua-plan-admin api/agente.js). No
OpenAI, no Supabase. Run with:
    python3 tests/test_caja_interno.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import caja_interno  # noqa: E402

KEY = "k" * 40
TEAM = "5492615551111"


class StubAgent(BaseHTTPRequestHandler):
    calls: list[dict] = []
    down = False

    def log_message(self, *args):  # keep test output clean
        pass

    def _reply(self, status: int, body: dict) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        StubAgent.calls.append({"path": self.path})
        if StubAgent.down:
            return self._reply(500, {})
        if self.headers.get("Authorization") != f"Bearer {KEY}":
            return self._reply(401, {})
        self._reply(200, {"telefonos": [TEAM]})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        StubAgent.calls.append({"path": self.path, "body": body})
        if StubAgent.down:
            return self._reply(500, {})
        handled = caja_interno._same_phone(caja_interno._digits(body["telefono"]), TEAM)
        self._reply(200, {"manejado": True, "respuesta": f"eco: {body['texto']}"} if handled else {"manejado": False})


class CajaInternoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), StubAgent)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/api/agente"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        StubAgent.calls = []
        StubAgent.down = False
        caja_interno._team_cache.update(at=0.0, phones=frozenset())
        os.environ["CAJA_AGENTE_URL"] = self.url
        os.environ["CAJA_AGENT_KEY"] = KEY

    def tearDown(self):
        os.environ.pop("CAJA_AGENTE_URL", None)
        os.environ.pop("CAJA_AGENT_KEY", None)

    def test_off_without_env_and_no_network(self):
        os.environ.pop("CAJA_AGENTE_URL")
        self.assertIsNone(caja_interno.internal_reply(TEAM, "hola"))
        self.assertEqual(StubAgent.calls, [])

    def test_client_goes_to_sales(self):
        self.assertIsNone(caja_interno.internal_reply("5491100000000", "cuánto sale?"))
        self.assertEqual([c["path"] for c in StubAgent.calls], ["/api/agente?a=equipo"])

    def test_team_phone_in_other_format_goes_to_agent(self):
        reply = caja_interno.internal_reply("+54 9 261 555-1111", "pagué 120 mil de mulas")
        self.assertEqual(reply, "eco: pagué 120 mil de mulas")

    def test_team_list_is_cached(self):
        caja_interno.internal_reply("5491100000000", "a")
        caja_interno.internal_reply("5491100000001", "b")
        self.assertEqual(sum(c["path"].endswith("a=equipo") for c in StubAgent.calls), 1)

    def test_agent_down_does_not_touch_clients(self):
        StubAgent.down = True
        self.assertIsNone(caja_interno.internal_reply("5491100000000", "hola"))

    def test_agent_down_tells_team_member(self):
        caja_interno.internal_reply("5491100000000", "warm the cache")
        StubAgent.down = True
        self.assertEqual(caja_interno.internal_reply(TEAM, "ok"), caja_interno.UNAVAILABLE_REPLY)

    def test_removed_from_team_falls_back_to_sales(self):
        caja_interno._team_cache.update(at=10**12, phones=frozenset({"5492619990000"}))
        self.assertIsNone(caja_interno.internal_reply("5492619990000", "hola"))


class EndpointTest(unittest.TestCase):
    """The completion Nico returns for a team phone, through the real endpoint."""

    def test_team_phone_gets_agent_reply_as_completion(self):
        from unittest import mock
        from orchestrator import server

        os.environ.setdefault("ORCHESTRATOR_API_KEY", "test-key")
        with mock.patch.object(server, "internal_reply", return_value="Te propongo esto: ..."), \
             mock.patch.object(server, "is_authorized_for_chat", return_value=True):
            resp = server.app.test_client().post(
                "/v1/chat/completions",
                json={"model": "gpt-4.1-mini", "messages": [{"role": "user", "content": "pagué 120 mil"}]},
                headers={"contact-address": TEAM, "conversation-id": "c1"},
            )
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["choices"][0]["message"]["content"], "Te propongo esto: ...")


if __name__ == "__main__":
    unittest.main(verbosity=2)
