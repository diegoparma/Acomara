#!/usr/bin/env python3
"""Conversation auditing helpers for Acomara orchestrator.

This module fetches conversations/messages from Supabase and computes
quality and reliability metrics that can be served through HTTP endpoints
or generated as periodic reports.
"""

from __future__ import annotations

import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ORG_ID = "7cb6ffa2-4452-4d65-b880-bfa31b197eee"
KNOWN_TEST_CONVERSATION_IDS = {
    "361e99c8-e6ab-4264-a7ee-ff71ce146d25",
}

ES_KEYWORDS = (
    "hola",
    "buen",
    "dias",
    "tarde",
    "noche",
    "gracias",
    "por favor",
    "como",
    "cual",
    "quiero",
    "informacion",
    "aconcagua",
)
EN_KEYWORDS = (
    "hello",
    "hi",
    "good",
    "morning",
    "evening",
    "thanks",
    "please",
    "how",
    "which",
    "i want",
    "information",
    "aconcagua",
)

CRM_ERROR_PATTERNS = (
    "crm",
    "client lookup failed",
    "database error",
    "unable to find",
    "sql",
    "mysql",
    "timeout",
    "error al consultar",
)
PAUSED_PATTERNS = (
    "we'll be in touch",
    "sera en breve",
    "en contacto",
    "asesor humano",
)
SENSITIVE_PATTERNS = (
    r"deployment[_-]?id",
    r"vercel",
    r"session[_-]?url",
    r"supabase",
    r"database",
    r"api[_-]?key",
    r"bearer\s+[a-z0-9\-_\.]+",
    r"openai[_-]?api[_-]?key",
)


def _load_env_if_available() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _detect_language(text: str) -> str:
    lowered = (text or "").lower()
    es_count = sum(1 for key in ES_KEYWORDS if re.search(r"\b" + re.escape(key) + r"\b", lowered))
    en_count = sum(1 for key in EN_KEYWORDS if re.search(r"\b" + re.escape(key) + r"\b", lowered))
    if es_count > en_count:
        return "es"
    if en_count > es_count:
        return "en"
    return "unknown"


def _supabase_get(base_url: str, api_key: str, table: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    response = requests.get(
        f"{base_url.rstrip('/')}/rest/v1/{table}",
        params=params,
        headers={
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def _fetch_conversations(
    base_url: str,
    api_key: str,
    organization_id: str,
    days_back: int | None = None,
    max_conversations: int | None = None,
) -> list[dict[str, Any]]:
    conversations: list[dict[str, Any]] = []
    offset = 0
    page_size = 500
    updated_since = None
    if days_back is not None:
        updated_since = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()

    while True:
        params: dict[str, Any] = {
            "organization_id": f"eq.{organization_id}",
            "select": "id,created_at,updated_at,contact_address",
            "order": "created_at.asc",
            "limit": page_size,
            "offset": offset,
        }
        if updated_since:
            params["updated_at"] = f"gte.{updated_since}"

        batch = _supabase_get(base_url, api_key, "conversations", params)
        if not batch:
            break

        conversations.extend(batch)
        if max_conversations is not None and len(conversations) >= max_conversations:
            return conversations[:max_conversations]

        if len(batch) < page_size:
            break
        offset += page_size

    return conversations


def _fetch_text_messages(base_url: str, api_key: str, conversation_id: str) -> list[dict[str, str]]:
    messages = _supabase_get(
        base_url,
        api_key,
        "messages",
        {
            "conversation_id": f"eq.{conversation_id}",
            "select": "direction,content,timestamp",
            "order": "timestamp.asc",
            "limit": 1000,
        },
    )

    text_messages: list[dict[str, str]] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, dict) or content.get("kind") != "text":
            continue
        text_messages.append(
            {
                "role": "assistant" if message.get("direction") == "outgoing" else "user",
                "text": str(content.get("text") or ""),
            }
        )
    return text_messages


def run_conversation_audit(
    organization_id: str = DEFAULT_ORG_ID,
    days_back: int | None = None,
    include_test_conversations: bool = False,
    max_conversations: int | None = None,
) -> dict[str, Any]:
    _load_env_if_available()
    supabase_url = os.getenv("SUPABASE_URL", "https://nheelwshzbgenpavwhcy.supabase.co")
    supabase_key = os.getenv("SUPABASE_SECRET_KEY")

    if not supabase_key:
        raise RuntimeError("Missing SUPABASE_SECRET_KEY")

    conversations = _fetch_conversations(
        base_url=supabase_url,
        api_key=supabase_key,
        organization_id=organization_id,
        days_back=days_back,
        max_conversations=max_conversations,
    )

    issue_counts: Counter[str] = Counter()
    language_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    message_counts: list[int] = []
    problematic_rows: list[dict[str, Any]] = []

    excluded_test_conversations = 0

    for conv in conversations:
        conv_id = str(conv.get("id") or "")
        if not include_test_conversations and conv_id in KNOWN_TEST_CONVERSATION_IDS:
            excluded_test_conversations += 1
            continue

        messages = _fetch_text_messages(supabase_url, supabase_key, conv_id)
        if not messages:
            status_counts["NO_MESSAGES"] += 1
            problematic_rows.append(
                {
                    "conversation_id": conv_id,
                    "created_at": conv.get("created_at"),
                    "updated_at": conv.get("updated_at"),
                    "contact_address": conv.get("contact_address"),
                    "message_count": 0,
                    "issues": ["NO_MESSAGES"],
                }
            )
            continue

        message_counts.append(len(messages))
        user_texts = [m["text"] for m in messages if m["role"] == "user"]
        bot_texts = [m["text"] for m in messages if m["role"] == "assistant"]

        issues: list[str] = []

        user_langs = [_detect_language(text) for text in user_texts]
        bot_langs = [_detect_language(text) for text in bot_texts]
        predominant_user_lang = "unknown"
        if user_langs:
            predominant_user_lang = Counter(user_langs).most_common(1)[0][0]
            language_counts[predominant_user_lang] += 1

        mismatches = sum(
            1
            for lang in bot_langs
            if predominant_user_lang != "unknown" and lang not in ("unknown", predominant_user_lang)
        )
        if mismatches > 0:
            issues.append("LANGUAGE_DRIFT")

        duplicate_replies = sum(
            1
            for i in range(len(bot_texts) - 1)
            if bot_texts[i].strip() and bot_texts[i].strip() == bot_texts[i + 1].strip()
        )
        if duplicate_replies > 0:
            issues.append("DUPLICATE_REPLIES")

        paused_hits = sum(1 for text in bot_texts if any(pattern in text.lower() for pattern in PAUSED_PATTERNS))
        if paused_hits >= 3:
            issues.append("PAUSED_LOOP")

        crm_hits = sum(1 for text in bot_texts if any(pattern in text.lower() for pattern in CRM_ERROR_PATTERNS))
        if crm_hits > 0:
            issues.append("CRM_ISSUES")

        sensitive_hits = sum(
            1 for text in bot_texts if any(re.search(pattern, text, re.IGNORECASE) for pattern in SENSITIVE_PATTERNS)
        )
        if sensitive_hits > 0:
            issues.append("INFO_EXPOSURE")

        if issues:
            status_counts["ERROR_OR_WARN"] += 1
            for issue in issues:
                issue_counts[issue] += 1
            problematic_rows.append(
                {
                    "conversation_id": conv_id,
                    "created_at": conv.get("created_at"),
                    "updated_at": conv.get("updated_at"),
                    "contact_address": conv.get("contact_address"),
                    "message_count": len(messages),
                    "issues": issues,
                }
            )
        else:
            status_counts["OK"] += 1

    message_stats: dict[str, Any]
    if message_counts:
        ordered = sorted(message_counts)
        n = len(ordered)
        median = ordered[n // 2] if n % 2 == 1 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2
        message_stats = {
            "min": min(ordered),
            "max": max(ordered),
            "avg": round(sum(ordered) / n, 2),
            "median": median,
            "total_messages": int(sum(ordered)),
        }
    else:
        message_stats = {"min": 0, "max": 0, "avg": 0, "median": 0, "total_messages": 0}

    audited_conversations = sum(status_counts.values())
    with_issues = status_counts.get("ERROR_OR_WARN", 0) + status_counts.get("NO_MESSAGES", 0)
    quality_rate = round(((audited_conversations - with_issues) / audited_conversations) * 100, 2) if audited_conversations else 0.0

    top_problematic = sorted(problematic_rows, key=lambda x: x.get("message_count", 0), reverse=True)[:25]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "organization_id": organization_id,
        "days_back": days_back,
        "include_test_conversations": include_test_conversations,
        "excluded_test_conversations": excluded_test_conversations,
        "totals": {
            "fetched_conversations": len(conversations),
            "audited_conversations": audited_conversations,
            "conversations_with_issues": with_issues,
            "quality_rate_percent": quality_rate,
        },
        "status_counts": dict(status_counts),
        "issue_counts": dict(issue_counts),
        "message_stats": message_stats,
        "language_distribution": dict(language_counts),
        "problematic_conversations": top_problematic,
    }
