#!/usr/bin/env python3
"""Conversation memory and human-sounding output.

No network, no OpenAI. Run with:
    python3 tests/test_humanize.py
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.humanize import (  # noqa: E402
    MAX_RECENT_TURNS,
    append_recent_turns,
    assistant_already_spoke,
    history_to_messages,
    humanize_reply,
    trim_to_last_sentence,
)
from orchestrator.server import (  # noqa: E402
    I18N_PHRASES,
    build_reset_session_vars,
    choose_reply_bubbles,
    generate_reply,
    log_llm_usage,
)


class RecentTurnsTests(unittest.TestCase):
    def test_appends_user_and_assistant(self):
        turns = append_recent_turns([], "Hola, somos 3", "Genial, ¿para qué fecha?")
        self.assertEqual(
            turns,
            [
                {"role": "user", "text": "Hola, somos 3"},
                {"role": "assistant", "text": "Genial, ¿para qué fecha?"},
            ],
        )

    def test_suppressed_reply_keeps_only_the_client_message(self):
        turns = append_recent_turns([], "hola?", "")
        self.assertEqual(turns, [{"role": "user", "text": "hola?"}])

    def test_keeps_only_the_last_turns(self):
        turns: list = []
        for i in range(20):
            turns = append_recent_turns(turns, f"u{i}", f"a{i}")
        self.assertEqual(len(turns), MAX_RECENT_TURNS)
        self.assertEqual(turns[-1], {"role": "assistant", "text": "a19"})

    def test_long_messages_are_clipped(self):
        turns = append_recent_turns([], "x" * 5000, "")
        self.assertLessEqual(len(turns[0]["text"]), 600)

    def test_ignores_corrupt_stored_values(self):
        self.assertEqual(append_recent_turns("garbage", "hola", ""), [{"role": "user", "text": "hola"}])
        prior = [{"role": "system", "text": "x"}, {"role": "user"}, "str", {"role": "user", "text": "ok"}]
        self.assertEqual(append_recent_turns(prior, "", ""), [{"role": "user", "text": "ok"}])

    def test_history_to_messages(self):
        turns = append_recent_turns([], "Hola", "¡Hola! ¿En qué te ayudo?")
        self.assertEqual(
            history_to_messages(turns),
            [{"role": "user", "content": "Hola"}, {"role": "assistant", "content": "¡Hola! ¿En qué te ayudo?"}],
        )
        self.assertEqual(history_to_messages(None), [])

    def test_reset_clears_the_transcript(self):
        self.assertEqual(build_reset_session_vars(1000)["recent_turns"], [])

    def test_assistant_already_spoke(self):
        self.assertFalse(assistant_already_spoke([]))
        self.assertFalse(assistant_already_spoke([{"role": "user", "text": "hola"}]))
        self.assertTrue(assistant_already_spoke(append_recent_turns([], "hola", "hola!")))


class HumanizeReplyTests(unittest.TestCase):
    def test_markdown_bold_becomes_whatsapp_bold(self):
        self.assertEqual(humanize_reply("El **18+2** es el más elegido."), "El *18+2* es el más elegido.")

    def test_markdown_is_kept_out_of_other_channels_only_for_headings(self):
        self.assertEqual(humanize_reply("## Precios\nUSD 6.990", channel="web"), "Precios\nUSD 6.990")

    def test_markdown_links_become_plain_urls(self):
        out = humanize_reply("Mirá [el itinerario](https://acomara.com/18) cuando puedas.")
        self.assertEqual(out, "Mirá el itinerario: https://acomara.com/18 cuando puedas.")

    def test_em_dash_is_replaced_but_ranges_are_kept(self):
        self.assertEqual(
            humanize_reply("El 18+2 es el más completo — tiene más días de aclimatación."),
            "El 18+2 es el más completo, tiene más días de aclimatación.",
        )
        self.assertEqual(humanize_reply("Entre 4300–5000 m."), "Entre 4300–5000 m.")

    def test_no_second_greeting_once_the_conversation_started(self):
        self.assertEqual(
            humanize_reply("¡Hola! El precio es USD 6.990.", already_spoke=True),
            "El precio es USD 6.990.",
        )
        self.assertEqual(humanize_reply("Hi again! Sure, it's 20 days.", already_spoke=True), "Sure, it's 20 days.")
        # First reply keeps its greeting.
        self.assertEqual(humanize_reply("¡Hola! El precio es USD 6.990."), "¡Hola! El precio es USD 6.990.")

    def test_greeting_with_a_name_is_kept(self):
        self.assertEqual(humanize_reply("Hola Ana, sí, hay salida.", already_spoke=True), "Hola Ana, sí, hay salida.")

    def test_canned_assistant_phrases_are_removed(self):
        self.assertEqual(
            humanize_reply("¡Excelente pregunta! El permiso no está incluido. ¿Hay algo más en lo que pueda ayudarte?"),
            "El permiso no está incluido.",
        )
        self.assertEqual(
            humanize_reply("The permit is not included. Feel free to ask if you have more questions!"),
            "The permit is not included.",
        )
        self.assertEqual(
            humanize_reply("O permiso não está incluído. Fico à disposição para qualquer dúvida."),
            "O permiso não está incluído.",
        )

    def test_never_returns_empty(self):
        self.assertEqual(humanize_reply("¿Hay algo más en lo que pueda ayudarte?"), "¿Hay algo más en lo que pueda ayudarte?")
        self.assertEqual(humanize_reply(""), "")

    def test_fixed_phrases_are_already_clean(self):
        for lang, phrases in I18N_PHRASES.items():
            for key, text in phrases.items():
                if key == "repeat_prefix":  # a fragment glued to another reply
                    continue
                with self.subTest(lang=lang, key=key):
                    self.assertEqual(humanize_reply(text), text.strip())
                    self.assertNotIn("humano", text.lower())
                    self.assertNotIn("automat", text.lower())


class TrimToLastSentenceTests(unittest.TestCase):
    def test_cut_sentence_is_dropped(self):
        self.assertEqual(
            trim_to_last_sentence("El 18+2 tiene 20 días. Incluye porteadores en los campamentos de alt"),
            "El 18+2 tiene 20 días.",
        )

    def test_complete_reply_is_untouched(self):
        self.assertEqual(trim_to_last_sentence("Sale el 14 de noviembre."), "Sale el 14 de noviembre.")
        self.assertEqual(trim_to_last_sentence("Dale 👍"), "Dale 👍")

    def test_single_cut_sentence_is_kept(self):
        self.assertEqual(trim_to_last_sentence("El 18+2 tiene"), "El 18+2 tiene")


class ReplyBubblesTests(unittest.TestCase):
    def test_two_paragraphs_become_two_bubbles(self):
        self.assertEqual(choose_reply_bubbles("¡Gracias!\n\nSale USD 6.990.", True, False), ["¡Gracias!", "Sale USD 6.990."])

    def test_single_paragraph_stays_one_message(self):
        self.assertEqual(choose_reply_bubbles("Sale USD 6.990.", True, False), [])

    def test_long_lists_stay_in_one_message(self):
        self.assertEqual(choose_reply_bubbles("a\n\nb\n\nc\n\nd", True, False), [])

    def test_disabled_without_respond_tool(self):
        self.assertEqual(choose_reply_bubbles("a\n\nb", False, False), [])


class _FakeResponses:
    def __init__(self, text: str, status: str = "completed") -> None:
        self.text = text
        self.status = status
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.text, status=self.status)


class GenerateReplyMemoryTests(unittest.TestCase):
    def _run(self, session_vars, text="¡Hola! El 18+2 tiene **20 días**.", status="completed"):
        fake = _FakeResponses(text, status)
        client = SimpleNamespace(responses=fake)
        msg = {"channel": "whatsapp", "conversation_id": "c1", "text": "¿Cuántos días son?"}
        reply = generate_reply(client, "m", "SYSTEM", msg, [], session_vars, today=date(2026, 11, 2))
        return reply, fake.calls[0]["input"]

    def test_history_goes_to_the_model_as_chat_messages(self):
        session = {"recent_turns": append_recent_turns([], "Somos 3 de Córdoba", "¡Genial! ¿Para qué fecha?")}
        _, model_input = self._run(session)
        self.assertEqual([m["role"] for m in model_input], ["system", "user", "assistant", "user"])
        self.assertEqual(model_input[1]["content"], "Somos 3 de Córdoba")
        self.assertIn("no vuelvas a saludar", model_input[-1]["content"])

    def test_transcript_is_not_duplicated_in_session_dump(self):
        session = {
            "recent_turns": append_recent_turns([], "Somos 3", "Genial"),
            "last_assistant_reply": "Genial",
            "conversation_turn_count": 2,
        }
        _, model_input = self._run(session)
        prompt = model_input[-1]["content"]
        self.assertNotIn("recent_turns", prompt)
        self.assertNotIn("last_assistant_reply", prompt)
        self.assertIn("conversation_turn_count", prompt)

    def test_reply_is_humanized_after_the_first_message(self):
        session = {"recent_turns": append_recent_turns([], "Hola", "¡Hola! ¿En qué te ayudo?")}
        reply, _ = self._run(session)
        self.assertEqual(reply, "El 18+2 tiene *20 días*.")

    def test_first_reply_keeps_its_greeting(self):
        reply, model_input = self._run({})
        self.assertEqual(reply, "¡Hola! El 18+2 tiene *20 días*.")
        self.assertEqual([m["role"] for m in model_input], ["system", "user"])

    def test_history_can_be_limited_or_disabled(self):
        turns: list = []
        for i in range(5):
            turns = append_recent_turns(turns, f"u{i}", f"a{i}")
        fake = _FakeResponses("ok")
        client = SimpleNamespace(responses=fake)
        msg = {"channel": "whatsapp", "conversation_id": "c1", "text": "?"}
        generate_reply(client, "m", "S", msg, [], {"recent_turns": turns}, history_turns=2)
        generate_reply(client, "m", "S", msg, [], {"recent_turns": turns}, history_turns=0)
        self.assertEqual([m["content"] for m in fake.calls[0]["input"][1:-1]], ["u4", "a4"])
        self.assertEqual(len(fake.calls[1]["input"]), 2)

    def test_usage_is_logged_for_cost_tracking(self):
        usage = SimpleNamespace(input_tokens=5200, output_tokens=80, input_tokens_details=SimpleNamespace(cached_tokens=2560))
        record = log_llm_usage("c1", "gpt-4.1-mini", usage)
        self.assertEqual(
            record,
            {"conversation_id": "c1", "model": "gpt-4.1-mini", "input_tokens": 5200, "cached_input_tokens": 2560, "output_tokens": 80},
        )
        self.assertEqual(log_llm_usage("c1", "m", None), {})

    def test_truncated_reply_is_cut_at_the_last_full_sentence(self):
        reply, _ = self._run({}, text="El 18+2 tiene 20 días. Incluye porteadores en los campa", status="incomplete")
        self.assertEqual(reply, "El 18+2 tiene 20 días.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
