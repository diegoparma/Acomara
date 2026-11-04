#!/usr/bin/env python3
"""Retrieval benchmark: does Nico find the right FAQ entry for real client questions?

    python3 scripts/eval_retrieval.py                         # keyword (BM25), no network
    python3 scripts/eval_retrieval.py --mode dense            # embeddings, needs OPENAI_API_KEY
    python3 scripts/eval_retrieval.py --mode all              # dense, keyword and hybrid
    python3 scripts/eval_retrieval.py --rows old_chunks.jsonl # another chunk/index file

Questions: docs/knowledge/eval/preguntas-busqueda.yaml (expected entry `key`s).
Reports hit@1, hit@3, hit@k (k = TOP_K, 4 in production) and MRR, overall and by
language, plus the misses. Rows without a `key` field (indexes built before
fuente/faq.yaml) are mapped through their legacy faq-NNN id.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_knowledge import entry_ids, load_sources  # noqa: E402
from orchestrator import kb_retrieval  # noqa: E402

QUESTIONS_PATH = ROOT / "docs" / "knowledge" / "eval" / "preguntas-busqueda.yaml"
CHUNKS_PATH = ROOT / "docs" / "knowledge" / "faq_rag_chunks.jsonl"
INDEX_PATH = ROOT / "docs" / "knowledge" / "faq_cloud_index.jsonl"

# Chunks of the old awk pipeline that mixed several of today's entries.
LEGACY_SPLITS = {
    "faq-001": ["itinerario-18-2", "itinerario-polaco-17-2", "itinerario-14-2"],
    "faq-017": ["servicios-opcionales", "trek-familiares-a-plaza-de-mulas", "porteadores-personales"],
    "faq-020": ["equipo-personal-obligatorio", "servicios-opcionales"],
    "faq-034": [
        "edad-minima", "tasa-de-cumbre-por-temporada", "dificultad-y-experiencia", "menu-vegetariano",
        "menu-celiaco", "menu-sin-lactosa", "menu-vegano", "menu-kosher", "menu-regular",
    ],
    "faq-053": ["peso-que-carga-cada-uno"],
}


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def id_to_keys() -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for entry in load_sources().faq:
        for cid in entry_ids(entry).values():
            mapping.setdefault(cid, set()).add(entry["key"])
    for cid, keys in LEGACY_SPLITS.items():
        mapping[cid] = set(keys)
    return mapping


def row_keys(row: dict[str, Any], legacy: dict[str, set[str]]) -> set[str]:
    if row.get("key"):
        return {row["key"]}
    return legacy.get(row["id"], set())


def contextual_query(q: dict[str, Any]) -> str:
    from orchestrator.server import build_contextual_query

    return build_contextual_query(q["q"], q.get("context") or [])


def load_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def run(rows: list[dict[str, Any]], questions: list[dict[str, Any]], mode: str, k: int, embedder=None) -> dict[str, Any]:
    legacy = id_to_keys()
    results = []
    for q in questions:
        queries = [q["q"]]
        ctx = contextual_query(q)
        if ctx != q["q"]:
            queries.append(ctx)
        vectors = embedder(queries) if mode in ("dense", "hybrid") else None
        ranked = kb_retrieval.rank(rows, queries, vectors, top_k=max(k, 10), mode=mode)
        expected = set(q["expect"])
        rank = next((i + 1 for i, r in enumerate(ranked) if row_keys(r, legacy) & expected), None)
        results.append({"q": q["q"], "lang": q["lang"], "expect": sorted(expected), "rank": rank,
                        "got": [r["id"] for r in ranked[:k]]})
    return {"mode": mode, "k": k, "results": results, "summary": summarize(results, k)}


def summarize(results: list[dict[str, Any]], k: int) -> dict[str, Any]:
    def stats(rs: list[dict[str, Any]]) -> dict[str, float]:
        n = len(rs) or 1
        hit = lambda m: sum(1 for r in rs if r["rank"] and r["rank"] <= m) / n  # noqa: E731
        return {"n": len(rs), "hit@1": hit(1), "hit@3": hit(3), f"hit@{k}": hit(k),
                "mrr": sum(1 / r["rank"] for r in rs if r["rank"]) / n}

    out = {"all": stats(results)}
    for lang in sorted({r["lang"] for r in results}):
        out[lang] = stats([r for r in results if r["lang"] == lang])
    return out


def make_embedder(rows: list[dict[str, Any]]):
    from openai import OpenAI

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("dense/hybrid need OPENAI_API_KEY")
    model = next((r["embed_model"] for r in rows if r.get("embed_model")), None) or os.getenv(
        "OPENAI_EMBED_MODEL", "text-embedding-3-large"
    )
    client = OpenAI()
    cache: dict[str, list[float]] = {}

    def embed(texts: list[str]) -> list[list[float]]:
        missing = [t for t in texts if t not in cache]
        if missing:
            for t, item in zip(missing, client.embeddings.create(model=model, input=missing).data):
                cache[t] = item.embedding
        return [cache[t] for t in texts]

    return embed


def print_report(report: dict[str, Any], show_misses: bool) -> None:
    k = report["k"]
    print(f"\n== {report['mode']} (k={k}) ==")
    print(f"{'':6} {'n':>4} {'hit@1':>7} {'hit@3':>7} {f'hit@{k}':>7} {'MRR':>6}")
    for name, s in report["summary"].items():
        print(f"{name:6} {s['n']:>4} {s['hit@1']:>7.1%} {s['hit@3']:>7.1%} {s[f'hit@{k}']:>7.1%} {s['mrr']:>6.3f}")
    if show_misses:
        for r in report["results"]:
            if not r["rank"] or r["rank"] > k:
                print(f"  MISS [{r['lang']}] {r['q']!r} expect={r['expect']} got={r['got']}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", choices=["keyword", "dense", "hybrid", "all"], default="keyword")
    p.add_argument("--rows", type=Path, help="chunks/index JSONL (default: chunks for keyword, index for dense)")
    p.add_argument("--k", type=int, default=int(os.getenv("TOP_K", "4")))
    p.add_argument("--misses", action="store_true", help="list the questions that miss")
    p.add_argument("--json", type=Path, help="write the full results here")
    args = p.parse_args(argv)

    questions = load_questions()
    modes = ["dense", "keyword", "hybrid"] if args.mode == "all" else [args.mode]
    reports = []
    for mode in modes:
        path = args.rows or (CHUNKS_PATH if mode == "keyword" else INDEX_PATH)
        rows = load_rows(path)
        embedder = make_embedder(rows) if mode != "keyword" else None
        report = run(rows, questions, mode, args.k, embedder)
        report["rows"] = str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
        print_report(report, args.misses)
        reports.append(report)
    if args.json:
        args.json.write_text(json.dumps(reports, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
