"""Acomara's own sales rules, plugged into the engine (see nico_core.hooks).

The rules themselves stay in orchestrator/sales_rules.py and
orchestrator/departures.py for now: other work edits them, and this file only
wires them in, in the same order as before.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from nico_core.hooks import CloseContext, TenantHooks
from orchestrator.departures import (
    clarify_season_years,
    ensure_departure_hit,
    filter_past_departures,
    season_departures,
)
from tenants.acomara.formatting import format_whatsapp_departure_dates
from orchestrator.sales_rules import apply_video_call_close, extended_alternative_note, short_program_reply


def rewrite_departures(answer: str, today: date) -> str:
    # Past departures are removed here: the small model dropped future ones when asked to.
    return clarify_season_years(filter_past_departures(answer, today))


def video_call_close(reply: str, ctx: CloseContext) -> str:
    departures = season_departures(ctx.index_rows)
    return apply_video_call_close(
        reply,
        ctx.user_text,
        ctx.session_vars,
        ctx.lang,
        has_email=ctx.has_email,
        extra_note=extended_alternative_note(ctx.user_text, departures, ctx.today, ctx.lang),
        departures=departures,
    )


def select_departure_evidence(
    hits: list[dict[str, Any]], rows: list[dict[str, Any]], user_text: str, lang: str, top_k: int
) -> list[dict[str, Any]]:
    return ensure_departure_hit(hits, rows, user_text, lang, top_k)


HOOKS = TenantHooks(
    # Fernando's 6,000 m rule; the model got it backwards for Kilimanjaro.
    fixed_replies=(short_program_reply,),
    select_evidence=select_departure_evidence,
    rewrite_evidence=rewrite_departures,
    close_reply=video_call_close,
    format_reply=format_whatsapp_departure_dates,
)
