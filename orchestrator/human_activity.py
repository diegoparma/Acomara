"""Detect recent human replies so Nico stays out of conversations an advisor took over.

Advisors often answer from the WhatsApp Business phone app. Those messages
never reach the orchestrator, so the only place to see them is the OpenBSP
messages table in Supabase.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests

DEFAULT_NICO_AGENT_ID = "50ce8caf-1088-4a42-ac2e-bda296174530"


def is_human_message(message: dict[str, Any], nico_agent_id: str) -> bool:
    """True for outbound messages written by a person, not by Nico or the client.

    - Client messages carry a sender_address and no agent_id.
    - Nico's messages carry Nico's agent_id.
    - Advisors on the OpenBSP platform carry their own agent_id.
    - Advisors on the WhatsApp Business phone app carry neither.
    """
    agent_id = message.get("agent_id")
    if agent_id:
        return agent_id != nico_agent_id
    return not message.get("sender_address")


def last_human_message_at(messages: list[dict[str, Any]], nico_agent_id: str) -> datetime | None:
    latest: datetime | None = None
    for message in messages:
        if not is_human_message(message, nico_agent_id):
            continue
        try:
            ts = datetime.fromisoformat(str(message.get("timestamp") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if latest is None or ts > latest:
            latest = ts
    return latest


def human_replied_recently(
    *,
    supabase_url: str | None,
    supabase_key: str | None,
    conversation_id: str,
    window_hours: float,
    nico_agent_id: str = DEFAULT_NICO_AGENT_ID,
    timeout_seconds: float = 2.0,
    now: datetime | None = None,
) -> tuple[bool, dict[str, Any]]:
    """Return (silence_nico, debug_info).

    Fails open: any missing config, timeout or error returns False so the
    client still gets Nico's reply.
    """
    if not supabase_url or not supabase_key or not conversation_id or window_hours <= 0:
        return False, {"checked": False, "reason": "not_configured"}

    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(hours=window_hours)).isoformat()
    try:
        response = requests.get(
            f"{supabase_url.rstrip('/')}/rest/v1/messages",
            params={
                # Always scope by conversation: this Supabase is shared by every
                # OpenBSP organization.
                "conversation_id": f"eq.{conversation_id}",
                "timestamp": f"gte.{since}",
                "select": "agent_id,sender_address,timestamp",
                "order": "timestamp.desc",
                "limit": 50,
            },
            headers={"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        rows = response.json()
    except Exception as exc:  # noqa: BLE001 - fail open on any error
        return False, {"checked": False, "reason": f"error: {type(exc).__name__}"}

    if not isinstance(rows, list):
        return False, {"checked": False, "reason": "unexpected_response"}

    last_human = last_human_message_at(rows, nico_agent_id)
    return last_human is not None, {
        "checked": True,
        "recent_messages": len(rows),
        "last_human_message_at": last_human.isoformat() if last_human else None,
        "window_hours": window_hours,
    }
