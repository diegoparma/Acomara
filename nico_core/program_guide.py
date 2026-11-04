"""Two-step answer to "what options do you have?" without calling the model.

Moved from orchestrator/server.py. The first time a client asks for options
without naming one, Nico recommends a short list; if they ask for the rest,
it lists the others. What the lists say is per tenant.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ProgramGuideConfig:
    # A message that already names a product ("el 18+2") is not a generic question.
    known_product_re: str
    first_intent_keywords: tuple[str, ...]
    followup_keywords: tuple[str, ...]
    # Per language; a language without its own text gets `fallback_language`'s.
    first_reply: Mapping[str, str]
    followup_reply: Mapping[str, str]
    fallback_language: str = "es"

    def reply(self, replies: Mapping[str, str], lang: str) -> str:
        return replies.get(lang) or replies[self.fallback_language]


def names_known_product(guide: ProgramGuideConfig, normalized_text: str) -> bool:
    return bool(re.search(guide.known_product_re, normalized_text))


def is_first_intent(guide: ProgramGuideConfig, normalized_text: str) -> bool:
    has_generic_keyword = any(k in normalized_text for k in guide.first_intent_keywords)
    return has_generic_keyword and not names_known_product(guide, normalized_text)


def is_followup_intent(guide: ProgramGuideConfig, normalized_text: str) -> bool:
    return any(k in normalized_text for k in guide.followup_keywords)


def program_options_reply(
    guide: ProgramGuideConfig | None,
    normalized_text: str,
    session_vars: dict[str, Any],
    lang: str,
) -> str | None:
    """Fixed reply for an options question, advancing `program_options_stage`; None otherwise."""
    if guide is None:
        return None
    options_stage = int(session_vars.get("program_options_stage") or 0)

    if options_stage <= 0 and is_first_intent(guide, normalized_text):
        session_vars["program_options_stage"] = 1
        return guide.reply(guide.first_reply, lang)

    if options_stage >= 1 and is_followup_intent(guide, normalized_text):
        session_vars["program_options_stage"] = 2
        return guide.reply(guide.followup_reply, lang)

    return None
