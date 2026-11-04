#!/usr/bin/env python3
"""Build the embeddings index Nico searches (docs/knowledge/faq_cloud_index.jsonl).

    python3 scripts/build_knowledge.py && python3 scripts/build_cloud_index.py

Reads the chunks generated from docs/knowledge/fuente/ (faq_rag_chunks.jsonl),
embeds them with OpenAI and writes the index. Chunks whose text and model did
not change keep their stored vector, so editing one price re-embeds one or two
chunks, not all of them.

    --check   no network: list chunks missing from the index or out of date
              (exit 1 if any). Useful without OPENAI_API_KEY.

Each row records the model that embedded it (embed_model) so the server can
embed queries with the same model; vectors from different models are not
comparable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "docs" / "knowledge" / "faq_rag_chunks.jsonl"
OUTPUT_PATH = ROOT / "docs" / "knowledge" / "faq_cloud_index.jsonl"
DEFAULT_MODEL = "text-embedding-3-large"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_chunks(path: Path = INPUT_PATH) -> list[dict[str, Any]]:
    return load_jsonl(path)


def embed_text(chunk: dict[str, Any]) -> str:
    """What gets embedded: the question, how clients also ask it, and the answer."""
    parts = [f"Q: {chunk['question']}"]
    if chunk.get("also_asked"):
        parts.append("Also asked: " + " | ".join(chunk["also_asked"]))
    parts.append(f"A: {chunk['answer']}")
    return "\n".join(parts)


def embed_hash(chunk: dict[str, Any], model: str) -> str:
    return hashlib.sha256(f"{model}\n{embed_text(chunk)}".encode("utf-8")).hexdigest()[:16]


def plan(chunks: list[dict[str, Any]], index: list[dict[str, Any]], model: str) -> tuple[list[dict], list[dict]]:
    """(rows that can keep their vector, chunks that need a new one)."""
    by_hash = {r.get("embed_hash"): r for r in index if r.get("embed_hash") and r.get("embedding")}
    keep, todo = [], []
    for c in chunks:
        old = by_hash.get(embed_hash(c, model))
        (keep if old else todo).append(c)
    return keep, todo


def index_row(chunk: dict[str, Any], vector: list[float], model: str) -> dict[str, Any]:
    row = {k: v for k, v in chunk.items()}
    row.setdefault("source", "fuente/faq.yaml")
    row["embed_model"] = model
    row["embed_hash"] = embed_hash(chunk, model)
    row["embedding"] = vector
    return row


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="sin red: muestra qué falta re-indexar")
    args = parser.parse_args(argv)

    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except ImportError:
        pass
    model = os.getenv("OPENAI_EMBED_MODEL", DEFAULT_MODEL)

    chunks = load_chunks()
    if not chunks:
        raise SystemExit(f"No chunks in {INPUT_PATH}; run scripts/build_knowledge.py first")
    index = load_jsonl(OUTPUT_PATH)
    keep, todo = plan(chunks, index, model)
    chunk_ids = {c["id"] for c in chunks}
    removed = [r["id"] for r in index if r["id"] not in chunk_ids]

    if args.check:
        print(f"Modelo: {model}. Fragmentos: {len(chunks)}; al día: {len(keep)}; a embeber: {len(todo)}; sobran en el índice: {len(removed)}")
        for c in todo:
            print(f"  embeber {c['id']} ({c.get('key', '')})")
        for rid in removed:
            print(f"  quitar  {rid}")
        return 1 if todo or removed else 0

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key and todo:
        raise SystemExit("Missing OPENAI_API_KEY (.env or environment)")

    vectors: dict[str, list[float]] = {}
    if todo:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        batch_size = 32
        for i in range(0, len(todo), batch_size):
            batch = todo[i : i + batch_size]
            resp = client.embeddings.create(model=model, input=[embed_text(c) for c in batch])
            for c, item in zip(batch, resp.data):
                vectors[c["id"]] = item.embedding
    old_by_hash = {r.get("embed_hash"): r for r in index}

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for c in chunks:
            vector = vectors.get(c["id"]) or old_by_hash[embed_hash(c, model)]["embedding"]
            f.write(json.dumps(index_row(c, vector, model), ensure_ascii=False) + "\n")

    print(f"Index written: {OUTPUT_PATH} ({len(chunks)} rows; embedded {len(todo)}, reused {len(keep)}; model {model})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
