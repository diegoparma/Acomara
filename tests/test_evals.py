#!/usr/bin/env python3
"""Deterministic parts of the eval harness (evals/): no model, no network.

Run with:
    python3 -m pytest tests/test_evals.py
"""
from __future__ import annotations

import io
import json
import os
import random
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals import checks  # noqa: E402
from evals.calibration import CASES, regex_results  # noqa: E402
from evals.judge import normalize_verdict, overall_score, render_transcript, stub_verdict  # noqa: E402
from evals.llm import ChatJSON, UsageTracker, cost_usd  # noqa: E402
from evals.personas import (  # noqa: E402
    INTENTS,
    LANGUAGES,
    STYLES,
    Persona,
    add_typos,
    burst,
    generate_personas,
    scripted_conversation,
)
from evals.report import compare, render_html, render_markdown, build_sections, summarize, write_outputs  # noqa: E402


def _persona(**kw) -> Persona:
    base = dict(
        id="t-0001", language="es_ar", country="Argentina", name="Ana", experience="none", group_size=2,
        budget="flexible", objection="none", style="normal", intent="info_seeker", max_turns=6, shares_email=True,
    )
    return Persona(**{**base, **kw})


def _turns(*pairs, paused=None):
    out = []
    for i, (client, nico) in enumerate(pairs):
        bubbles = nico if isinstance(nico, list) else ([nico] if nico else [])
        out.append({"turn": i, "client": [client], "nico": [bubbles], "errors": [], "paused": [bool(paused and i in paused)]})
    return out


def _codes(transcript, persona=None):
    return {f.code for f in checks.check_conversation(transcript, persona or _persona())}


class PersonaTests(unittest.TestCase):
    def test_same_seed_same_personas(self):
        a = [p.to_dict() for p in generate_personas(40, seed=3)]
        b = [p.to_dict() for p in generate_personas(40, seed=3)]
        c = [p.to_dict() for p in generate_personas(40, seed=4)]
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_dimensions_are_balanced(self):
        personas = generate_personas(len(INTENTS) * 8, seed=1)
        intents = Counter(p.intent for p in personas)
        self.assertEqual(set(intents.values()), {8})
        langs = Counter(p.language for p in personas)
        self.assertLessEqual(max(langs.values()) - min(langs.values()), 1)
        self.assertEqual(set(langs), set(LANGUAGES))
        self.assertEqual({p.style for p in personas}, set(STYLES))

    def test_constraints(self):
        for p in generate_personas(200, seed=9):
            if p.intent == "basecamp_only":
                self.assertNotIn(p.experience, ("none", "trekking_4000"))
            if p.intent == "family_decision":
                self.assertEqual(p.objection, "family")
            if p.intent == "troll_spam":
                self.assertFalse(p.shares_email)
            self.assertTrue(p.email.endswith("@example.com"))
            self.assertEqual(p.channel, "email" if p.style == "long_email" else "whatsapp")

    def test_scripted_conversation_respects_persona(self):
        for p in generate_personas(60, seed=2):
            turns = scripted_conversation(p)
            self.assertTrue(turns)
            self.assertLessEqual(len(turns), p.max_turns)
            self.assertTrue(all(isinstance(m, str) and m.strip() for t in turns for m in t))
            if p.style == "burst":
                self.assertTrue(any(len(t) > 1 for t in turns) or all(len(t[0].split()) < 6 for t in turns))
        self.assertEqual(scripted_conversation(generate_personas(5, 2)[3]), scripted_conversation(generate_personas(5, 2)[3]))

    def test_typos_keep_emails_and_numbers(self):
        text = add_typos("Mi correo es Ana.0001@example.com y somos 18+2 personas", random.Random(0))
        self.assertIn("Ana.0001@example.com", text)
        self.assertIn("18+2", text)
        self.assertEqual(text, text.replace("¿", ""))

    def test_burst_splits(self):
        self.assertEqual(burst("Hola, quería info. ¿Cuánto sale?"), ["Hola,", "quería info.", "¿Cuánto sale?"])
        self.assertEqual(burst("Hola"), ["Hola"])

    def test_brief_mentions_language_and_goal(self):
        brief = _persona(language="pt_br", intent="wants_human").brief()
        self.assertIn("português", brief)
        self.assertIn("persona del equipo", brief)


class CheckTests(unittest.TestCase):
    def test_calibration_cases_fire_exactly_the_expected_codes(self):
        for row in regex_results():
            with self.subTest(case=row["name"]):
                self.assertEqual(row["missing"], [])
                self.assertEqual(row["unexpected"], [])
        self.assertGreaterEqual(len(CASES), 12)

    def test_amounts(self):
        self.assertEqual(checks.amounts_in("USD 7.250 o US$ 5,990 y 699 dólares"), {7250, 5990, 699})
        self.assertEqual(checks.amounts_in("Somos 4 y vamos el 5/12, día 18"), set())
        clave, _ = checks.known_amounts()
        self.assertIn(7250, clave)
        self.assertNotIn(6990, clave)

    def test_current_prices_are_fine(self):
        codes = _codes(_turns(("cuánto sale?", "Sale USD 7.250, con promos entre USD 5.990 y USD 6.390 según la fecha.")))
        self.assertFalse(codes & {"OLD_PRICE", "INVENTED_PRICE"})

    def test_payment_fees_are_not_discounts(self):
        codes = _codes(_turns(("formas de pago?", "PayPal tiene 5,5% de comisión y la transferencia 3,8% de impuesto.")))
        self.assertNotIn("INVENTED_DISCOUNT", codes)

    def test_permit_not_included_is_fine(self):
        for text in ("El permiso del Parque no está incluido.", "The park permit is not included.", "O permiso não está incluído."):
            with self.subTest(text=text):
                self.assertNotIn("PERMIT_INCLUDED", _codes(_turns(("permiso?", text))))

    def test_short_program_rule_reply_is_fine(self):
        reply = "Te soy sincero: el 14+2 es solo para quien ya estuvo arriba de los 6.000 m. Te recomiendo el 18+2: cuesta lo mismo."
        self.assertNotIn("SHORT_PROGRAM_TO_INEXPERIENCED", _codes(_turns(("me sirve el 14+2?", reply))))
        # Someone who has been above 6,000 m can be offered the short ones.
        codes = _codes(_turns(("ya hice el Aconcagua", "Te recomiendo el 14+2.")), _persona(experience="aconcagua_before"))
        self.assertNotIn("SHORT_PROGRAM_TO_INEXPERIENCED", codes)

    def test_program_list_marking_12_2_recommended_is_flagged(self):
        reply = "I recommend starting with two options:\n1. 18+2 (highly recommended)\n2. 12+2 (recommended)"
        self.assertIn("SHORT_PROGRAM_TO_INEXPERIENCED", _codes(_turns(("info", reply)), _persona(language="en")))

    def test_declining_to_recommend_drugs_is_fine(self):
        for text in ("We do not recommend Diamox (acetazolamide) or any other drug.", "No recomendamos Diamox: consultá con un médico de montaña."):
            with self.subTest(text=text):
                self.assertNotIn("MEDICAL_ADVICE", _codes(_turns(("diamox?", text))))

    def test_email_asked_once_then_again_on_handoff_is_fine(self):
        t = _turns(
            ("hola", "Pasame tu email y te mando el detalle."),
            ("quiero hablar con un asesor", "Dale, te paso con un asesor. ¿Me dejás tu email así te contacta?"),
        )
        self.assertNotIn("EMAIL_ASKED_TWICE", _codes(t))

    def test_email_asked_after_given(self):
        t = _turns(("mi mail es ana@example.com", "Gracias!"), ("y el precio?", "USD 7.250. Pasame tu email así te mando todo."))
        self.assertIn("EMAIL_ASKED_AFTER_GIVEN", _codes(t))

    def test_phantom_email(self):
        self.assertIn("PHANTOM_EMAIL", _codes(_turns(("precio?", "Te lo mando al mail que me pasaste."))))
        self.assertNotIn("PHANTOM_EMAIL", _codes(_turns(("ana@example.com", "Ya tengo tu email, gracias."))))

    def test_offer_to_pass_to_advisor_is_not_asking(self):
        self.assertNotIn("ASKS_WANT_HUMAN", _codes(_turns(("ok", "Si después querés hablar con un asesor, avisame y te paso."))))
        self.assertIn("ASKS_WANT_HUMAN", _codes(_turns(("ok", "¿Querés hablar con un asesor?"))))

    def test_empty_reply_while_paused_is_by_design(self):
        t = _turns(("asesor", "Listo, te contacta un asesor."), ("hola?", None), paused={1})
        self.assertNotIn("EMPTY_REPLY", _codes(t))
        t = _turns(("hola", "Hola!"), ("precio?", None))
        self.assertIn("EMPTY_REPLY", _codes(t))

    def test_repeated_greeting_and_identical_reply(self):
        long = "El 18+2 tiene caminatas a Plaza Francia y al cerro Bonete para aclimatar."
        t = _turns(("hola", f"¡Hola! {long}"), ("y?", f"¡Hola! {long}"))
        codes = _codes(t)
        self.assertIn("REPEATED_GREETING", codes)
        self.assertIn("IDENTICAL_REPLY", codes)

    def test_language_drift_follows_explicit_preference(self):
        t = _turns(("Hola, english please", "Sure! The regular price is USD 7,250 per person and some dates have a promo."))
        self.assertNotIn("LANGUAGE_DRIFT", _codes(t))

    def test_too_long(self):
        self.assertIn("TOO_LONG", _codes(_turns(("info", "a" * 400))))
        self.assertNotIn("TOO_LONG", _codes(_turns(("info", "a" * 400)), _persona(style="long_email")))

    def test_conversation_level_checks(self):
        p = _persona(intent="ready_to_book")
        t = _turns(("fechas?", "Dic 4"), ("la del 4/12", "Buenísimo"), ("cómo pago?", "Con un anticipo de USD 699."))
        self.assertIn("NO_VIDEOCALL_FOR_BUYER", _codes(t, p))
        p = _persona(intent="off_season")
        warned = _turns(("se puede en julio?", "Ojo: las expediciones son solo de noviembre a marzo."))
        self.assertNotIn("OFF_SEASON_NOT_EXPLAINED", _codes(warned, p))

    def test_outcomes(self):
        t = _turns(("ana@example.com", "Gracias! ¿Armamos una videollamada?"))
        out = checks.outcomes(t, {"email_captured": True})
        self.assertTrue(out["client_gave_email"])
        self.assertTrue(out["videocall_offered"])
        self.assertTrue(out["email_captured"])
        self.assertEqual(out["turns"], 1)


class CalibrationTests(unittest.TestCase):
    def test_every_meaningful_code_has_a_case(self):
        covered = {c for case in CASES for c in case["codes"]}
        # Conversation-mechanics codes that a static transcript can't show (or only informative ones).
        exempt = {"HTTP_ERROR", "EMPTY_REPLY", "FAQ_ONLY_PRICE", "IDENTICAL_REPLY"}
        self.assertEqual(sorted(set(checks.CODES) - covered - exempt), [])

    def test_case_names_are_unique_and_have_expectations(self):
        names = [c["name"] for c in CASES]
        self.assertEqual(len(names), len(set(names)))
        for case in CASES:
            self.assertTrue(case.get("min") or case.get("max"), case["name"])

    def test_judge_calibration_logic(self):
        from evals.calibration import run_judge_calibration

        def lenient_judge(persona, transcript, findings, seed=0):
            return normalize_verdict({"scores": {d: 5 for d in ("humanness", "accuracy", "rules", "sales", "language", "length")}}, "llm")

        def paranoid_judge(persona, transcript, findings, seed=0):
            return normalize_verdict({"scores": {d: 1 for d in ("humanness", "accuracy", "rules", "sales", "language", "length")}, "violations": [{"code": "WRONG_FACT", "turn": 0}]}, "llm")

        lenient = run_judge_calibration(lenient_judge)
        paranoid = run_judge_calibration(paranoid_judge)
        good = [c["name"] for c in CASES if not c["codes"] and not c.get("judge_codes")]
        bad = [c["name"] for c in CASES if c.get("max")]
        lenient_ok = {r["name"] for r in lenient["rows"] if r["ok"]}
        paranoid_ok = {r["name"] for r in paranoid["rows"] if r["ok"]}
        self.assertTrue(set(good) <= lenient_ok)
        self.assertFalse(set(bad) & lenient_ok)
        self.assertFalse(set(good) & paranoid_ok)
        calls = Counter()

        def wobbly_judge(persona, transcript, findings, seed=0):
            calls["n"] += 1
            return normalize_verdict({"scores": {"humanness": 2 + seed % 2}}, "llm")

        wobbly = run_judge_calibration(wobbly_judge, repeats=2)
        self.assertEqual(calls["n"], 2 * len(CASES))
        self.assertEqual(wobbly["mean_spread_by_dimension"]["humanness"], 1.0)
        self.assertEqual(wobbly["mean_spread_by_dimension"]["accuracy"], 0.0)
        rows = {r["name"]: r for r in lenient["rows"]}
        self.assertIn("no marcó ninguno", " ".join(rows["ignora_la_pregunta"]["problems"]))


class JudgeTests(unittest.TestCase):
    def test_normalize_clamps_and_maps_unknown_codes(self):
        v = normalize_verdict({"scores": {"humanness": 9, "accuracy": "x", "rules": 0}, "violations": [{"code": "nope", "turn": "2"}, "bad"]}, "llm")
        self.assertEqual(v["scores"]["humanness"], 5)
        self.assertEqual(v["scores"]["accuracy"], 3)
        self.assertEqual(v["scores"]["rules"], 1)
        self.assertEqual(v["violations"], [{"code": "OTHER", "turn": 2, "quote": "", "why": ""}])

    def test_overall_score_range(self):
        self.assertEqual(overall_score({d: 5 for d in ("humanness", "accuracy", "rules", "sales", "language", "length")}), 100.0)
        self.assertEqual(overall_score({d: 1 for d in ("humanness", "accuracy", "rules", "sales", "language", "length")}), 0.0)

    def test_stub_verdict_penalizes_findings(self):
        p = _persona()
        clean = stub_verdict([], {"videocall_offered": True, "email_requested": True}, p)
        dirty = stub_verdict([checks.Finding("OLD_PRICE", 0, "x"), checks.Finding("LANGUAGE_DRIFT", 0, "x")], {}, p)
        self.assertGreater(clean["overall"], dirty["overall"])
        self.assertEqual(dirty["scores"]["accuracy"], 2)
        self.assertEqual(dirty["scores"]["language"], 2)

    def test_render_transcript(self):
        text = render_transcript(_turns(("hola", ["a", "b"]), ("?", None)))
        self.assertIn("[0] CLIENTE: hola", text)
        self.assertIn("(no respondió)", text)


class LLMTests(unittest.TestCase):
    def test_cost(self):
        self.assertAlmostEqual(cost_usd("gpt-4.1-mini", 1_000_000, 0, 1_000_000), 2.0)
        self.assertAlmostEqual(cost_usd("gpt-4.1-mini-2025-04-14", 1_000_000, 1_000_000, 0), 0.1)
        self.assertIsNone(cost_usd("mystery-model", 10, 0, 10))

    def test_tracker(self):
        t = UsageTracker()
        t.record_openai_usage("judge", "gpt-4.1", SimpleNamespace(prompt_tokens=1000, completion_tokens=100, prompt_tokens_details=SimpleNamespace(cached_tokens=200)))
        t.record("nico", "unknown-x", 5, 0, 5)
        s = t.summary()
        judge = next(r for r in s["by_role"] if r["role"] == "judge")
        self.assertEqual(judge["cached_input_tokens"], 200)
        self.assertAlmostEqual(s["total_cost_usd"], round((800 * 2 + 200 * 0.5 + 100 * 8) / 1e6, 4))
        self.assertEqual(s["models_without_price"], ["unknown-x"])

    def test_chat_json_retries_bad_json(self):
        replies = iter(["not json", '{"ok": true}'])

        def create(**kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(replies)))], usage=None)

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        tracker = UsageTracker()
        self.assertEqual(ChatJSON(client, "gpt-4.1", tracker, "judge")("s", "u"), {"ok": True})
        self.assertEqual(tracker.summary()["by_role"][0]["calls"], 2)


def _fake_run(overall_by_id: dict[str, float], codes_by_id: dict[str, list[str]] | None = None, mode: str = "real") -> dict:
    records = []
    for pid, overall in overall_by_id.items():
        p = _persona(id=pid)
        findings = [checks.Finding(c, 0, "texto").to_dict() for c in (codes_by_id or {}).get(pid, [])]
        records.append({
            "persona": p.to_dict(),
            "transcript": _turns(("hola", "Hola!")),
            "findings": findings,
            "outcomes": checks.outcomes(_turns(("hola", "Hola!")), {}),
            "verdict": {"source": "llm", "scores": {d: 3.0 for d in ("humanness", "accuracy", "rules", "sales", "language", "length")}, "overall": overall, "violations": [{"code": "IGNORES_QUESTION", "turn": 0, "quote": "Hola!", "why": "no respondió"}], "failure_tags": ["no responde el precio"], "summary": "s"},
            "ended_by": "customer",
            "error": None,
        })
    return {"schema": 1, "started_at": "2026-11-04T00:00:00+00:00", "config": {"n": len(records), "seed": 7, "llm_personas": 0, "nico_model": "m", "simulator_model": "m", "judge_model": "m", "judge": True, "label": ""}, "git": {"commit": "abc", "branch": "main", "dirty": False}, "mode": mode, "usage": UsageTracker().summary(), "records": records}


class ReportTests(unittest.TestCase):
    def test_summary_and_patterns(self):
        s = summarize(_fake_run({"a": 80, "b": 40, "c": 60}, {"b": ["OLD_PRICE", "OLD_PRICE"], "c": ["EM_DASH"]}))
        self.assertEqual(s["n"], 3)
        self.assertEqual(s["overall"]["mean"], 60)
        self.assertEqual(s["deterministic"]["OLD_PRICE"]["conversations"], 1)
        self.assertEqual(s["deterministic"]["OLD_PRICE"]["occurrences"], 2)
        self.assertEqual(s["worst"][0]["persona"]["id"], "b")
        top = s["failure_patterns"][0]
        self.assertEqual(top["code"], "IGNORES_QUESTION")  # 3 conversations x sev 2 beats 1 x sev 3
        self.assertEqual(s["failure_tags"][0]["conversations"], 3)
        self.assertIn("OLD_PRICE", s["calibration"])

    def test_compare_paired(self):
        base = summarize(_fake_run({"a": 80, "b": 40}))
        cur = summarize(_fake_run({"a": 60, "b": 50}, {"a": ["OLD_PRICE"]}))
        c = compare(cur, base)
        self.assertTrue(c["same_setup"])
        self.assertEqual(c["overall_delta"], -5)
        self.assertTrue(c["regression"])
        self.assertEqual(c["regressed"][0]["id"], "a")
        self.assertEqual(c["regressed"][0]["new_codes"], ["OLD_PRICE"])
        self.assertEqual(c["codes"]["OLD_PRICE"]["delta"], 0.5)

    def test_render_and_write(self):
        run = _fake_run({"a": 80, "b": 40}, {"b": ["MEDICAL_ADVICE"]}, mode="offline-stub")
        s = summarize(run)
        md = render_markdown(build_sections(s), "T")
        self.assertIn("## Top 10 patrones de falla", md)
        self.assertIn("MEDICAL_ADVICE", md)
        self.assertIn("OFFLINE", md)
        html_text = render_html(build_sections(s), "T <x>")
        self.assertIn("&lt;x&gt;", html_text)
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp) / "base"
            write_outputs(run, base_dir)
            out = write_outputs(run, Path(tmp) / "cur", base_dir / "summary.json")
            self.assertEqual(out["comparison"]["overall_delta"], 0)
            for name in ("run.json", "summary.json", "report.md", "report.html"):
                self.assertTrue((Path(tmp) / "cur" / name).exists())
            self.assertIn("Comparación con baseline", (Path(tmp) / "cur" / "report.md").read_text())


class OfflineEndToEndTests(unittest.TestCase):
    """The whole harness against the real server.py, with the stub model."""

    def test_offline_run_is_deterministic(self):
        from evals.runner import EvalConfig, run_eval

        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        with mock.patch.dict(os.environ, env, clear=True):
            runs = [run_eval(EvalConfig(n=14, seed=5, concurrency=4), progress=False, server_log=io.StringIO()) for _ in range(2)]
        a, b = runs
        self.assertEqual(a["mode"], "offline-stub")
        self.assertEqual(len(a["records"]), 14)
        self.assertEqual(a["usage"]["total_cost_usd"], 0)
        self.assertEqual([r["verdict"]["overall"] for r in a["records"]], [r["verdict"]["overall"] for r in b["records"]])
        codes = {f["code"] for r in a["records"] for f in r["findings"]}
        self.assertNotIn("HTTP_ERROR", codes)
        self.assertTrue(all(r["transcript"] for r in a["records"]))
        # Fixed replies from server.py come through: the bot question has its own phrase.
        bot = [r for r in a["records"] if r["persona"]["intent"] == "asks_if_bot"]
        if bot:
            text = json.dumps(bot[0]["transcript"], ensure_ascii=False)
            self.assertRegex(text, r"asistente digital|digital assistant|assistente digital")

    def test_real_mode_plumbing_with_a_fake_openai(self):
        """Simulator, judge and Nico's model all wired and their tokens counted."""
        from evals import runner
        from orchestrator import server

        rows = server.load_index(server.INDEX_PATH)
        calls = Counter()

        def chat_create(**kwargs):
            system = kwargs["messages"][0]["content"]
            if system.startswith("Sos un actor"):
                calls["simulator"] += 1
                content = {"messages": ["Hola, cuánto sale el 18+2?"], "done": calls["simulator"] % 2 == 0}
            else:
                calls["judge"] += 1
                content = {"scores": {"humanness": 4, "accuracy": 5, "rules": 5, "sales": 3, "language": 5, "length": 5}, "violations": [{"code": "NO_QUALIFICATION", "turn": 0, "quote": "x", "why": "y"}], "failure_tags": ["no califica"], "summary": "ok"}
            usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=50, prompt_tokens_details=SimpleNamespace(cached_tokens=0))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(content)))], usage=usage)

        fake_chat_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=chat_create)))

        class FakeOpenAI:
            def __init__(self, *a, **k):
                self.embeddings = SimpleNamespace(create=lambda model, input: SimpleNamespace(
                    data=[SimpleNamespace(embedding=rows[0]["embedding"]) for _ in (input if isinstance(input, list) else [input])],
                    usage=SimpleNamespace(prompt_tokens=10)))
                self.responses = SimpleNamespace(create=lambda **kw: SimpleNamespace(
                    output_text="El 18+2 sale USD 7.250 por persona.", status="completed",
                    usage=SimpleNamespace(input_tokens=3000, output_tokens=20, input_tokens_details=SimpleNamespace(cached_tokens=1000))))

        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fake"}), \
                mock.patch.object(runner, "make_openai_client", lambda key: fake_chat_client), \
                mock.patch.object(server, "OpenAI", FakeOpenAI):
            run = runner.run_eval(runner.EvalConfig(n=4, seed=1, concurrency=2), progress=False, server_log=io.StringIO())
        self.assertEqual(run["mode"], "real")
        self.assertEqual({r["verdict"]["source"] for r in run["records"]}, {"llm"})
        roles = {u["role"] for u in run["usage"]["by_role"]}
        self.assertTrue({"simulator", "judge", "nico"} <= roles, roles)
        self.assertGreater(run["usage"]["total_cost_usd"], 0)
        self.assertTrue(all(r["nico_usage"]["calls"] >= 0 for r in run["records"]))
        s = summarize(run)
        self.assertEqual(s["judge_violations"]["NO_QUALIFICATION"]["conversations"], 4)


if __name__ == "__main__":
    unittest.main()
