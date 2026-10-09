#!/usr/bin/env python3
"""Extract what advisors (Fernando) answered in real WhatsApp conversations.

Fernando's replies are the most up-to-date source of truth, newer than the
FAQ. This pulls every advisor message from Supabase with the client messages
it answered and, when there is one, what Nico had said just before (useful to
spot where Fernando corrected Nico).

Output goes to private/ (git-ignored): the repository is public and these
are real customer conversations. Emails and phone numbers are redacted, but
names and other details can remain, so never commit these files.

Usage:
    python3 scripts/extract_advisor_answers.py               # last 120 days
    python3 scripts/extract_advisor_answers.py --days 365
    python3 scripts/extract_advisor_answers.py --max-conversations 50

Then ask Claude to read private/advisor_answers.md and propose facts for the
"Respuestas confirmadas por Fernando" section of docs/knowledge/datos-clave.md.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orchestrator.conversation_audit import (  # noqa: E402
    DEFAULT_ORG_ID,
    _fetch_conversations,
    _load_env_if_available,
    _supabase_get,
)
from orchestrator.human_activity import DEFAULT_NICO_AGENT_ID, is_human_message  # noqa: E402

OUT_DIR = ROOT / "private"

_EMAIL_RE = re.compile(r"[\w.%+-]+@[\w.-]+\.[a-zA-Z]{2,}")
# 7+ digits, allowing spaces, dashes, dots, parentheses and a leading +.
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{5,}\d")


_CURRENCY_BEFORE_RE = re.compile(r"(?:usd|us\$|u\$s|\$|dolares|dólares|dollars)\s*$", re.IGNORECASE)
# "5990 - 6390", "5.990-6.390": a price range, not a phone number.
_PRICE_RANGE_RE = re.compile(r"\d{1,2}[.,]?\d{3}\s*[-–]\s*\d{1,2}[.,]?\d{3}")


def redact(text: str) -> str:
    text = _EMAIL_RE.sub("[email]", text or "")

    def phone(match: re.Match[str]) -> str:
        value = match.group(0)
        before = text[max(0, match.start() - 12) : match.start()]
        if (
            len(re.sub(r"\D", "", value)) < 7
            or _CURRENCY_BEFORE_RE.search(before)
            or _PRICE_RANGE_RE.fullmatch(value.strip())
        ):
            return value
        return "[telefono]"

    return _PHONE_RE.sub(phone, text)


def _role(message: dict[str, Any], nico_agent_id: str) -> str:
    if is_human_message(message, nico_agent_id):
        return "advisor"
    if message.get("agent_id") == nico_agent_id:
        return "nico"
    return "client"


def build_advisor_exchanges(messages: list[dict[str, Any]], nico_agent_id: str) -> list[dict[str, Any]]:
    """Group a conversation into advisor answers with what they answered.

    `messages` are rows with agent_id, sender_address, content and timestamp,
    in time order. Consecutive advisor messages form one answer.
    """
    exchanges: list[dict[str, Any]] = []
    client_buffer: list[str] = []
    last_nico: str = ""
    current: dict[str, Any] | None = None

    for message in messages:
        content = message.get("content")
        if not isinstance(content, dict) or content.get("kind") != "text":
            continue
        text = redact(str(content.get("text") or "")).strip()
        if not text:
            continue
        role = _role(message, nico_agent_id)
        if role == "advisor":
            if current is None:
                current = {
                    "timestamp": str(message.get("timestamp") or ""),
                    "client_asked": list(client_buffer),
                    "nico_said_before": last_nico,
                    "advisor_answer": [],
                }
                exchanges.append(current)
                client_buffer = []
            current["advisor_answer"].append(text)
            continue
        current = None
        if role == "client":
            client_buffer.append(text)
        else:
            last_nico = text
            client_buffer = []
    return exchanges


def _fetch_messages(base_url: str, api_key: str, conversation_id: str) -> list[dict[str, Any]]:
    return _supabase_get(
        base_url,
        api_key,
        "messages",
        {
            "conversation_id": f"eq.{conversation_id}",
            "select": "agent_id,sender_address,content,timestamp",
            "order": "timestamp.asc",
            "limit": 1000,
        },
    )


def _to_markdown(items: list[dict[str, Any]]) -> str:
    lines = [
        "# Respuestas de asesores en conversaciones reales",
        "",
        "PRIVADO: conversaciones reales de clientes. No commitear.",
        "",
    ]
    for i, item in enumerate(items, 1):
        lines.append(f"## {i}. {item['timestamp'][:10]}")
        if item["client_asked"]:
            lines.append("**Cliente:** " + " / ".join(item["client_asked"]))
        if item["nico_said_before"]:
            lines.append("**Nico antes:** " + item["nico_said_before"])
        lines.append("**Asesor:** " + " / ".join(item["advisor_answer"]))
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--days", type=int, default=120, help="conversations updated in the last N days")
    parser.add_argument("--max-conversations", type=int, default=None)
    args = parser.parse_args()

    _load_env_if_available()
    base_url = os.environ.get("SUPABASE_URL")
    api_key = os.environ.get("SUPABASE_SECRET_KEY")
    if not base_url or not api_key:
        raise SystemExit("Missing SUPABASE_URL or SUPABASE_SECRET_KEY (put them in .env)")
    org_id = os.environ.get("OPENBSP_ORGANIZATION_ID", DEFAULT_ORG_ID)
    nico_agent_id = os.environ.get("NICO_AGENT_ID", DEFAULT_NICO_AGENT_ID)

    conversations = _fetch_conversations(base_url, api_key, org_id, days_back=args.days, max_conversations=args.max_conversations)
    items: list[dict[str, Any]] = []
    for conv in conversations:
        for exchange in build_advisor_exchanges(_fetch_messages(base_url, api_key, conv["id"]), nico_agent_id):
            items.append({"conversation": conv["id"][:8], **exchange})
    items.sort(key=lambda x: x["timestamp"], reverse=True)

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "advisor_answers.json").write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUT_DIR / "advisor_answers.md").write_text(_to_markdown(items), encoding="utf-8")
    print(f"{len(conversations)} conversaciones, {len(items)} respuestas de asesores → {OUT_DIR}/advisor_answers.md")


if __name__ == "__main__":
    main()
