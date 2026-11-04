"""Business rules a tenant plugs into the engine.

Some sales rules are too specific to be config values (Acomara: the 6,000 m
rule for the short programs, the departure-date evidence, Fernando's video
call close). A tenant implements them as plain functions and lists them here;
the engine calls them at fixed points of the pipeline. Every hook is
optional: an empty `TenantHooks()` is a valid tenant.

Pipeline points, in order:
1. `fixed_replies`: before the model, after the generic fixed replies
   (greeting, thanks, "are you a bot?"). The first non-None reply wins and
   the model is not called.
2. `select_evidence`: after retrieval, may add or reorder FAQ hits.
3. `rewrite_evidence`: each hit's answer text before the model sees it.
4. `close_reply`: the model's reply, before the generic email and season
   policies.
5. `format_reply`: every reply (fixed or not), with the channel name, before
   the outbound safety filter.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

# (user_text, lang) -> fixed reply or None
FixedReply = Callable[[str, str], "str | None"]
# (hits, index_rows, user_text, lang, top_k) -> hits
SelectEvidence = Callable[[list[dict[str, Any]], list[dict[str, Any]], str, str, int], list[dict[str, Any]]]
# (answer_text, today) -> answer_text
RewriteEvidence = Callable[[str, date], str]


@dataclass(frozen=True)
class CloseContext:
    """What a close_reply hook may look at; it may mutate session_vars."""

    user_text: str
    session_vars: dict[str, Any]
    lang: str
    has_email: bool
    index_rows: list[dict[str, Any]]
    today: date


# (reply, ctx) -> reply
CloseReply = Callable[[str, CloseContext], str]
# (reply, channel) -> reply
FormatReply = Callable[[str, str], str]


@dataclass(frozen=True)
class TenantHooks:
    fixed_replies: tuple[FixedReply, ...] = ()
    select_evidence: SelectEvidence | None = None
    rewrite_evidence: RewriteEvidence | None = None
    close_reply: CloseReply | None = None
    format_reply: FormatReply | None = None


def first_fixed_reply(hooks: TenantHooks, user_text: str, lang: str) -> str | None:
    for rule in hooks.fixed_replies:
        reply = rule(user_text, lang)
        if reply is not None:
            return reply
    return None
