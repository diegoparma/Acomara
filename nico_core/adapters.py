"""Contracts for the systems around the engine (phase 3 of 17-nico-producto.md).

Today the server talks to session-agent and OpenBSP directly. These
protocols name what it needs from each, so a business can plug in another
store or channel, and evals can run the engine without any network. Nothing
in the server uses them yet; `SessionAgentStore` wraps the current client
with the same behavior (it never raises: failures read as "no session").

session-agent is shared with other projects: these adapters only call its
existing API, they never ask it to change.
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Protocol, runtime_checkable


@runtime_checkable
class SessionStore(Protocol):
    """Per-conversation memory. get() returns {"variables": {...}, ...} or None."""

    def get(self, conversation_id: str) -> dict[str, Any] | None: ...

    def upsert(self, msg: dict[str, str], agent_id: str, variables: dict[str, Any]) -> None: ...

    def append_event(self, conversation_id: str, event_type: str, event_data: dict[str, Any]) -> None: ...

    def delete(self, conversation_id: str) -> None: ...


@runtime_checkable
class Channel(Protocol):
    """Where messages come from and go to (OpenBSP WhatsApp today; email or web chat later)."""

    name: str

    def max_bubbles(self) -> int: ...

    def send(self, msg: dict[str, str], bubbles: list[str]) -> None: ...


class InMemorySessionStore:
    """Session memory in a dict: for tests, evals and local runs."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[tuple[str, dict[str, Any]]]] = {}

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        session = self.sessions.get(conversation_id)
        return copy.deepcopy(session) if session is not None else None

    def upsert(self, msg: dict[str, str], agent_id: str, variables: dict[str, Any]) -> None:
        self.sessions[msg["conversation_id"]] = {
            "conversation_id": msg["conversation_id"],
            "organization_id": msg.get("organization_id"),
            "agent_id": agent_id,
            "contact_id": msg.get("contact_id"),
            "variables": copy.deepcopy(variables),
        }

    def append_event(self, conversation_id: str, event_type: str, event_data: dict[str, Any]) -> None:
        self.events.setdefault(conversation_id, []).append((event_type, copy.deepcopy(event_data)))

    def delete(self, conversation_id: str) -> None:
        self.sessions.pop(conversation_id, None)
        self.events.pop(conversation_id, None)


class SessionAgentStore:
    """The shared session-agent service (orchestrator/session_client.py), as a SessionStore."""

    def __init__(self, base_url: str | None, http_json: Callable[..., tuple[int, Any]], logger: Any) -> None:
        self.base_url = base_url
        self._kw = {"http_json": http_json, "logger": logger}

    def get(self, conversation_id: str) -> dict[str, Any] | None:
        from orchestrator.session_client import try_session_get

        return try_session_get(self.base_url, conversation_id, **self._kw)

    def upsert(self, msg: dict[str, str], agent_id: str, variables: dict[str, Any]) -> None:
        from orchestrator.session_client import try_session_upsert

        try_session_upsert(self.base_url, msg, agent_id, variables, **self._kw)

    def append_event(self, conversation_id: str, event_type: str, event_data: dict[str, Any]) -> None:
        from orchestrator.session_client import try_session_append_event

        try_session_append_event(self.base_url, conversation_id, event_type, event_data, **self._kw)

    def delete(self, conversation_id: str) -> None:
        from orchestrator.session_client import try_session_delete

        try_session_delete(self.base_url, conversation_id, **self._kw)
