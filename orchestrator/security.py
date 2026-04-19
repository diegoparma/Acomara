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
    
    # Already requested or already verified
    if session_vars.get("email_requested"):
        return False
    if session_vars.get("email_verified"):
        return False
    if session_vars.get("email_compromised"):
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
    email: str,
    reason: str,
) -> dict[str, Any]:
    """
    Mark conversation as paused due to security concern.
    """
    return {
        **session_vars,
        "conversation_paused": True,
        "pause_reason": reason,
        "paused_email": email,
        "paused_at_ts": int(time.time()),
    }
