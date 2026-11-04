"""Per-business configuration for the Nico engine.

Phase 1 keeps the config as plain Python (a `TENANT` object in
`tenants/<slug>/__init__.py`): it holds regexes and callables, needs no new
dependency and is checked by the test suite. Text a non-developer edits
(phrases, key facts, prompt) can move to data files later without changing
this interface.
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from typing import Mapping

DEFAULT_TENANT = "acomara"
TENANT_ENV = "NICO_TENANT"

# Keys every tenant must translate: the engine sends them without the model.
REQUIRED_PHRASES = (
    "reset_acknowledge",
    "handoff_ask_email",
    "handoff_executed",
    "handoff_pending",
    "proactive_email_request",
    "proactive_email_saved",
    "proactive_email_check_failed",
    "paused_handoff",
    "paused_suspicious",
    "paused_proactive_email",
    "paused_loop_final",
    "repeat_prefix",
    "thanks_reply_1",
    "thanks_reply_2",
    "bot_question",
    "email_received_short",
    "email_received_ack",
    "opening_welcome",
)


@dataclass(frozen=True)
class TenantConfig:
    """Everything that makes Nico sell for one business and not another."""

    slug: str
    brand_name: str
    # Fixed replies per language: {"es": {"key": "text"}, ...}. The first
    # language in `languages` is the fallback for missing keys.
    phrases: Mapping[str, Mapping[str, str]]
    languages: tuple[str, ...] = ("es", "en", "pt")
    placeholder: bool = False
    notes: str = ""
    extra: Mapping[str, object] = field(default_factory=dict)

    @property
    def default_language(self) -> str:
        return self.languages[0]

    def validate(self) -> list[str]:
        """Problems that would make the engine send a broken reply; empty when fine."""
        problems = []
        for lang in self.languages:
            if lang not in self.phrases:
                problems.append(f"{self.slug}: no phrases for language {lang!r}")
                continue
            for key in REQUIRED_PHRASES:
                if not self.phrases[lang].get(key):
                    problems.append(f"{self.slug}: phrase {key!r} missing in {lang!r}")
        return problems


def load_tenant(slug: str | None = None) -> TenantConfig:
    """Import `tenants.<slug>` and return its TENANT; slug defaults to $NICO_TENANT or acomara."""
    slug = (slug or os.getenv(TENANT_ENV) or DEFAULT_TENANT).strip().lower().replace("-", "_")
    if not slug.isidentifier():
        raise ValueError(f"invalid tenant slug: {slug!r}")
    module = importlib.import_module(f"tenants.{slug}")
    tenant = getattr(module, "TENANT", None)
    if not isinstance(tenant, TenantConfig):
        raise TypeError(f"tenants.{slug} has no TENANT of type TenantConfig")
    return tenant


_ACTIVE: TenantConfig | None = None


def get_tenant() -> TenantConfig:
    """The tenant this deploy serves, loaded once per process."""
    global _ACTIVE
    if _ACTIVE is None:
        _ACTIVE = load_tenant()
    return _ACTIVE
