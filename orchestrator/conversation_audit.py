#!/usr/bin/env python3
"""Conversation auditing helpers for Acomara orchestrator.

This module fetches conversations/messages from Supabase and computes
quality and reliability metrics that can be served through HTTP endpoints
or generated as periodic reports.
"""

from __future__ import annotations

import os
import re
import unicodedata
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
    "quisiera",
    "precio",
    "fechas",
    "salida",
    "disponibles",
    "asesor",
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
    "would like",
    "departure",
    "available",
    "price",
    "how",
    "are",
    "can",
    "could",
    "please",
    "plan",
    "together",
    "human",
    "email",
    "english",
    "contact",
    "help",
    "thanks",
    "yes",
    "have",
    "need",
    "want",
    "call",
)
PT_KEYWORDS = (
    "ola",
    "obrigado",
    "por favor",
    "quero",
    "gostaria",
    "informacao",
    "datas",
    "preco",
    "assessor",
    "expedicao",
    "disponiveis",
)
IT_KEYWORDS = (
    "ciao",
    "grazie",
    "per favore",
    "vorrei",
    "informazioni",
    "data",
    "date",
    "prezzo",
    "consulente",
    "spedizione",
    "disponibili",
    "posso",
)
FR_KEYWORDS = (
    "bonjour",
    "merci",
    "s il vous plait",
    "je voudrais",
    "informations",
    "dates",
    "prix",
    "conseiller",
    "expedition",
    "disponibles",
)

LANGUAGE_PREFERENCE_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "en": (
        re.compile(r"\benglish\s+please\b", re.IGNORECASE),
        re.compile(r"\bi\s+don(?:'|’)?t\s+speak\s+spanish\b", re.IGNORECASE),
        re.compile(r"\bspeak\s+english\b", re.IGNORECASE),
    ),
    "es": (
        re.compile(r"\bespanol\s+por\s+favor\b", re.IGNORECASE),
        re.compile(r"\bhabla\s+en\s+espanol\b", re.IGNORECASE),
        re.compile(r"\bno\s+hablo\s+ingles\b", re.IGNORECASE),
    ),
    "pt": (
        re.compile(r"\bportugues\s+por\s+favor\b", re.IGNORECASE),
        re.compile(r"\bfale\s+em\s+portugues\b", re.IGNORECASE),
    ),
    "it": (
        re.compile(r"\bin\s+italiano\b", re.IGNORECASE),
        re.compile(r"\bparla\s+italiano\b", re.IGNORECASE),
    ),
    "fr": (
        re.compile(r"\ben\s+francais\b", re.IGNORECASE),
        re.compile(r"\bparlez\s+francais\b", re.IGNORECASE),
    ),
}

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


def _normalize_for_language_detection(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _score_language(text: str, keywords: tuple[str, ...]) -> int:
    normalized = _normalize_for_language_detection(text)
    score = 0
    for keyword in keywords:
        normalized_keyword = _normalize_for_language_detection(keyword)
        if not normalized_keyword:
            continue
        if " " in normalized_keyword:
            if normalized_keyword in normalized:
                score += 2
        else:
            score += len(re.findall(r"\b" + re.escape(normalized_keyword) + r"\b", normalized))
    return score


def _dominant_language(labels: list[str]) -> str:
    non_unknown = [label for label in labels if label != "unknown"]
    if non_unknown:
        return Counter(non_unknown).most_common(1)[0][0]
    if labels:
        return Counter(labels).most_common(1)[0][0]
    return "unknown"


def _detect_language(text: str) -> str:
    scores = {
        "es": _score_language(text, ES_KEYWORDS),
        "en": _score_language(text, EN_KEYWORDS),
        "pt": _score_language(text, PT_KEYWORDS),
        "it": _score_language(text, IT_KEYWORDS),
        "fr": _score_language(text, FR_KEYWORDS),
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_lang, top_score = ranked[0]
    runner_up = ranked[1][1] if len(ranked) > 1 else 0

    # Keep the detector conservative: require at least two hits, or a clear
    # margin over the runner-up. Short greetings and mixed sentences remain
    # unknown so the audit does not over-attribute drift.
    if top_score < 2:
        return "unknown"
    if top_score == runner_up:
        return "unknown"
    if top_score == 2 and runner_up > 0:
        return "unknown"
    return top_lang


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
    apply_days_back_filter: bool = True,
) -> list[dict[str, Any]]:
    conversations: list[dict[str, Any]] = []
    offset = 0
    page_size = 500
    updated_since = None
    if apply_days_back_filter and days_back is not None:
        updated_since = (datetime.now(timezone.utc) - timedelta(days=days_back)).isoformat()

    while True:
        params: dict[str, Any] = {
            "organization_id": f"eq.{organization_id}",
            "select": "id,created_at,updated_at,contact_address",
            "order": "updated_at.asc",
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
                "timestamp": str(message.get("timestamp") or ""),
            }
        )
    return text_messages


def _latest_message_timestamp(messages: list[dict[str, str]]) -> datetime | None:
    latest: datetime | None = None
    for message in messages:
        raw_timestamp = str(message.get("timestamp") or "").strip()
        if not raw_timestamp:
            continue
        try:
            parsed = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest


def _is_control_command(text: str) -> bool:
    stripped = (text or "").strip().lower()
    return stripped.startswith("/reset") or stripped.startswith("/new")


def _detect_language_preference(text: str) -> str | None:
    normalized = _normalize_for_language_detection(text)
    for lang, patterns in LANGUAGE_PREFERENCE_PATTERNS.items():
        if any(pattern.search(normalized) for pattern in patterns):
            return lang
    return None


def _count_language_drift(messages: list[dict[str, str]]) -> tuple[int, dict[str, Any]]:
    """Count drift by comparing each assistant turn to user expectation.

    Expectations are derived per segment (split by /reset and /new):
    - explicit language preference from user text (highest priority),
    - otherwise last detectable user language in the segment.
    """
    mismatches = 0
    assistant_turns = 0
    segment_id = 0
    locked_lang_by_segment: dict[int, str] = {}
    last_user_lang_by_segment: dict[int, str] = {}

    for msg in messages:
        role = msg.get("role")
        text = str(msg.get("text") or "")

        if role == "user":
            if _is_control_command(text):
                segment_id += 1
                continue

            preferred = _detect_language_preference(text)
            if preferred:
                locked_lang_by_segment[segment_id] = preferred

            detected = _detect_language(text)
            if detected != "unknown":
                last_user_lang_by_segment[segment_id] = detected
            continue

        if role != "assistant":
            continue

        assistant_turns += 1
        expected = locked_lang_by_segment.get(segment_id) or last_user_lang_by_segment.get(segment_id)
        if not expected:
            continue

        assistant_lang = _detect_language(text)
        if assistant_lang not in ("unknown", expected):
            mismatches += 1

    return mismatches, {
        "assistant_turns": assistant_turns,
        "segments": segment_id + 1,
        "locked_lang_by_segment": locked_lang_by_segment,
    }


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
        apply_days_back_filter=False,
    )

    cutoff_ts: datetime | None = None
    if days_back is not None:
        cutoff_ts = datetime.now(timezone.utc) - timedelta(days=days_back)

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

        latest_activity_at = _latest_message_timestamp(messages)
        if cutoff_ts is not None and latest_activity_at is not None and latest_activity_at < cutoff_ts:
            continue

        message_counts.append(len(messages))
        user_texts = [m["text"] for m in messages if m["role"] == "user"]
        bot_texts = [m["text"] for m in messages if m["role"] == "assistant"]

        issues: list[str] = []

        user_langs = [_detect_language(text) for text in user_texts]
        predominant_user_lang = _dominant_language(user_langs)
        if predominant_user_lang != "unknown":
            language_counts[predominant_user_lang] += 1

        mismatches, drift_debug = _count_language_drift(messages)
        if mismatches > 0:
            issues.append("LANGUAGE_DRIFT")

        # Count only truly consecutive assistant duplicates in the full turn
        # timeline. This avoids false positives when the user writes between
        # two equal bot replies (e.g. handoff confirmation + user "ok").
        duplicate_replies = sum(
            1
            for i in range(len(messages) - 1)
            if messages[i]["role"] == "assistant"
            and messages[i + 1]["role"] == "assistant"
            and messages[i]["text"].strip()
            and messages[i]["text"].strip() == messages[i + 1]["text"].strip()
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
                    "latest_activity_at": latest_activity_at.isoformat() if latest_activity_at else None,
                    "contact_address": conv.get("contact_address"),
                    "message_count": len(messages),
                    "issues": issues,
                    "language_drift_mismatches": mismatches,
                    "language_drift_debug": drift_debug,
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
