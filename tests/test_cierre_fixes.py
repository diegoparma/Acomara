#!/usr/bin/env python3
"""Regression tests for the fixed-reply fixes of the final pass (docs/sales-agent/19).

No network: OpenAI, session-agent, CRM and Supabase are in-memory fakes.

Run with:
    python3 tests/test_cierre_fixes.py
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import server  # noqa: E402
from orchestrator.policies import declines_or_defers_email, drop_repeated_email_ask  # noqa: E402
from orchestrator.usted import to_tuteo, to_usted  # noqa: E402

HEADERS = {
    "Authorization": "Bearer test-key",
    "conversation-id": "conv-cierre",
    "contact-id": "lead-1",
    "contact-address": "+5492610000000",
    "organization-id": "acomara",
}
_VOS = re.compile(r"\b(?:quer[eé]s|ten[eé]s|pod[eé]s|pasame|decime|contame|avisame|escrib[ií]s|dejás|mir[aá])\b", re.IGNORECASE)


class _FakeModel:
    def __init__(self) -> None:
        self.replies: list[str] = []
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        text = self.replies.pop(0) if self.replies else "El 18+2 cuesta USD 7.250."
        return SimpleNamespace(output_text=text, status="completed")


class _EndpointCase(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict[str, dict] = {}
        self.model = _FakeModel()
        env = {
            "OPENAI_API_KEY": "sk-test",
            "ORCHESTRATOR_API_KEY": "test-key",
            "SESSION_AGENT_BASE_URL": "http://session.test",
            "HUMAN_SILENCE_HOURS": "0",
            "EMAIL_VERIFICATION_ENABLED": "false",
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
            # The remote delete can fail: the reset must not depend on it.
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
        # Like the real store: upsert merges into what is already there.
        self.store.setdefault(msg["conversation_id"], {}).update(variables)

    def _send(self, text: str) -> str:
        body = {"model": "nico", "messages": [{"role": "user", "content": text}]}
        resp = self.client.post("/v1/chat/completions", json=body, headers=HEADERS)
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()["choices"][0]["message"]["content"]


class FirstMessageWithDataTests(_EndpointCase):
    def test_first_message_with_data_is_answered_not_welcomed(self):
        self.model.replies = ["Sin experiencia en altura te recomiendo el 18+2, que tiene más días de aclimatación."]
        reply = self._send("Hola, quiero info, nunca estuve en altura")
        self.assertEqual(self.model.calls, 1)
        self.assertIn("18+2", reply)

    def test_bare_greeting_and_bare_interest_keep_the_welcome(self):
        for text in ("Hola", "Buenas", "Hola, quiero info"):
            with self.subTest(text=text):
                self.store.clear()
                self.assertIn("En qué te puedo ayudar", self._send(text))
        self.assertEqual(self.model.calls, 0)

    def test_is_generic_opening_rejects_messages_with_data(self):
        for text in ("Hola, quiero info, nunca estuve en altura", "Hi, I'm interested, I have never been at altitude",
                     "Olá, quero informações, sou iniciante"):
            with self.subTest(text=text):
                self.assertFalse(server.is_generic_opening(text))


class ResetTests(_EndpointCase):
    def test_reset_through_chat_completions_clears_stale_state(self):
        self.store["conv-cierre"] = {
            "conversation_turn_count": 6, "customer_name": "Ana", "email_captured": True, "captured_email": "ana@example.com",
            "emails_seen": ["ana@example.com"], "email_received_acked": True, "out_of_season_warned": True,
            "thanks_reply_count": 3, "program_options_stage": 2, "email_declined": True, "recent_turns": [{"role": "user", "text": "x"}],
        }
        reply = self._send("/reset")
        self.assertIn("En qué te puedo ayudar", reply)
        state = self.store["conv-cierre"]
        self.assertEqual(state["conversation_turn_count"], 0)
        self.assertFalse(state["email_captured"])
        self.assertFalse(state["email_declined"])
        self.assertFalse(state["email_received_acked"])
        self.assertFalse(state["out_of_season_warned"])
        self.assertEqual(state["emails_seen"], [])
        self.assertEqual(state["captured_email"], "")
        self.assertEqual(state["program_options_stage"], 0)
        self.assertIsNone(state["customer_name"])
        # Next message is turn 1 again: the opening welcome, not a continuation.
        self.assertIn("En qué te puedo ayudar", self._send("Hola"))

    def test_command_with_decoration_still_resets(self):
        for text in ("/reset.", "/RESET", "﻿/reset", "/new!", '"/reset"'):
            with self.subTest(text=text):
                self.assertIn(server.extract_command(text), ("/reset", "/new"))
        self.assertIsNone(server.extract_command("hola /reset"))


class EmailNotAskedAgainTests(_EndpointCase):
    def test_deferral_detector(self):
        for text in ("Después te paso el mail", "prefiero no dar mi mail", "I'll send you my email later",
                     "depois te mando o email", "no quiero pasar mi correo"):
            with self.subTest(text=text):
                self.assertTrue(declines_or_defers_email(text))
        for text in ("mi mail es ana@example.com", "cuánto sale el 18+2?", "dale, lo pienso y te escribo"):
            with self.subTest(text=text):
                self.assertFalse(declines_or_defers_email(text))

    def test_model_email_ask_is_dropped_after_decline(self):
        reply = "El 18+2 cuesta USD 7.250. ¿Querés que te pase el detalle por email?"
        self.assertNotIn("email", drop_repeated_email_ask(reply, {"email_declined": True}))

    def test_no_proactive_ask_after_client_defers_it(self):
        self.model.replies = ["Claro, el 18+2 es el más completo.", "Son 18 días en total.", "Sale USD 7.250.", "Hay salidas en enero."]
        self._send("Hola, somos dos amigos de Córdoba")
        self._send("Después te paso el mail, ahora no lo tengo a mano")
        self._send("Cuántos días son?")
        last = self._send("Cuánto sale?")
        for reply in (last,):
            self.assertNotRegex(reply.lower(), r"pasame tu email|tu email")
        self.assertTrue(self.store["conv-cierre"]["email_declined"])

    def test_handoff_does_not_ask_for_an_email_already_given(self):
        self.model.replies = ["Perfecto."]
        self._send("Mi mail es ana.test@example.com, hola")
        reply = self._send("Quiero hablar con un asesor")
        self.assertNotIn("email", reply.lower())
        self.assertIn("asesor", reply.lower())


class PortugueseTests(_EndpointCase):
    def test_short_portuguese_is_detected(self):
        for text in ("quanto custa?", "O que está incluído? A permissão do parque está incluída?", "Boa tarde, tudo bem?",
                     "Já fiz cume no Aconcágua em 2022"):
            with self.subTest(text=text):
                self.assertEqual(server.detect_language_confident(text), "pt")

    def test_spanish_is_not_read_as_portuguese(self):
        for text in ("¿Está incluido el permiso del parque?", "Cuánto sale el seguro? Tengo dudas", "Hola, quiero info incluido"):
            with self.subTest(text=text):
                self.assertNotEqual(server.detect_language_confident(text), "pt")

    def test_every_spanish_phrase_has_a_portuguese_version(self):
        self.assertEqual(set(server.I18N_PHRASES["es"]), set(server.I18N_PHRASES["pt"]))
        self.assertEqual(set(server.I18N_PHRASES["es"]), set(server.I18N_PHRASES["en"]))

    def test_followup_program_options_in_portuguese(self):
        text = server._followup_program_options_reply("pt")
        self.assertIn("alternativas", text)
        self.assertNotIn("Las otras", text)

    def test_portuguese_client_gets_portuguese_welcome(self):
        self.assertIn("Como posso te ajudar", self._send("Boa tarde, tudo bem?"))


class NeverSilentTests(_EndpointCase):
    def test_burst_repeat_gets_a_short_alternative(self):
        session = {"last_assistant_reply_ts": 1000}
        seen = set()
        for _ in range(4):
            out = server.resolve_duplicate_reply("Sale USD 6.990.", session, 1005, "es")
            self.assertTrue(out.strip())
            seen.add(out)
        self.assertEqual(len(seen), 4)
        self.assertTrue(server.resolve_duplicate_reply("It's USD 6,990.", {"last_assistant_reply_ts": 1000}, 1005, "en").strip())
        self.assertIn("anterior", server.resolve_duplicate_reply("Custa USD 6.990.", {"last_assistant_reply_ts": 1000}, 1005, "pt"))

    def test_same_model_answer_twice_in_a_row_is_not_silent(self):
        same = "El 18+2 cuesta USD 7.250 por persona."
        self.model.replies = [same, same, same]
        self._send("Hola, somos dos amigos de Córdoba")
        first = self._send("Cuánto sale?")
        second = self._send("Cuánto sale?? no me contestaron")
        self.assertTrue(first.strip())
        self.assertTrue(second.strip())
        self.assertNotEqual(first, second)


class UstedVoseoTests(_EndpointCase):
    def test_new_fixed_phrases_have_usted_versions(self):
        for key in ("repeat_alt_1", "repeat_alt_2", "repeat_alt_3", "repeat_alt_4"):
            with self.subTest(key=key):
                self.assertFalse(_VOS.search(to_usted(server.I18N_PHRASES["es"][key])))
        self.assertEqual(to_usted("¿Estuviste en altura alguna vez?"), "¿Ha estado en altura alguna vez?")
        self.assertEqual(to_usted('Mirá "Crampons" en la lista'), 'Mire "Crampons" en la lista')

    def test_tuteo_client_gets_no_voseo(self):
        out = to_tuteo("Si querés, pasame tu email. Cualquier cosa me escribís por acá. Contame y decime.")
        self.assertFalse(_VOS.search(out), out)

    def test_formal_client_with_quisiera_gets_usted(self):
        self.model.replies = ["El 18+2 es el más completo."]
        self._send("Buenas tardes, quisiera información sobre la expedición")
        self.store["conv-cierre"]["conversation_turn_count"] = 2
        reply = self._send("¿Cuánto cuesta?")
        self.assertFalse(_VOS.search(reply), reply)

    def test_tuteo_client_end_to_end(self):
        self.model.replies = ["Claro. Si querés, pasame tu email y te mando todo."]
        self._send("Hola, tienes fechas para enero?")
        self.assertFalse(_VOS.search(self.store["conv-cierre"]["last_assistant_reply"]))


if __name__ == "__main__":
    unittest.main()
