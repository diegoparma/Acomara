#!/usr/bin/env python3
"""Build a cloud embedding index from FAQ chunks.

This script calls a hosted embedding API (OpenAI) and stores vectors locally
as JSONL for fast retrieval at runtime. No local model inference is used.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "docs" / "knowledge" / "faq_rag_chunks.jsonl"
OUTPUT_PATH = ROOT / "docs" / "knowledge" / "faq_cloud_index.jsonl"


def load_chunks(path: Path) -> list[dict]:
    chunks: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            chunks.append(json.loads(line))
    return chunks


def embed_texts(client: OpenAI, model: str, texts: list[str]) -> list[list[float]]:
    # Batch call keeps API usage and latency under control.
    resp = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in resp.data]


def main() -> None:
    load_dotenv(ROOT / ".env")

    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY in .env")
    if not INPUT_PATH.exists():
        raise SystemExit(f"Input file not found: {INPUT_PATH}")

    client = OpenAI(api_key=api_key)
    chunks = load_chunks(INPUT_PATH)

    texts = [f"Q: {c['question']}\nA: {c['answer']}" for c in chunks]

    vectors: list[list[float]] = []
    batch_size = 32
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        vectors.extend(embed_texts(client, model, batch))

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for c, v in zip(chunks, vectors):
            rec = {
                "id": c["id"],
                "topic": c.get("topic", "general"),
                "question": c["question"],
                "answer": c["answer"],
                "source": c.get("source", "faq_structured.md"),
                "embedding": v,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"Index written: {OUTPUT_PATH}")
    print(f"Records: {len(chunks)}")


if __name__ == "__main__":
    main()
