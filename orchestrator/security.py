#!/usr/bin/env python3
"""Security and email verification utilities for the sales agent."""

from urllib.parse import quote
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def check_email_reputation(
    email: str,
    api_key: str,
    timeout: int = 10,
) -> tuple[bool, bool]:
    """
    Check email reputation against Have I Been Pwned API v3.
    
    Inverted logic: validated accounts appear in breach databases (have real history).
    Suspicious accounts do NOT appear in any breach (likely new/fake/spam).
    
    Uses Have I Been Pwned v3 breached account endpoint.
    
    Returns: (is_suspicious, check_succeeded)
    - is_suspicious: True if email NOT found in breached databases (new/unverified)
    - is_suspicious: False if email found in breached databases (real account)
    - check_succeeded: True if check completed successfully
    """
    try:
        if not api_key:
            return False, False

        normalized_email = email.strip().lower()
        encoded_email = quote(normalized_email, safe="")
        url = (
            "https://haveibeenpwned.com/api/v3/breachedaccount/"
            f"{encoded_email}?truncateResponse=true"
        )

        headers = {
            "User-Agent": "Acomara-SalesAgent/1.0",
            "hibp-api-key": api_key,
            "Accept": "application/json",
        }

        req = Request(url=url, headers=headers, method="GET")

        with urlopen(req, timeout=timeout) as resp:
            # 200 means account has breach history = REAL (not suspicious)
            if resp.getcode() == 200:
                return False, True
            return True, False

    except HTTPError as e:
        # 404 means no breaches for that account = SUSPICIOUS (new/unverified)
        if e.code == 404:
            return True, True
        if e.code == 429:
            return False, False
        return False, False
    except (URLError, TimeoutError, Exception):
        return False, False


def should_request_email(session_vars: dict[str, Any]) -> bool:
    """
    Determine if agent should request email in this turn.
    
    Request email after ~3-4 turns of conversation when prospect 
    is engaged but before attempting to convert.
    """
    turn_count = session_vars.get("conversation_turn_count", 0)

    # Block re-request if the email was already requested, captured or verified
    # (single-ask rule). Any of these flags means we must not ask again.
    blocking_flags = (
        "email_requested",
        "email_captured",
        "captured_email",
        "email_verified",
        "verified_email",
        "email_compromised",
    )
    if any(session_vars.get(flag) for flag in blocking_flags):
        return False

    # Request specifically around turns 3-4 in normal flow.
    return 3 <= turn_count <= 4


def extract_email_from_text(text: str) -> str | None:
    """
    Simple email extraction from user message.
    Looks for common email patterns.
    """
    # Very basic email regex - match word chars, dots, hyphens @ domain
    import re
    pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    matches = re.findall(pattern, text)
    return matches[0] if matches else None


def pause_conversation(
    session_vars: dict[str, Any],
    email: str | None,
    reason: str,
) -> dict[str, Any]:
    """
    Mark conversation as paused due to security concern or other reason.
    """
    updated = {
        **session_vars,
        "conversation_paused": True,
        "pause_reason": reason,
        "paused_at_ts": int(time.time()),
    }
    if email:
        updated["paused_email"] = email
    return updated


BARE_EMAIL_MAX_EXTRA_CHARS = 15
MAX_DISTINCT_EMAILS = 3


def bot_signal(
    session_vars: dict[str, Any],
    text: str,
    email: str,
    email_in_breaches: bool,
) -> str | None:
    """Return a reason when the conversation looks automated, else None.

    A missing breach history alone is NOT a bot signal: in real traffic one in
    three genuine leads (long, specific conversations) had emails absent from
    HIBP. Only pause when the behaviour itself looks automated.
    """
    emails_seen = {str(e).lower() for e in session_vars.get("emails_seen") or []}
    emails_seen.add(email.lower())
    if len(emails_seen) >= MAX_DISTINCT_EMAILS:
        return "many_distinct_emails"

    turn_count = int(session_vars.get("conversation_turn_count") or 0)
    extra_text = (text or "").replace(email, "").strip()
    if not email_in_breaches and turn_count <= 2 and len(extra_text) < BARE_EMAIL_MAX_EXTRA_CHARS:
        return "bare_email_without_conversation"

    return None

