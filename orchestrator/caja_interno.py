"""Route team phones to the internal cash-flow agent (Zurbriggen's "caja").

Nico shares its WhatsApp number with the internal agent that lives in the
aconcagua-plan-admin repo (api/agente.js). This module is the only contact
point: when the sender is on the team list, the message goes to that agent and
its reply is returned as the completion; everyone else keeps going to sales.

The decision is made here by comparing phone numbers, never by a model. The
team list comes from the agent itself and is cached, so adding someone in the
caja dashboard is enough. If the agent can't be reached, clients are
unaffected: an unknown list means "nobody is team".

Env: CAJA_AGENTE_URL (e.g. https://aconcagua-plan-admin.vercel.app/api/agente)
and CAJA_AGENT_KEY. Without both, the route is off and nothing changes.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

TEAM_TTL_SECONDS = 300
TEAM_TIMEOUT_SECONDS = 3
AGENT_TIMEOUT_SECONDS = 50
UNAVAILABLE_REPLY = "Ahora no puedo llegar a la caja. Probá de nuevo en unos minutos."

_team_lock = threading.Lock()
_team_cache: dict[str, Any] = {"at": 0.0, "phones": frozenset()}


def _config() -> tuple[str, str] | None:
    url = (os.getenv("CAJA_AGENTE_URL") or "").strip().rstrip("/")
    key = (os.getenv("CAJA_AGENT_KEY") or "").strip()
    return (url, key) if url and key else None


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _same_phone(a: str, b: str) -> bool:
    # Tolerates the usual Argentine variants (+54 9 261..., 54261..., 0261 15...).
    return len(a) >= 8 and len(b) >= 8 and (a == b or a[-10:] == b[-10:])


def _call(url: str, key: str, method: str, body: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    req = Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    })
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode() or "{}")


def _team_phones(url: str, key: str) -> frozenset[str]:
    now = time.time()
    with _team_lock:
        if now - _team_cache["at"] < TEAM_TTL_SECONDS:
            return _team_cache["phones"]
    try:
        data = _call(f"{url}?a=equipo", key, "GET", None, TEAM_TIMEOUT_SECONDS)
        phones = frozenset(_digits(p) for p in data.get("telefonos", []) if len(_digits(p)) >= 8)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        print(f"[CAJA_INTERNO] team list unavailable: {exc}", flush=True)
        with _team_lock:
            phones = _team_cache["phones"]  # keep the last known list
            _team_cache["at"] = now - TEAM_TTL_SECONDS + 30  # retry in 30 s
        return phones
    with _team_lock:
        _team_cache.update(at=now, phones=phones)
    return phones


def is_team_phone(contact_address: str) -> bool:
    cfg = _config()
    if not cfg:
        return False
    d = _digits(contact_address)
    return any(_same_phone(d, p) for p in _team_phones(*cfg))


def internal_reply(contact_address: str, user_text: str) -> str | None:
    """The internal agent's reply for a team phone, or None to continue with sales."""
    cfg = _config()
    if not cfg or not is_team_phone(contact_address):
        return None
    url, key = cfg
    try:
        data = _call(f"{url}?a=mensaje", key, "POST",
                     {"telefono": contact_address, "texto": user_text}, AGENT_TIMEOUT_SECONDS)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        print(f"[CAJA_INTERNO] agent error: {exc}", flush=True)
        return UNAVAILABLE_REPLY
    if not data.get("manejado"):
        return None  # removed from the team since the list was cached: treat as a client
    return str(data.get("respuesta") or "").strip() or UNAVAILABLE_REPLY
