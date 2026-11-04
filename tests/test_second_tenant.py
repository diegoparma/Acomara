#!/usr/bin/env python3
"""The same engine serves a second business: Aconcagua Basecamp (placeholder).

The server binds its tenant at import, so each check runs in a fresh Python
process with NICO_TENANT set, like a separate deploy would.

Run with:
    python3 tests/test_second_tenant.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBE = textwrap.dedent(
    """
    import json, sys
    from types import SimpleNamespace
    sys.path.insert(0, %(root)r)
    from orchestrator import server

    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text="Tenemos mulas y servicios de campamento.", status="completed")
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    runtime = {"rows": [], "top_k": 4, "embed_model": "e", "chat_model": "m",
               "system_prompt": server.load_system_prompt(), "history_turns": 0}
    server.retrieve_with_context = lambda *a, **k: []
    server.check_client_status = lambda **k: server.TENANT.integrations.crm_lookup(**k)

    def turn(text, turn_count):
        msg = server.InboundMessage(text=text, conversation_id="c1", organization_id="o", organization_address="a",
                                    contact_id="k", contact_address="", channel="whatsapp")
        ctx = server.ProcessingContext(session_vars={"conversation_turn_count": turn_count}, now_ts=1, inbound_signature="s")
        decision, _ = server.process_inbound_message(client, runtime, msg, ctx)
        return decision.reply

    print(json.dumps({
        "slug": server.TENANT.slug,
        "placeholder": server.TENANT.placeholder,
        "greeting": turn("Hola", 1),
        "bot": turn("¿Sos un bot?", 2),
        "options": turn("¿Qué opciones tienen?", 2),
        "short_program": turn("Me sirve el 14+2? Hice el Kilimanjaro", 2),
        "model_calls": len(calls),
        "system_prompt_has_abc": "Aconcagua Basecamp" in calls[0]["input"][0]["content"] if calls else False,
        "system_prompt_has_key_facts": "DATOS CLAVE" in calls[0]["input"][0]["content"] if calls else False,
        "out_of_season": server.mentions_out_of_season("Necesito mulas para julio en Plaza de Mulas"),
        "service": server.build_version_payload()["service"],
        "crm": server.check_client_status(phone="+54", email=""),
    }))
    """
)


def run_tenant(slug: str) -> dict:
    env = {**os.environ, "NICO_TENANT": slug}
    out = subprocess.run(
        [sys.executable, "-c", PROBE % {"root": str(ROOT)}],
        env=env, cwd=str(ROOT), capture_output=True, text=True, timeout=60,
    )
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return json.loads(out.stdout.strip().splitlines()[-1])


class SecondTenantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.abc = run_tenant("aconcagua_basecamp")

    def test_identity_and_fixed_phrases(self) -> None:
        self.assertEqual(self.abc["slug"], "aconcagua_basecamp")
        self.assertTrue(self.abc["placeholder"])
        self.assertIn("Aconcagua Basecamp", self.abc["greeting"])
        self.assertIn("Aconcagua Basecamp", self.abc["bot"])
        self.assertNotIn("Acomara", self.abc["bot"])
        self.assertEqual(self.abc["service"], "aconcagua-basecamp-orchestrator")

    def test_acomara_rules_do_not_leak(self) -> None:
        # No program guide and no 6,000 m hook: both go to the model.
        self.assertNotIn("18+2", self.abc["options"])
        self.assertNotIn("6.000", self.abc["short_program"])
        self.assertEqual(self.abc["model_calls"], 2)

    def test_own_knowledge_and_season(self) -> None:
        self.assertTrue(self.abc["system_prompt_has_abc"])
        self.assertTrue(self.abc["system_prompt_has_key_facts"])
        self.assertTrue(self.abc["out_of_season"])

    def test_no_crm_means_unknown_client(self) -> None:
        self.assertFalse(self.abc["crm"]["found"])


if __name__ == "__main__":
    unittest.main()
