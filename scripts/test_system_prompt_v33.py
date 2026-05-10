#!/usr/bin/env python3
"""Smoke tests for sales system prompt v3.3 policy behavior.

Runs six controlled prompt tests against the configured OpenAI chat model.
Each test injects synthetic evidence and verifies expected output patterns.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "docs" / "sales-agent" / "02-system-prompt.md"


@dataclass
class Case:
    name: str
    language: str
    user_question: str
    evidence: list[dict[str, str]]
    must_have: list[str]
    must_not_have: list[str]


def load_prompt() -> str:
    if not PROMPT_PATH.exists():
        raise SystemExit(f"Missing prompt file: {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_evidence_block(evidence: list[dict[str, str]]) -> str:
    if not evidence:
        return "(sin evidencia recuperada)"
    parts: list[str] = []
    for item in evidence:
        parts.append(
            "ID: {id}\nQUESTION: {question}\nANSWER: {answer}".format(
                id=item.get("id", "faq-test"),
                question=item.get("question", ""),
                answer=item.get("answer", ""),
            )
        )
    return "\n\n---\n\n".join(parts)


def run_case(client: OpenAI, model: str, prompt: str, case: Case) -> tuple[bool, str, list[str]]:
    evidence_block = build_evidence_block(case.evidence)
    user_input = (
        "conversation_language={lang}\n"
        "Cliente pregunta:\n{q}\n\n"
        "Evidencia recuperada:\n{ev}\n\n"
        "Responde como asistente de ventas.\n"
        "Devuelve SOLO JSON compacto con esta forma exacta:\n"
        "{{\"answer\":\"...\"}}"
    ).format(lang=case.language, q=case.user_question, ev=evidence_block)

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_input},
        ],
    )

    raw = (resp.output_text or "").strip()
    errors: list[str] = []

    try:
        payload = json.loads(raw)
        answer = str(payload.get("answer", "")).strip()
    except Exception:
        answer = raw
        errors.append("Response was not strict JSON; evaluated as plain text")

    for pattern in case.must_have:
        if re.search(pattern, answer, flags=re.IGNORECASE) is None:
            errors.append(f"Missing expected pattern: {pattern}")

    for pattern in case.must_not_have:
        if re.search(pattern, answer, flags=re.IGNORECASE) is not None:
            errors.append(f"Matched forbidden pattern: {pattern}")

    return (len(errors) == 0), answer, errors


def main() -> None:
    load_dotenv(ROOT / ".env")

    api_key = os.getenv("OPENAI_API_KEY")
    model = os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")

    if not api_key:
        raise SystemExit("Missing OPENAI_API_KEY in .env")

    prompt = load_prompt()
    client = OpenAI(api_key=api_key)

    cases = [
        Case(
            name="ES Precio publicado",
            language="es",
            user_question="Cual es el precio de la expedicion?",
            evidence=[
                {
                    "id": "faq-058",
                    "question": "Cuál es el precio de la expedición?",
                    "answer": "El precio es USD 6.990, con promoción limitada de USD 5.990 para algunas fechas según disponibilidad.",
                }
            ],
            must_have=[r"USD\s*6[\.,]?990", r"USD\s*5[\.,]?990"],
            must_not_have=[r"No dispongo de esa información"],
        ),
        Case(
            name="EN Departure dates published",
            language="en",
            user_question="What are your departure dates?",
            evidence=[
                {
                    "id": "faq-061",
                    "question": "What are the departure dates?",
                    "answer": "Confirmed departures for 2026/27 include November 14 and 22, December 1, 4, 20, 27, January 2, 10, 31, and February 7.",
                }
            ],
            must_have=[r"2026/27", r"November"],
            must_not_have=[r"I don't have that information"],
        ),
        Case(
            name="ES No confirmar cupo",
            language="es",
            user_question="Confirmame si hay cupo para el 22 de noviembre y reservamelo ahora",
            evidence=[
                {
                    "id": "faq-060",
                    "question": "Cuáles son las fechas de salida?",
                    "answer": "Hay salida publicada el 22 de noviembre.",
                }
            ],
            must_have=[r"asesor humano|asesor", r"email|correo"],
            must_not_have=[r"confirmado|te reservo|reserva realizada"],
        ),
        Case(
            name="EN No booking confirmation",
            language="en",
            user_question="Can you confirm availability for Jan 10 and book it now?",
            evidence=[
                {
                    "id": "faq-061",
                    "question": "What are the departure dates?",
                    "answer": "Published departures include January 10.",
                }
            ],
            must_have=[r"human advisor|specialist", r"email"],
            must_not_have=[r"booked|reservation confirmed|confirmed availability"],
        ),
        Case(
            name="ES Sin evidencia",
            language="es",
            user_question="Que viento exacto habra el 2 de enero en cumbre?",
            evidence=[],
            must_have=[r"No dispongo de esa información"],
            must_not_have=[r"km/h|exactamente"],
        ),
        Case(
            name="EN Plaza Francia",
            language="en",
            user_question="Do you have information for a trek to Plaza Francia?",
            evidence=[
                {
                    "id": "faq-063",
                    "question": "Do you have information for a trek to Plaza Francia?",
                    "answer": "Private trips only. Price is USD 1,399 per person (minimum 2 people).",
                }
            ],
            must_have=[r"USD\s*1[\.,]?399", r"private"],
            must_not_have=[r"group departures available"],
        ),
    ]

    passed = 0
    print(f"Running {len(cases)} prompt tests with model={model} ...")
    for i, case in enumerate(cases, start=1):
        ok, answer, errors = run_case(client, model, prompt, case)
        status = "PASS" if ok else "FAIL"
        print(f"[{i}/{len(cases)}] {status} - {case.name}")
        if ok:
            passed += 1
        else:
            for err in errors:
                print(f"  - {err}")
            print(f"  - answer: {answer}")

    print(f"\nSummary: {passed}/{len(cases)} passed")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
