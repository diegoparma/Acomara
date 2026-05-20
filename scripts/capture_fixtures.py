#!/usr/bin/env python3
"""Capture conversation transcripts from Supabase as test fixtures.

Read-only. Pulls a curated set of conversations identified as useful for
regression testing (loops, email captures, price inconsistencies, clean
baselines) and saves them as JSON files in tests/fixtures/conversations/.

Usage:
    python3 scripts/capture_fixtures.py
    python3 scripts/capture_fixtures.py --ids 7726ce7d-... 1d0d5e8f-...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "conversations"

# Curated fixture set: each tuple is (conversation_id, short_label, why).
DEFAULT_FIXTURES: list[tuple[str, str, str]] = [
    ("14b02acd-2234-4bc8-9412-389055ee1185", "clean_baseline", "single-turn clean response"),
    ("1d0d5e8f-ec84-450e-b92b-9ea1491b9780", "wes_handoff_ok", "successful email capture + handoff"),
    ("7726ce7d-1fe7-4992-966d-a92e1e93ff55", "jacques_email_loop", "EMAIL_LOOP_AFTER_CAPTURE"),
    ("11953b50-c036-4bab-83b7-666b718dc076", "plaza_francia_price", "PRICE_INCONSISTENCY 1399 vs 1499 + dates list"),
    ("9801750c-4cd4-48c7-bf91-45090c92fb47", "language_drift", "LANGUAGE_DRIFT"),
    ("c484409c-eebe-448f-a512-971e59dffdef", "duplicate_replies", "DUPLICATE_REPLIES"),
    ("b1753aee-1bf6-4630-9ceb-9d8165c9f194", "recent_email_repeat", "EMAIL_REQUEST_REPEATED, recent"),
    ("0b1fdd91-9595-4425-9366-5e9d2ba95fe6", "pathological", "all 5 issue classes present"),
]


def fetch_conversation(base_url: str, api_key: str, conversation_id: str) -> dict | None:
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    conv_resp = requests.get(
        f"{base_url.rstrip('/')}/rest/v1/conversations",
        params={
            "id": f"eq.{conversation_id}",
            "select": "id,created_at,updated_at,contact_address,organization_id",
            "limit": 1,
        },
        headers=headers,
        timeout=30,
    )
    conv_resp.raise_for_status()
    rows = conv_resp.json()
    if not rows:
        return None
    conv = rows[0]

    msg_resp = requests.get(
        f"{base_url.rstrip('/')}/rest/v1/messages",
        params={
            "conversation_id": f"eq.{conversation_id}",
            "select": "direction,content,timestamp",
            "order": "timestamp.asc",
            "limit": 2000,
        },
        headers=headers,
        timeout=30,
    )
    msg_resp.raise_for_status()
    raw_messages = msg_resp.json()

    turns: list[dict] = []
    for m in raw_messages:
        content = m.get("content") or {}
        if not isinstance(content, dict) or content.get("kind") != "text":
            continue
        turns.append(
            {
                "role": "assistant" if m.get("direction") == "outgoing" else "user",
                "text": str(content.get("text") or ""),
                "timestamp": m.get("timestamp"),
            }
        )

    return {
        "id": conv["id"],
        "created_at": conv.get("created_at"),
        "updated_at": conv.get("updated_at"),
        "contact_address": conv.get("contact_address"),
        "organization_id": conv.get("organization_id"),
        "turns": turns,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", nargs="*", help="Specific conversation_ids to capture; defaults to curated set")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    base_url = os.getenv("SUPABASE_URL", "https://nheelwshzbgenpavwhcy.supabase.co")
    api_key = os.getenv("SUPABASE_SECRET_KEY")
    if not api_key:
        print("ERROR: SUPABASE_SECRET_KEY not set", file=sys.stderr)
        return 1

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    if args.ids:
        targets = [(cid, cid[:8], "ad-hoc") for cid in args.ids]
    else:
        targets = DEFAULT_FIXTURES

    index: list[dict] = []
    for conv_id, label, why in targets:
        print(f"  fetching {label} ({conv_id[:8]}) — {why}", file=sys.stderr)
        data = fetch_conversation(base_url, api_key, conv_id)
        if data is None:
            print(f"    WARN: not found", file=sys.stderr)
            continue
        data["fixture_label"] = label
        data["fixture_purpose"] = why
        out_path = FIXTURE_DIR / f"{label}__{conv_id}.json"
        out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        index.append({
            "label": label,
            "conversation_id": conv_id,
            "purpose": why,
            "turns": len(data["turns"]),
            "file": out_path.name,
        })
        print(f"    -> {out_path.relative_to(ROOT)} ({len(data['turns'])} turns)", file=sys.stderr)

    (FIXTURE_DIR / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nCaptured {len(index)} fixtures into {FIXTURE_DIR.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
