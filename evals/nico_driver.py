"""Drive the real Nico (orchestrator/server.py) in-process, like a WhatsApp client would.

Same isolation as scripts/simulate_conversations.py: the session lives in
memory, CRM / Supabase / emails / the caja agent are off, email verification
is off. Requests go through the Flask app (`/v1/chat/completions`) so every
deterministic rule in server.py runs exactly as in production.

Two model backends for Nico itself:
- real: OpenAI, with every call's tokens recorded per conversation.
- stub (offline, no key): embeddings pick FAQ rows by word overlap and the
  "reply" is the start of the best FAQ answer. It exercises the whole pipeline
  and the deterministic rules, but says nothing about the prompt's quality.
"""
from __future__ import annotations

import contextlib
import io
import json
import math
import os
import re
import threading
import unicodedata
from types import SimpleNamespace
from typing import Any, Iterator
from unittest import mock

from evals.llm import UsageTracker

_thread = threading.local()


def _current_bucket() -> dict[str, int] | None:
    return getattr(_thread, "bucket", None)


def _add_to_bucket(usage: Any) -> None:
    bucket = _current_bucket()
    if bucket is None or usage is None:
        return
    details = getattr(usage, "input_tokens_details", None)
    bucket["calls"] += 1
    bucket["input_tokens"] += int(getattr(usage, "input_tokens", 0) or 0)
    bucket["cached_input_tokens"] += int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
    bucket["output_tokens"] += int(getattr(usage, "output_tokens", 0) or 0)


# ---------------------------------------------------------------------------
# Offline stub for Nico's model.
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9+]{3,}")


def _words(text: str) -> set[str]:
    text = "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))
    return set(_WORD.findall(text))


class StubNicoClient:
    """Deterministic stand-in for OpenAI used by server.py when there is no key."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self._row_words = [_words(f"{r.get('question', '')} {r.get('answer', '')[:600]}") for r in rows]
        self.embeddings = SimpleNamespace(create=self._embed)
        self.responses = SimpleNamespace(create=self._respond)

    def _vector_for(self, text: str) -> list[float]:
        query = _words(text)
        if not self._rows:
            return [1.0]
        scores = [len(query & words) / (1 + math.log(1 + len(words))) for words in self._row_words]
        best = max(range(len(scores)), key=lambda i: (scores[i], -i))
        return list(self._rows[best]["embedding"])

    def _embed(self, model: str, input: Any) -> Any:  # noqa: A002 - OpenAI's name
        texts = input if isinstance(input, list) else [input]
        return SimpleNamespace(data=[SimpleNamespace(embedding=self._vector_for(str(t))) for t in texts])

    def _respond(self, **kwargs: Any) -> Any:
        prompt = str(kwargs["input"][-1]["content"])
        answers = re.findall(r"^ANSWER: (.*)$", prompt, flags=re.MULTILINE)
        text = answers[0] if answers else "Eso lo tiene que confirmar un asesor del equipo."
        sentences = re.split(r"(?<=[.!?])\s+", text.replace("\xa0", " "))
        reply = ""
        for sentence in sentences:
            if len(reply) + len(sentence) > 260:
                break
            reply = f"{reply} {sentence}".strip()
        reply = reply or text[:260]
        # No usage: offline runs must report zero cost.
        return SimpleNamespace(output_text=reply, status="completed", usage=None)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


class _MemorySession:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, base_url: Any, conversation_id: str) -> dict | None:
        with self._lock:
            stored = self.store.get(conversation_id)
            return {"variables": json.loads(json.dumps(stored))} if stored is not None else None

    def upsert(self, base_url: Any, msg: dict, agent_id: Any, variables: dict) -> None:
        with self._lock:
            self.store[msg["conversation_id"]] = json.loads(json.dumps(variables, default=str))


def reply_bubbles(completion: dict) -> list[str]:
    """The WhatsApp bubbles Nico would send for one completion."""
    message = completion["choices"][0]["message"]
    if message.get("tool_calls"):
        parts: list[str] = []
        for call in message["tool_calls"]:
            args = json.loads(call["function"]["arguments"])
            parts.extend(str(m.get("text", "")) for m in args.get("messages", []))
        return [p for p in parts if p.strip()]
    content = message.get("content") or ""
    return [content] if content.strip() else []


class NicoHarness:
    """Context manager: patches server.py once, then `send()` from any thread."""

    def __init__(
        self,
        tracker: UsageTracker,
        *,
        offline: bool,
        nico_model: str = "gpt-4.1-mini",
        embed_model: str | None = None,
        api_key: str | None = None,
        server_log: io.TextIOBase | None = None,
    ) -> None:
        self.tracker = tracker
        self.offline = offline
        self.nico_model = nico_model
        self.embed_model = embed_model or os.environ.get("OPENAI_EMBED_MODEL") or "text-embedding-3-small"
        self.api_key = api_key
        self.session = _MemorySession()
        self._patches: list[Any] = []
        self._server_log = server_log
        self._redirect: Any = None

    def __enter__(self) -> NicoHarness:
        from orchestrator import server

        self.server = server
        tracker = self.tracker
        embed_model = self.embed_model
        nico_model = self.nico_model
        if self.offline:
            rows = server.load_index(server.INDEX_PATH)
            stub = StubNicoClient(rows)

            def factory(api_key: str) -> Any:
                return _Recording(stub, tracker, nico_model, embed_model)

        else:
            real = server.OpenAI(api_key=self.api_key, max_retries=6, timeout=90)

            def factory(api_key: str) -> Any:
                return _Recording(real, tracker, nico_model, embed_model)

        env = {
            "OPENAI_API_KEY": self.api_key or "offline-stub",
            "OPENAI_CHAT_MODEL": nico_model,
            "OPENAI_EMBED_MODEL": embed_model,
            "ORCHESTRATOR_API_KEY": "evals",
            "SESSION_AGENT_BASE_URL": "http://evals.local",
            "HUMAN_SILENCE_HOURS": "0",
            # Verification runs like in production, with the HIBP lookup faked as
            # "found in breaches" (a normal, real-looking lead).
            "EMAIL_VERIFICATION_ENABLED": "true",
            "HANDOFF_EMAIL_TO": "",
            "OPENBSP_MULTI_MESSAGE_ENABLED": "true",
            "CAJA_AGENT_URL": "",
        }
        not_sent = lambda *a, **k: (False, 0, {"info": "evals"})  # noqa: E731
        self._patches = [
            mock.patch.dict(os.environ, env),
            mock.patch.object(server, "load_local_env", lambda: None),
            mock.patch.object(server, "OpenAI", factory),
            mock.patch.object(server, "try_session_get", self.session.get),
            mock.patch.object(server, "try_session_upsert", self.session.upsert),
            mock.patch.object(server, "try_session_append_event", lambda *a, **k: None),
            mock.patch.object(server, "try_session_delete", lambda *a, **k: None),
            mock.patch.object(server, "check_client_status", lambda **k: {}),
            mock.patch.object(server, "human_replied_recently", lambda **k: (False, {})),
            mock.patch.object(server, "internal_reply", lambda *a, **k: None),
            mock.patch.object(server, "check_email_reputation", lambda *a, **k: (False, True)),
            mock.patch.object(server, "try_send_handoff_email", not_sent),
            mock.patch.object(server, "try_send_new_lead_email", not_sent),
            mock.patch.object(server, "try_send_suspicious_admin_alert", lambda *a, **k: (False, 0, {}, False, "evals")),
        ]
        for patch in self._patches:
            patch.start()
        if self._server_log is not None:
            self._redirect = contextlib.redirect_stdout(self._server_log)
            self._redirect.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        if self._redirect is not None:
            self._redirect.__exit__(*exc)
        for patch in reversed(self._patches):
            patch.stop()

    @contextlib.contextmanager
    def conversation_usage(self) -> Iterator[dict[str, int]]:
        bucket = {"calls": 0, "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
        _thread.bucket = bucket
        try:
            yield bucket
        finally:
            _thread.bucket = None

    def send(self, conversation_id: str, text: str, channel: str = "whatsapp") -> dict[str, Any]:
        client = getattr(_thread, "flask_client", None)
        if client is None:
            client = self.server.app.test_client()
            _thread.flask_client = client
        body = {
            "model": "nico",
            "messages": [{"role": "user", "content": text}],
            "tools": [{"type": "function", "function": {"name": "respond"}}],
        }
        headers = {
            "Authorization": "Bearer evals",
            "conversation-id": conversation_id,
            "contact-id": conversation_id,
            "contact-address": "+540000000000",
            "organization-id": "evals",
            "x-channel": channel,
        }
        resp = client.post("/v1/chat/completions", json=body, headers=headers)
        if resp.status_code != 200:
            return {"bubbles": [], "error": f"HTTP {resp.status_code}: {resp.get_data(as_text=True)[:300]}"}
        return {"bubbles": reply_bubbles(resp.get_json()), "error": None}

    def session_vars(self, conversation_id: str) -> dict[str, Any]:
        snap = self.session.get(None, conversation_id)
        return snap["variables"] if snap else {}


class _Recording:
    """OpenAI-shaped wrapper that records Nico's token usage."""

    def __init__(self, inner: Any, tracker: UsageTracker, chat_model: str, embed_model: str) -> None:
        self._inner = inner
        self._tracker = tracker
        self._chat_model = chat_model
        self._embed_model = embed_model
        self.responses = self
        self.embeddings = SimpleNamespace(create=self._embed)

    def create(self, **kwargs: Any) -> Any:
        resp = self._inner.responses.create(**kwargs)
        usage = getattr(resp, "usage", None)
        self._tracker.record_openai_usage("nico", kwargs.get("model", self._chat_model), usage)
        _add_to_bucket(usage)
        return resp

    def _embed(self, **kwargs: Any) -> Any:
        resp = self._inner.embeddings.create(**kwargs)
        usage = getattr(resp, "usage", None)
        tokens = int(getattr(usage, "prompt_tokens", 0) or 0) if usage is not None else 0
        self._tracker.record("nico_embeddings", kwargs.get("model", self._embed_model), tokens, 0, 0)
        return resp
