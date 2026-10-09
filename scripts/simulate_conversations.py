#!/usr/bin/env python3
"""Run scripted client conversations against the real Nico, with the real model.

Uses OPENAI_API_KEY from .env and calls OpenAI for real, but touches nothing
else: the session lives in memory, the CRM and Supabase are skipped, no emails
are sent and email verification is off. Prints every reply and the token usage
per reply, so two versions can be compared side by side.

Usage:
    python3 scripts/simulate_conversations.py               # all scenarios
    python3 scripts/simulate_conversations.py --only memoria
    python3 scripts/simulate_conversations.py --out results.json

To compare with the version in production, run it on each branch:
    git checkout main && python3 scripts/simulate_conversations.py --out before.json
    git checkout claude/nico-humano-experimento && python3 scripts/simulate_conversations.py --out after.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from orchestrator import server  # noqa: E402

RealOpenAI = server.OpenAI

SCENARIOS: dict[str, list[str]] = {
    "memoria": [
        "Hola",
        "Somos 3 amigos de Córdoba y queremos ir en enero",
        "Nunca subimos más de 4000 metros",
        "¿Qué programa nos conviene entonces?",
        "¿Y cuánto sale?",
    ],
    "email_con_pregunta": [
        "Hola, quiero info del Aconcagua",
        "¿Qué incluye la expedición?",
        "Mi mail es prueba.nico@example.com, ¿el permiso del parque está incluido?",
    ],
    "fechas_y_temporada": [
        "Hola! Qué fechas de salida tienen?",
        "Me interesa la del 5/12",
        "¿Y se puede ir en julio?",
    ],
    "ingles": [
        "Hi, I'm interested in climbing Aconcagua",
        "I have climbed Kilimanjaro, is the 14+2 ok for me?",
        "Thanks!",
    ],
    "pregunta_bot": [
        "Hola",
        "¿Sos un bot o una persona?",
        "Ok, ¿qué diferencia hay entre la ruta normal y el glaciar polaco?",
    ],
    "pareja": [
        "Hola, estoy viendo el 18+2",
        "Quiero hablar con mi esposa antes de reservar, ¿me pasás el precio?",
    ],
    "datos": [
        "¿El permiso del parque está incluido en el precio?",
        "Nunca estuve en altura, ¿qué programa me conviene?",
        "¿Y cuánto sale?",
    ],
}

# Facts that must hold (from docs/knowledge/datos-clave.md). Keyed by
# (scenario, turn index): regexes the reply must / must not match.
# Current prices per Fernando (docs/knowledge/datos-clave.md); 6.990 is the old one.
_PRICE = r"7[.,]?250|5[.,]?990|6[.,]?390"
_OLD_PRICE = r"6[.,]?990"
FACT_CHECKS: dict[tuple[str, int], dict[str, list[str]]] = {
    ("datos", 0): {
        "must": [r"no (est[aá] )?incluid|aparte|not included|por separado"],
        "must_not": [r"(?<!no )(?<!not )\b(est[aá]|is) included\b", r"(?<!no )est[aá] incluido"],
    },
    ("datos", 1): {"must": [r"18\+2"], "must_not": [r"\b1[24]\+2\b[^.]*recomend"]},
    ("datos", 2): {"must": [_PRICE], "must_not": [_OLD_PRICE]},
    ("memoria", 4): {"must": [_PRICE], "must_not": [_OLD_PRICE]},
    ("email_con_pregunta", 1): {"must": [r"hotel|comidas|mulas|porteador|gu[ií]as"]},
    ("ingles", 1): {"must": [r"18\+2"], "must_not": [r"14\+2[^.]*\b(?:suitable|could suit|can suit|good fit|ok for you)", r"14\+2(?:(?!18\+2)[^.;])*(extra|extended|more|additional)(?:(?!18\+2)[^.;])*acclimati"]},
    ("fechas_y_temporada", 0): {"must": [r"(?i)nov"]},
    ("fechas_y_temporada", 1): {"must": [r"14\+2", r"videollamada", r"disponibilidad"]},
    ("pareja", 1): {"must": [_PRICE, r"videollamada"], "must_not": [_OLD_PRICE]},
}

# What gives a reply away as a bot, checked on every reply.
TELLS = {
    "markdown_bold": re.compile(r"\*\*"),
    "em_dash": re.compile(r"—"),
    "assistant_closer": re.compile(
        r"hay algo m[aá]s en (lo )?que|no dudes en|estoy aqu[ií] para|anything else i can help|feel free to",
        re.IGNORECASE,
    ),
    "mentions_docs": re.compile(r"\bFAQ\b|documentaci[oó]n|base de (datos|conocimiento)", re.IGNORECASE),
    "asesor_humano": re.compile(r"asesor humano|human advisor", re.IGNORECASE),
}
# Claims the client already gave an email; checked only while they haven't.
PHANTOM_EMAIL = re.compile(
    r"(?:e-?mail|mail|correo) que me (?:pasaste|diste|compartiste|mandaste)|the email you (?:sent|gave|shared)",
    re.IGNORECASE,
)
CLIENT_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
EMAIL_WORD = re.compile(r"\b(e-?mail|correo)\b", re.IGNORECASE)
GREETING = re.compile(r"^\s*(¡\s*)?(hola|hi|hello|ol[aá])\b", re.IGNORECASE)


class _Session:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {}

    def get(self, base_url, conversation_id):
        stored = self.store.get(conversation_id)
        return {"variables": dict(stored)} if stored is not None else None

    def upsert(self, base_url, msg, agent_id, variables):
        self.store[msg["conversation_id"]] = dict(variables)


def _reply_text(completion: dict) -> str:
    message = completion["choices"][0]["message"]
    if message.get("content"):
        return message["content"]
    parts = []
    for call in message.get("tool_calls") or []:
        args = json.loads(call["function"]["arguments"])
        parts.extend(m.get("text", "") for m in args.get("messages", []))
    return "\n\n".join(parts)


def run(only: str | None) -> dict:
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("Missing OPENAI_API_KEY (put it in .env)")
    session = _Session()
    usage: list[dict] = []

    class RecordingOpenAI:
        """Real OpenAI client that records token usage of every reply."""

        def __init__(self, api_key):
            self._client = RealOpenAI(api_key=api_key)
            self.embeddings = self._client.embeddings
            self.responses = self

        def create(self, **kwargs):
            resp = self._client.responses.create(**kwargs)
            raw = getattr(resp, "usage", None)
            details = getattr(raw, "input_tokens_details", None)
            usage.append(
                {
                    "input_tokens": int(getattr(raw, "input_tokens", 0) or 0),
                    "cached_input_tokens": int(getattr(details, "cached_tokens", 0) or 0),
                    "output_tokens": int(getattr(raw, "output_tokens", 0) or 0),
                }
            )
            return resp

    env = {
        "ORCHESTRATOR_API_KEY": "simulation",
        "SESSION_AGENT_BASE_URL": "http://simulation.local",
        "HUMAN_SILENCE_HOURS": "0",
        "EMAIL_VERIFICATION_ENABLED": "false",
        "HANDOFF_EMAIL_TO": "",
    }
    not_sent = lambda *a, **k: (False, 0, {"info": "simulation"})  # noqa: E731
    patches = [
        mock.patch.dict(os.environ, env),
        mock.patch.object(server, "try_session_get", session.get),
        mock.patch.object(server, "try_session_upsert", session.upsert),
        mock.patch.object(server, "try_session_append_event", lambda *a, **k: None),
        mock.patch.object(server, "try_session_delete", lambda *a, **k: None),
        mock.patch.object(server, "check_client_status", lambda **k: {}),
        mock.patch.object(server, "human_replied_recently", lambda **k: (False, {})),
        mock.patch.object(server, "try_send_handoff_email", not_sent),
        mock.patch.object(server, "try_send_new_lead_email", not_sent),
        mock.patch.object(server, "try_send_suspicious_admin_alert", lambda *a, **k: (False, 0, {}, False, "simulation")),
    ]
    patches.append(mock.patch.object(server, "OpenAI", RecordingOpenAI))
    for patch in patches:
        patch.start()

    client = server.app.test_client()
    results: dict = {
        "scenarios": {},
        "tells": {k: 0 for k in TELLS},
        "repeated_greetings": 0,
        "empty_replies": 0,
        "email_asked_twice_in_one_message": 0,
        "identical_replies": 0,
        "phantom_email": 0,
        "fact_checks": {"passed": 0, "failed": []},
    }
    seen_sentences: dict[str, int] = {}
    for name, turns in SCENARIOS.items():
        if only and name != only:
            continue
        print(f"\n=== {name} ===")
        conversation_id = f"sim-{name}"
        transcript = []
        client_gave_email = False
        for i, text in enumerate(turns):
            client_gave_email = client_gave_email or bool(CLIENT_EMAIL.search(text))
            before = len(usage)
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "nico", "messages": [{"role": "user", "content": text}]},
                headers={
                    "Authorization": "Bearer simulation",
                    "conversation-id": conversation_id,
                    "contact-id": conversation_id,
                    "contact-address": "+540000000000",
                },
            )
            reply = _reply_text(resp.get_json()) if resp.status_code == 200 else f"[HTTP {resp.status_code}]"
            turn_usage = usage[before:]
            print(f"\nCliente: {text}\nNico:    {reply}")
            if turn_usage:
                u = turn_usage[-1]
                print(f"         [{u['input_tokens']} in / {u['cached_input_tokens']} cached / {u['output_tokens']} out]")
            for tell, pattern in TELLS.items():
                if pattern.search(reply):
                    results["tells"][tell] += 1
            if i > 0 and GREETING.search(reply) and not GREETING.search(text):
                results["repeated_greetings"] += 1
            if not reply.strip():
                results["empty_replies"] += 1
            if not client_gave_email and PHANTOM_EMAIL.search(reply):
                results["phantom_email"] += 1
                print("         ✗ menciona un email que el cliente no dio")
            if len(EMAIL_WORD.findall(reply)) >= 2:
                results["email_asked_twice_in_one_message"] += 1
            # The same long sentence word for word across replies reads as canned.
            for sentence in re.split(r"(?<=[.!?])\s+", reply):
                key = sentence.strip().lower()
                if len(key) >= 40:
                    seen_sentences[key] = seen_sentences.get(key, 0) + 1
                    if seen_sentences[key] == 2:
                        results["identical_replies"] += 1
            check = FACT_CHECKS.get((name, i))
            if check:
                problems = [f"falta /{rx}/" for rx in check.get("must", []) if not re.search(rx, reply, re.IGNORECASE)]
                problems += [f"no debería /{rx}/" for rx in check.get("must_not", []) if re.search(rx, reply, re.IGNORECASE)]
                if problems:
                    results["fact_checks"]["failed"].append({"scenario": name, "turn": i, "client": text, "problems": problems})
                    print(f"         ✗ dato: {'; '.join(problems)}")
                else:
                    results["fact_checks"]["passed"] += 1
            transcript.append({"client": text, "nico": reply, "usage": turn_usage})
        results["scenarios"][name] = transcript

    for patch in reversed(patches):
        patch.stop()

    calls = len(usage)
    total_in = sum(u["input_tokens"] for u in usage)
    total_out = sum(u["output_tokens"] for u in usage)
    results["usage"] = {
        "model_calls": calls,
        "input_tokens": total_in,
        "cached_input_tokens": sum(u["cached_input_tokens"] for u in usage),
        "output_tokens": total_out,
        "avg_input_per_call": round(total_in / calls) if calls else None,
        "avg_output_per_call": round(total_out / calls) if calls else None,
    }
    print("\n=== Resumen ===")
    summary_keys = (
        "fact_checks",
        "tells",
        "repeated_greetings",
        "empty_replies",
        "email_asked_twice_in_one_message",
        "identical_replies",
        "phantom_email",
        "usage",
    )
    print(json.dumps({k: results[k] for k in summary_keys}, indent=2, ensure_ascii=False))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", choices=sorted(SCENARIOS), help="run a single scenario")
    parser.add_argument("--out", help="save results as JSON")
    args = parser.parse_args()
    results = run(args.only)
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Guardado en {args.out}")


if __name__ == "__main__":
    main()
