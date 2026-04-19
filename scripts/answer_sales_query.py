#!/usr/bin/env python3
"""Answer a sales query using cloud-only RAG.

Flow:
1) Embed incoming user question via hosted API.
2) Retrieve top-k FAQ chunks by cosine similarity.
3) Generate a sales-oriented response grounded on retrieved evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "docs" / "knowledge" / "faq_cloud_index.jsonl"
SYSTEM_PROMPT_PATH = ROOT / "docs" / "sales-agent" / "02-system-prompt.md"


def load_index(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def get_embedding(client: OpenAI, model: str, text: str) -> list[float]:
    resp = client.embeddings.create(model=model, input=text)
    return resp.data[0].embedding


def retrieve(query_vec: list[float], rows: list[dict], top_k: int) -> list[dict]:
    scored: list[dict] = []
    for r in rows:
        score = cosine(query_vec, r["embedding"])
        scored.append({"score": score, **r})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def load_system_prompt() -> str:
    if not SYSTEM_PROMPT_PATH.exists():
        return "Eres un asistente comercial de expediciones al Aconcagua. Responde con precision y no inventes datos."
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def build_context(top_hits: list[dict]) -> str:
    parts: list[str] = []
    for h in top_hits:
        parts.append(
            f"ID: {h['id']}\n"
            f"TOPIC: {h.get('topic', 'general')}\n"
            f"QUESTION: {h['question']}\n"
            f"ANSWER: {h['answer']}\n"
            f"SIMILARITY: {h['score']:.4f}"
        )
    return "\n\n---\n\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Answer one sales query from FAQ cloud index")
    parser.add_argument("query", help="Customer question")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    api_key = os.getenv("OPENAI_API_KEY")
    embed_model = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
    chat_model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")
    top_k = int(os.getenv("TOP_K", "4"))

    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY in .env")
    if not INDEX_PATH.exists():
        raise SystemExit(
            "Missing cloud index file. Run scripts/build_cloud_index.py first."
        )

    rows = load_index(INDEX_PATH)
    client = OpenAI(api_key=api_key)

    q_vec = get_embedding(client, embed_model, args.query)
    hits = retrieve(q_vec, rows, top_k)
    context = build_context(hits)
    system_prompt = load_system_prompt()

    user_prompt = (
        "Cliente pregunta:\n"
        f"{args.query}\n\n"
        "Evidencia interna recuperada:\n"
        f"{context}\n\n"
        "Instrucciones:\n"
        "- Responde SOLO con datos respaldados por la evidencia.\n"
        "- Si falta informacion, dilo explicitamente y ofrece pasar a asesor humano.\n"
        "- Cierra con un siguiente paso comercial concreto (una sola accion).\n"
        "- Escribe en espanol."
    )

    resp = client.responses.create(
        model=chat_model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    print(resp.output_text.strip())
    print("\nFuentes usadas:")
    for h in hits:
        print(f"- {h['id']} | {h.get('topic', 'general')} | score={h['score']:.4f}")


if __name__ == "__main__":
    main()
