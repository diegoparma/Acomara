"""Seasonal businesses: notice when a client asks for a date with no service.

Moved from orchestrator/server.py (Acomara: expeditions run November-March).
The month list is derived from the tenant's season months, so a tenant only
declares which months it operates and which words show trip intent.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Month names (normalized: lowercase, no accents) in the languages Nico speaks.
# English "may" is left out: it is also a modal verb (see _MAY_MONTH_RE).
MONTH_NAMES: dict[int, tuple[str, ...]] = {
    1: ("january", "enero", "janeiro"),
    2: ("february", "febrero", "fevereiro"),
    3: ("march", "marzo", "marco"),
    4: ("april", "abril"),
    5: ("mayo", "maio"),
    6: ("june", "junio", "junho"),
    7: ("july", "julio", "julho"),
    8: ("august", "agosto"),
    9: ("september", "septiembre", "setiembre", "setembro"),
    10: ("october", "octubre", "outubro"),
    11: ("november", "noviembre", "novembro"),
    12: ("december", "diciembre", "dezembro"),
}

# English "may" only counts as the month next to a date-like context
# ("in May", "May 12", "12th of May"), never as the modal verb ("May I...").
MAY_MONTH_RE = re.compile(
    r"\b(?:in|on|of|during|early|late|mid|next|this|by|until)\s+may\b"
    r"|\bmay\s+\d"
    r"|\d(?:st|nd|rd|th)?\s+(?:of\s+)?may\b"
)
# Numeric day/month pairs (27/05, 05-27, 15/05/2027). Ranges followed by a
# unit ("4-6 personas", "5-7 dias") are quantities, not dates.
NUMERIC_DATE_RE = re.compile(
    r"\b(\d{1,2})[/-](\d{1,2})\b(?!\s*(?:personas?|pessoas?|people|persons?|pax|dias?|days?"
    r"|noches?|noites?|nights?|semanas?|weeks?|horas?|hours?|km|kg|anos?|years?))"
)


@dataclass(frozen=True)
class SeasonConfig:
    """Months the business operates and the words that show a trip/booking intent."""

    months: frozenset[int]
    # A month alone is not enough ("I was in July at a wedding"): the message
    # also needs one of these. Matched as substrings of the normalized text.
    trip_intent_tokens: tuple[str, ...]

    @property
    def off_months(self) -> frozenset[int]:
        return frozenset(range(1, 13)) - self.months

    @property
    def off_month_tokens(self) -> tuple[str, ...]:
        return tuple(name for month in sorted(self.off_months) for name in MONTH_NAMES[month])


def numeric_date_is_off_season(first: int, second: int, off_months: frozenset[int] | range) -> bool:
    """True only when every valid reading (DD/MM and MM/DD) lands off season.

    "5/12" is 5 December for a Spanish/Portuguese speaker, a real departure,
    so an ambiguous pair must not trigger the out-of-season warning.
    """
    months = []
    if 1 <= second <= 12 and 1 <= first <= 31:
        months.append(second)  # DD/MM
    if 1 <= first <= 12 and 1 <= second <= 31:
        months.append(first)  # MM/DD
    return bool(months) and all(m in off_months for m in months)


def mentions_off_season(text: str, season: SeasonConfig | None) -> bool:
    """True if the message names an off-season month together with a trip intent.

    Conservative on purpose. A tenant without a season never triggers it.
    """
    if not text or season is None:
        return False
    lowered = text.lower()
    normalized = unicodedata.normalize("NFKD", lowered).encode("ascii", "ignore").decode("ascii")

    if not any(tok in normalized for tok in season.trip_intent_tokens):
        return False

    off_months = season.off_months
    for tok in season.off_month_tokens:
        if re.search(r"\b" + re.escape(tok) + r"\b", normalized):
            return True
    if 5 in off_months and MAY_MONTH_RE.search(normalized):
        return True
    for match in NUMERIC_DATE_RE.finditer(normalized):
        if numeric_date_is_off_season(int(match.group(1)), int(match.group(2)), off_months):
            return True
    return False
