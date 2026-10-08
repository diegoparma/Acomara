#!/usr/bin/env python3
"""End-to-end conversation through /v1/chat/completions.

OpenAI, session-agent, CRM and Supabase are replaced by in-memory fakes, so
this checks the real request flow: the transcript is stored, the model sees it
on the next message, and replies are split into WhatsApp bubbles.

Run with:
    python3 tests/test_conversation_flow.py
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import server  # noqa: E402

HEADERS = {
    "Authorization": "Bearer test-key",
    "conversation-id": "conv-flow",
    "contact-id": "lead-1",
    "contact-address": "+5492610000000",
    "organization-id": "acomara",
}


class _FakeModel:
    """Answers each model call with the next scripted reply."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs["input"])
        return SimpleNamespace(output_text=self.replies.pop(0), status="completed")


class ConversationFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict[str, dict] = {}
        self.model = _FakeModel([])
        env = {
            "OPENAI_API_KEY": "sk-test",
            "ORCHESTRATOR_API_KEY": "test-key",
            "SESSION_AGENT_BASE_URL": "http://session.test",
            "HUMAN_SILENCE_HOURS": "0",
            "EMAIL_VERIFICATION_ENABLED": "false",
            "OPENBSP_MULTI_MESSAGE_ENABLED": "true",
        }
        patches = [
            mock.patch.dict(os.environ, env),
            mock.patch.object(server, "load_local_env", lambda: None),
            mock.patch.object(server, "OpenAI", lambda api_key: SimpleNamespace(responses=self.model)),
            mock.patch.object(server, "retrieve_top_k", lambda *a, **k: []),
            mock.patch.object(server, "retrieve_with_context", lambda *a, **k: []),
            mock.patch.object(server, "try_session_get", self._session_get),
            mock.patch.object(server, "try_session_upsert", self._session_upsert),
            mock.patch.object(server, "try_session_append_event", lambda *a, **k: None),
            mock.patch.object(server, "try_session_delete", lambda *a, **k: None),
            mock.patch.object(server, "check_client_status", lambda **k: {}),
            mock.patch.object(server, "human_replied_recently", lambda **k: (False, {})),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        server.app.config["INDEX_ROWS"] = []
        self.client = server.app.test_client()

    def _session_get(self, base_url, conversation_id):
        stored = self.store.get(conversation_id)
        return {"variables": dict(stored)} if stored is not None else None

    def _session_upsert(self, base_url, msg, agent_id, variables):
        self.store[msg["conversation_id"]] = dict(variables)

    def _send(self, text: str, tools: bool = False) -> dict:
        body = {"model": "nico", "messages": [{"role": "user", "content": text}]}
        if tools:
            body["tools"] = [{"type": "function", "function": {"name": "respond"}}]
        resp = self.client.post("/v1/chat/completions", json=body, headers=HEADERS)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()

    @staticmethod
    def _text(completion: dict) -> str:
        return completion["choices"][0]["message"]["content"]

    def test_model_remembers_what_the_client_said(self):
        self.model.replies = [
            "¡Hola! Para 3 personas el 18+2 es ideal. ¿Tienen experiencia en altura?",
            "¡Hola! Perfecto, entonces el 18+2 les da más días de aclimatación.",
        ]
        self._send("Hola")  # fixed welcome, no model call
        first = self._text(self._send("Somos 3 amigos de Córdoba, queremos ir en enero"))
        second = self._text(self._send("Nunca subimos más de 4000"))

        self.assertIn("18+2", first)
        # No second greeting once the conversation is going; turn 3 adds the one-time email ask.
        self.assertTrue(second.startswith("Perfecto, entonces el 18+2 les da más días de aclimatación."))
        self.assertIn("pasame tu email", second)

        second_call = self.model.calls[1]
        roles = [m["role"] for m in second_call]
        self.assertEqual(roles[0], "system")
        self.assertEqual(roles[-1], "user")
        history = [m["content"] for m in second_call[1:-1]]
        self.assertIn("Somos 3 amigos de Córdoba, queremos ir en enero", history)
        self.assertIn(first, history)

        stored_turns = self.store["conv-flow"]["recent_turns"]
        self.assertEqual(stored_turns[-1], {"role": "assistant", "text": second})
        self.assertEqual(len(stored_turns), 6)

    def test_email_with_a_question_gets_both_bubbles(self):
        self.model.replies = ["El 18+2 sale USD 6.990, sujeto a disponibilidad."]
        self.store["conv-flow"] = {"conversation_turn_count": 2, "conversation_language": "es"}
        completion = self._send("Mi mail es ana@gmail.com, ¿cuánto sale el 18+2?", tools=True)
        message = completion["choices"][0]["message"]
        self.assertIn("tool_calls", message)
        self.assertIn("Ya tengo tu email", str(message["tool_calls"]))
        self.assertIn("USD 6.990", str(message["tool_calls"]))

    def test_single_paragraph_reply_is_one_message(self):
        self.model.replies = ["El permiso del Parque no está incluido en el precio."]
        self.store["conv-flow"] = {"conversation_turn_count": 5, "conversation_language": "es"}
        completion = self._send("¿El permiso está incluido?", tools=True)
        self.assertEqual(
            self._text(completion), "El permiso del Parque no está incluido en el precio."
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
