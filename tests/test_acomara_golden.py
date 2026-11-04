#!/usr/bin/env python3
"""Golden snapshot of Acomara's deterministic replies.

Nico is being split into a reusable core plus per-business config
(docs/sales-agent/17-nico-producto.md). This test pins every fixed phrase and
the output of the deterministic rules for a corpus of client messages, as they
were before the split. If a refactor changes a single character of what
Acomara's clients receive, it fails.

The snapshot lives in tests/golden/acomara_deterministic.json. Regenerate it
only for an intended behavior change:
    python3 tests/test_acomara_golden.py --update
"""
from __future__ import annotations

import json
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator import server  # noqa: E402
from orchestrator.departures import clarify_season_years, departures_by_program, filter_past_departures  # noqa: E402
from orchestrator.sales_rules import (  # noqa: E402
    apply_video_call_close,
    extended_alternative_note,
    short_program_reply,
)

GOLDEN_PATH = ROOT / "tests" / "golden" / "acomara_deterministic.json"
LANGS = ("es", "en", "pt", "fr", None)

MESSAGES = [
    "Hola",
    "Hi",
    "Olá",
    "Buenas tardes, quiero info del Aconcagua",
    "Hi, I'm interested in climbing Aconcagua",
    "Gostaria de saber sobre a expedição",
    "Gracias!",
    "Thanks so much for the info",
    "Quiero hablar con un asesor",
    "quiero hablar con mi esposa",
    "Can I talk to a real person?",
    "Quero falar com um atendente",
    "¿Sos un bot?",
    "Are you a robot?",
    "Estou falando com uma pessoa?",
    "¿Qué opciones tienen?",
    "What options do you have?",
    "¿Cuáles son las otras opciones?",
    "Me sirve el 14+2? Hice el Kilimanjaro",
    "Is the 12+2 ok for me? I climbed Mont Blanc",
    "Posso fazer o 14+2?",
    "Me sirve el 14+2? Subí el Chimborazo",
    "¿Diferencia entre el 14+2 y el 18+2?",
    "Queremos ir en julio al Aconcagua",
    "I'd like to climb in May",
    "May I ask about the expedition?",
    "Viagem em setembro",
    "Salida el 15/05",
    "Salida el 5/12",
    "Somos 4-6 personas para la expedición",
    "Me interesa la del 5/12",
    "Quiero reservar el 18+2",
    "Cuánto sale cancelar la reserva?",
    "English please",
    "en español por favor",
    "mi mail es juan@example.com",
    "/reset",
    "¿Qué fechas tienen?",
]

DATES_TEXT = (
    "Fechas de salida temporada 2026/27\n"
    "18+2 días | Ruta Normal (Extendido)\n"
    "Noviembre: 14 | 22\nDiciembre: 4 | 18\nEnero: 2 | 15\nFebrero: 1\n"
    "14+2 días | Ascenso Rápido\n"
    "Diciembre: 5 | 20\nEnero: 8\n"
    "12+2 días | Ascenso Extremo\n"
    "Enero: 10 | 24\n"
)

WHATSAPP_REPLIES = [
    DATES_TEXT,
    "Estas son las salidas: Extendido (18+2 días) Noviembre 14, 22; Diciembre 4, 18; Rápido (14+2 días) Diciembre 5, 20.",
    "Las fechas son:\n18+2 DÍAS | RUTA NORMAL (EXTENDIDO)\n- Noviembre: 14 | 22\n- Diciembre: 4 | 18",
    "No hay fechas en esta respuesta.",
]


def snapshot() -> dict:
    today = date(2026, 11, 4)
    departures = departures_by_program(DATES_TEXT)
    out: dict = {"phrases": {}, "messages": {}, "whatsapp": [], "dates": {}}
    for lang in LANGS:
        out["phrases"][str(lang)] = {key: server.get_phrase(key, lang) for key in server.I18N_PHRASES["es"]}
    out["phrases"]["missing_key"] = server.get_phrase("no_such_key", "en")
    for text in MESSAGES:
        row: dict = {
            "detect": server.detect_language_from_text(text),
            "detect_confident": server.detect_language_confident(text),
            "explicit_pref": server.detect_explicit_language_preference(text),
            "session_lang": server.get_session_language({"conversation_language": "es"}, text),
            "out_of_season": server.mentions_out_of_season(text),
            "handoff": server.wants_human_handoff(text),
            "asks_bot": server.asks_if_bot(text),
            "greeting": server._is_pure_greeting(text),
            "thanks": server.is_thanks_only(text),
            "generic_opening": server.is_generic_opening(text),
            "command": server.extract_command(text),
        }
        for lang in ("es", "en", "pt"):
            vars0: dict = {}
            first = server.build_program_options_guidance_reply(text, vars0, lang)
            vars1 = {"program_options_stage": 1}
            followup = server.build_program_options_guidance_reply(text, vars1, lang)
            row[f"options_{lang}"] = [first, vars0, followup, vars1]
            row[f"short_program_{lang}"] = short_program_reply(text, lang)
            row[f"extended_note_{lang}"] = extended_alternative_note(text, departures, today, lang)
            close_vars: dict = {}
            row[f"video_close_{lang}"] = [
                apply_video_call_close(
                    "Perfecto. ¿Querés que te cuente más?",
                    text,
                    close_vars,
                    lang,
                    extra_note=extended_alternative_note(text, departures, today, lang),
                    departures=departures,
                ),
                close_vars,
            ]
            oos_vars: dict = {}
            row[f"out_of_season_policy_{lang}"] = [
                server.apply_out_of_season_policy("Respuesta.", text, oos_vars, lang),
                oos_vars,
            ]
        out["messages"][text] = row
    for reply in WHATSAPP_REPLIES:
        out["whatsapp"].append(
            [server.format_whatsapp_departure_dates(reply, "whatsapp"), server.format_whatsapp_departure_dates(reply, "email")]
        )
    out["dates"] = {
        "filtered": filter_past_departures(DATES_TEXT, today),
        "clarified": clarify_season_years(DATES_TEXT),
        "by_program": {k: [d.isoformat() for d in v] for k, v in departures.items()},
    }
    out["blocked_reply"] = {lang: server.build_sensitive_outbound_block_reply(lang) for lang in ("es", "en", "pt")}
    out["paused"] = {
        reason: server.build_paused_reply({"pause_reason": reason, "conversation_language": "en"})
        for reason in ("human_handoff_in_progress", "proactive_email_request", "suspicious")
    }
    out["user_prompts"] = [_user_prompt(channel, text) for channel in ("whatsapp", "email") for text in MESSAGES[:6]]
    return json.loads(json.dumps(out, ensure_ascii=False, default=str))


def _user_prompt(channel: str, text: str) -> str:
    """The instructions the model receives for one message (the system prompt is checked apart)."""
    calls: list = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_text="ok", status="completed")

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    msg = {"text": text, "channel": channel, "conversation_id": "conv-golden"}
    hits = [{"id": "faq-007", "question": "¿Qué fechas tienen?", "answer": DATES_TEXT, "score": 0.9}]
    session_vars = {"conversation_turn_count": 2, "email_requested": True, "crm_client_found": False}
    server.generate_reply(client, "model-x", "SYSTEM", msg, hits, session_vars, today=date(2026, 11, 4))
    return calls[0]["input"][-1]["content"]


class AcomaraGoldenTests(unittest.TestCase):
    def test_deterministic_replies_match_snapshot(self) -> None:
        expected = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
        actual = snapshot()
        for section in expected:
            self.assertEqual(actual.get(section), expected[section], section)
        self.assertEqual(set(actual), set(expected))

    def test_system_prompt_is_prompt_file_plus_key_facts(self) -> None:
        # The files themselves are edited by other work; only how they are joined is pinned.
        prompt = (ROOT / "docs" / "sales-agent" / "02-system-prompt.md").read_text(encoding="utf-8")
        facts = (ROOT / "docs" / "knowledge" / "datos-clave.md").read_text(encoding="utf-8")
        expected = f"{prompt.rstrip()}\n\n--------------------------------------------------\n\n{facts}"
        self.assertEqual(server.load_system_prompt(), expected)


if __name__ == "__main__":
    if "--update" in sys.argv:
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(json.dumps(snapshot(), ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {GOLDEN_PATH}")
    else:
        unittest.main()
