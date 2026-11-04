#!/usr/bin/env python3
"""Canonical knowledge source (docs/knowledge/fuente/) and what is generated from it.

No network. Run with:
    python3 tests/test_knowledge_base.py
"""
from __future__ import annotations

import copy
import json
import logging
import re
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import build_cloud_index  # noqa: E402
import build_knowledge as kb  # noqa: E402
import eval_retrieval  # noqa: E402
from orchestrator import kb_retrieval  # noqa: E402
from orchestrator.departures import is_departure_dates_entry, season_departures  # noqa: E402

KNOWLEDGE = ROOT / "docs" / "knowledge"
SOURCES = kb.load_sources()

# Texts a client can end up reading (directly or through Nico). Any USD amount in
# them must be one of the amounts in the canonical source.
CLIENT_FACING = [
    KNOWLEDGE / "datos-clave.md",
    KNOWLEDGE / "faq_rag_chunks.jsonl",
    KNOWLEDGE / "faq_cloud_index.jsonl",
    ROOT / "docs" / "sales-agent" / "02-system-prompt.md",
    ROOT / "docs" / "sales-agent" / "15-reglas-de-nico.md",
    ROOT / "docs" / "estado-nico-para-fernando.md",
    ROOT / "orchestrator" / "server.py",
    ROOT / "orchestrator" / "sales_rules.py",
]
_USD = re.compile(r"(?:USD|US\$|U\$S)\s?\$?\s?(\d{1,3}(?:[.,]\d{3})+|\d+)")


def usd_amounts(text: str) -> set[int]:
    return {int(re.sub(r"[.,]", "", m)) for m in _USD.findall(text)}


def canonical_amounts() -> set[int]:
    amounts = {int(v["usd"]) for v in SOURCES.values.values() if "usd" in v}
    # Amounts the web FAQ states literally (abandonment costs, tips, satellite phone...).
    for entry in SOURCES.faq:
        for answer in entry["answer"].values():
            amounts |= usd_amounts(answer)
            amounts |= {int(x) for x in re.findall(r"USD \d+(?:[.,]\d+)?[/-](\d+)", answer)}
    return amounts


class GeneratedFilesTests(unittest.TestCase):
    def test_sources_are_valid(self):
        self.assertEqual(kb.validate(SOURCES), [])

    def test_generated_files_are_up_to_date(self):
        # Fails when someone edits a generated file by hand or forgets to run the build.
        for path, content in kb.build_all(SOURCES).items():
            with self.subTest(path=path.name):
                self.assertEqual(
                    path.read_text(encoding="utf-8"), content,
                    f"{path.name} desactualizado: correr python3 scripts/build_knowledge.py",
                )

    def test_key_facts_keep_what_the_prompt_tests_rely_on(self):
        md = kb.build_key_facts_md(SOURCES)
        self.assertTrue(md.startswith("# DATOS CLAVE"))
        self.assertIn("USD 7.250", md)
        self.assertIn("NO está incluido", md)
        self.assertNotIn("{", md, "placeholder sin reemplazar")

    def test_pending_facts_are_not_published(self):
        sources = copy.deepcopy(SOURCES)
        sources.key_facts["sections"][0]["facts"].append(
            {"id": "x", "text": "DATO SIN CONFIRMAR", "source": ["?"], "confidence": "pending"}
        )
        self.assertNotIn("DATO SIN CONFIRMAR", kb.build_key_facts_md(sources))

    def test_every_chunk_has_metadata(self):
        chunks = kb.build_chunks(SOURCES)
        self.assertEqual(len({c["id"] for c in chunks}), len(chunks), "ids repetidos")
        for c in chunks:
            for field in ("id", "key", "lang", "topic", "question", "answer", "source", "confidence"):
                self.assertTrue(c.get(field), f"{c.get('id')}: falta {field}")
            self.assertNotRegex(c["answer"], r"\{[a-z_]+\}", c["id"])

    def test_entries_answered_only_in_english_carry_the_spanish_question(self):
        # Clients write mostly in Spanish; the Spanish question is what lets them find it.
        for entry in SOURCES.faq:
            with self.subTest(key=entry["key"]):
                self.assertIn("es", entry["question"])


class RenderingTests(unittest.TestCase):
    def test_usd_format_per_language(self):
        self.assertEqual(kb.format_usd(7250, "es"), "USD 7.250")
        self.assertEqual(kb.format_usd(7250, "pt"), "USD 7.250")
        self.assertEqual(kb.format_usd(7250, "en"), "USD 7,250")
        self.assertEqual(kb.format_usd(699, "es"), "USD 699")

    def test_percent_format_per_language(self):
        self.assertEqual(kb.format_percent(5.5, "es"), "5,5%")
        self.assertEqual(kb.format_percent(5.5, "en"), "5.5%")

    def test_unknown_placeholder_is_an_error(self):
        with self.assertRaises(kb.KnowledgeError):
            kb.render(SOURCES, "precio {precio_inventado}", "es")
        sources = copy.deepcopy(SOURCES)
        sources.faq[0]["answer"]["es"] += " {precio_inventado}"
        self.assertTrue(any("precio_inventado" in e for e in kb.validate(sources)))

    def test_a_price_change_is_one_edit(self):
        sources = copy.deepcopy(SOURCES)
        sources.values["price_regular"]["usd"] = 8100
        outputs = kb.build_all(sources)
        key_facts = outputs[KNOWLEDGE / "datos-clave.md"]
        chunks = outputs[KNOWLEDGE / "faq_rag_chunks.jsonl"]
        self.assertIn("USD 8.100", key_facts)
        self.assertIn("USD 8.100", chunks)
        self.assertIn("USD 8,100", chunks)
        for text in (key_facts, chunks):
            self.assertNotRegex(text, r"7[.,]250")

    def test_expired_values_fail_validation(self):
        errors = kb.validate(SOURCES, today=date(2027, 4, 1))
        self.assertTrue(any("price_regular" in e and "vencido" in e for e in errors))


class ConsistencyTests(unittest.TestCase):
    def test_commercial_prices_are_written_only_in_valores(self):
        # A confirmed price typed literally in faq.yaml or datos-clave.yaml would
        # not change when valores.yaml changes.
        texts = {
            "faq.yaml": (ROOT / "docs/knowledge/fuente/faq.yaml").read_text(encoding="utf-8"),
            "datos-clave.yaml": (ROOT / "docs/knowledge/fuente/datos-clave.yaml").read_text(encoding="utf-8"),
        }
        for name, spec in SOURCES.values.items():
            if "usd" not in spec or spec.get("confidence") != "confirmed" or spec["usd"] < 1000:
                continue
            n = int(spec["usd"])
            pattern = re.compile(rf"(?:USD|US\$)\s?{n // 1000}[.,]?{n % 1000:03d}\b")
            for fname, text in texts.items():
                with self.subTest(value=name, file=fname):
                    self.assertIsNone(pattern.search(text), f"{name} escrito a mano en {fname}: usar {{{name}}}")

    def test_no_source_states_a_price_the_canonical_source_does_not_have(self):
        # Regression: docs/estado-nico-para-fernando.md said USD 6.990 after
        # Fernando moved the price to USD 7.250.
        allowed = canonical_amounts()
        for path in CLIENT_FACING:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".jsonl":
                text = "\n".join(json.loads(l).get("answer", "") for l in text.splitlines() if l.strip())
            with self.subTest(file=path.name):
                unknown = sorted(usd_amounts(text) - allowed)
                self.assertEqual(unknown, [], f"{path.name} menciona montos que no están en fuente/: {unknown}")

    def test_departures_text_parses_back_to_the_source_dates(self):
        chunks = kb.build_chunks(SOURCES)
        self.assertEqual({c["id"] for c in chunks if is_departure_dates_entry(c)}, {"faq-060", "faq-061"})
        parsed = season_departures(chunks)
        for program in SOURCES.departures["programs"]:
            with self.subTest(program=program["program"]):
                self.assertEqual(parsed[program["program"]], sorted(program["dates"]))

    def test_index_is_in_sync_with_the_chunks(self):
        chunks = build_cloud_index.load_chunks()
        index = build_cloud_index.load_jsonl(build_cloud_index.OUTPUT_PATH)
        model = next((r["embed_model"] for r in index if r.get("embed_model")), build_cloud_index.DEFAULT_MODEL)
        _, todo = build_cloud_index.plan(chunks, index, model)
        if todo:
            self.skipTest(f"índice desactualizado ({len(todo)} fragmentos): python3 scripts/build_cloud_index.py")


class RetrievalTests(unittest.TestCase):
    ROWS = [
        {"id": "a", "question": "What is the price?", "also_asked": ["¿Cuánto sale?"], "answer": "USD 7,250", "embedding": [1.0, 0.0]},
        {"id": "b", "question": "Is there a vegan menu?", "also_asked": ["Menú vegano"], "answer": "Yes", "embedding": [0.0, 1.0]},
        {"id": "c", "question": "Do I need insurance?", "also_asked": [], "answer": "Yes, rescue insurance", "embedding": [0.7, 0.7]},
    ]

    def test_keyword_finds_spanish_paraphrase(self):
        hits = kb_retrieval.rank(self.ROWS, ["¿Hay menú vegano?"], None, top_k=1, mode="hybrid")
        self.assertEqual(hits[0]["id"], "b")

    def test_dense_mode_orders_by_cosine(self):
        hits = kb_retrieval.rank(self.ROWS, ["x"], [[0.0, 1.0]], top_k=3, mode="dense")
        self.assertEqual([h["id"] for h in hits], ["b", "c", "a"])
        self.assertAlmostEqual(hits[0]["score"], 1.0)

    def test_hybrid_lifts_a_keyword_match_the_embedding_ranked_lower(self):
        hits = kb_retrieval.rank(self.ROWS, ["menú vegano"], [[1.0, 0.1]], top_k=2, mode="hybrid")
        self.assertIn("b", [h["id"] for h in hits])

    def test_size_mismatch_is_logged(self):
        with self.assertLogs("orchestrator.kb_retrieval", level=logging.ERROR):
            kb_retrieval.dense_scores([[1.0, 0.0, 0.0]], [{"embedding": [1.0, 0.0]}])

    def test_accents_and_plurals_are_folded(self):
        self.assertEqual(kb_retrieval.tokenize("Fechas de salida"), kb_retrieval.tokenize("fecha salidas"))
        self.assertEqual(kb_retrieval.tokenize("menú"), ["menu"])


class IndexBuildTests(unittest.TestCase):
    def test_unchanged_chunks_reuse_their_vector(self):
        chunk = {"id": "faq-900", "question": "q", "answer": "a"}
        row = build_cloud_index.index_row(chunk, [0.1, 0.2], "m")
        keep, todo = build_cloud_index.plan([chunk], [row], "m")
        self.assertEqual((len(keep), len(todo)), (1, 0))
        changed = dict(chunk, answer="otro precio")
        self.assertEqual(len(build_cloud_index.plan([changed], [row], "m")[1]), 1)
        self.assertEqual(len(build_cloud_index.plan([chunk], [row], "otro-modelo")[1]), 1)

    def test_embed_text_includes_paraphrases(self):
        text = build_cloud_index.embed_text({"question": "Q1", "also_asked": ["¿Cuánto sale?"], "answer": "A"})
        self.assertIn("¿Cuánto sale?", text)


class BenchmarkTests(unittest.TestCase):
    def test_labeled_questions_point_to_existing_entries(self):
        keys = {e["key"] for e in SOURCES.faq}
        for q in eval_retrieval.load_questions():
            with self.subTest(q=q["q"]):
                self.assertTrue(set(q["expect"]) <= keys, q["expect"])
                self.assertIn(q["lang"], ("es", "en", "pt"))

    def test_keyword_retrieval_does_not_regress(self):
        # Offline floor (keyword only, measured 88.5% hit@4 on 2026-11-04).
        rows = build_cloud_index.load_chunks()
        report = eval_retrieval.run(rows, eval_retrieval.load_questions(), "keyword", 4)
        self.assertGreaterEqual(report["summary"]["all"]["hit@4"], 0.85)


if __name__ == "__main__":
    unittest.main(verbosity=2)
