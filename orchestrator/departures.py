"""Departure dates: drop the ones already gone and make sure they are found.

With gpt-4.1-mini, asking the model to "leave out past departures" made it
drop November and December while they were still ahead (simulation
2026-10-08). The filter now runs in code on the FAQ text before the model
sees it. Asking for dates also forces the dates FAQ into the evidence:
"¿Qué fechas tienen?" alone did not always retrieve it.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

_MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6, "julio": 7,
    "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "maio": 5, "junho": 6, "julho": 7,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}
_MONTH_NAMES = "|".join(sorted(_MONTHS, key=len, reverse=True))
# "Noviembre: 14 | 22" → month and its day list.
_MONTH_DAYS_RE = re.compile(
    rf"\b(?P<month>{_MONTH_NAMES})\s*:\s*(?P<days>\d{{1,2}}(?:\s*\|\s*\d{{1,2}})*)",
    re.IGNORECASE,
)
# "temporada 2026/27", "2026/27 season"
_SEASON_RE = re.compile(r"\b(20\d{2})\s*/\s*(\d{2})\b")
_DATES_QUESTION_RE = re.compile(
    r"\b(?:fechas?|salidas?|cuando salen|cuando sale|proximas? salidas?"
    r"|departures?|dates?|when do you (?:go|leave|start)"
    r"|datas?|saidas?|quando (?:saem|sai))\b"
    r"|\b\d{1,2}/\d{1,2}\b"  # "la del 5/12"
    # A season month ("queremos ir en enero") is a dates question too.
    r"|\b(?:noviembre|diciembre|enero|febrero|marzo|november|december|january|february|march"
    r"|novembro|dezembro|janeiro|fevereiro|marco)\b"
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    return text.encode("ascii", "ignore").decode("ascii")


def is_departure_dates_question(text: str) -> bool:
    return bool(_DATES_QUESTION_RE.search(_normalize(text)))


def is_departure_dates_entry(row: dict[str, Any]) -> bool:
    """The FAQ answer that lists the season's departures (several months with days)."""
    answer = str(row.get("answer") or "")
    return bool(_SEASON_RE.search(answer)) and len(_MONTH_DAYS_RE.findall(answer)) >= 4


def filter_past_departures(text: str, today: date) -> str:
    """Remove departure days before `today` from a season listing.

    A season "2026/27" runs July-December 2026 and January-June 2027. A month
    with no days left is removed. Text without a season label is untouched.
    """
    season = _SEASON_RE.search(text or "")
    if not season:
        return text
    start_year = int(season.group(1))

    def keep_future(match: re.Match[str]) -> str:
        month = _MONTHS[match.group("month").lower()]
        year = start_year if month >= 7 else start_year + 1
        days = [d for d in re.findall(r"\d{1,2}", match.group("days")) if _is_on_or_after(year, month, int(d), today)]
        if not days:
            return ""
        return f"{match.group('month')}: {' | '.join(days)}"

    filtered = _MONTH_DAYS_RE.sub(keep_future, text)
    return re.sub(r"[ \t]{2,}", " ", filtered)


_SEASON_LABEL_RE = re.compile(r"(temporada|season)\s+(20\d{2})\s*/\s*(\d{2})|(20\d{2})\s*/\s*(\d{2})\s+(season)", re.IGNORECASE)


def clarify_season_years(text: str) -> str:
    """Spell out which year each month belongs to.

    Given "temporada 2026/27" the model wrote "para enero 2026/27"
    (simulation 2026-10-09). With the years spelled out it writes "enero 2027".
    """

    def explain(match: re.Match[str]) -> str:
        start = int(match.group(2) or match.group(4))
        if (match.group(1) or "").lower() == "temporada":
            return f"{match.group(0)} (noviembre y diciembre de {start}; enero y febrero de {start + 1})"
        return f"{match.group(0)} (November and December {start}; January and February {start + 1})"

    return _SEASON_LABEL_RE.sub(explain, text or "", count=1)


def _is_on_or_after(year: int, month: int, day: int, today: date) -> bool:
    try:
        return date(year, month, day) >= today
    except ValueError:
        return True


def ensure_departure_hit(
    hits: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    user_text: str,
    lang: str,
    top_k: int,
) -> list[dict[str, Any]]:
    """When the client asks for dates, put the dates FAQ first in the evidence."""
    if not is_departure_dates_question(user_text):
        return hits
    if any(is_departure_dates_entry(h) for h in hits):
        return hits
    candidates = [r for r in rows if is_departure_dates_entry(r)]
    if not candidates:
        return hits
    english = lang == "en"
    candidates.sort(key=lambda r: ("departure" in str(r.get("question", "")).lower()) != english)
    best = {"score": 1.0, **{k: v for k, v in candidates[0].items() if k != "embedding"}}
    return [best, *hits][: max(top_k, 1)]


_PROGRAM_HEADER_RE = re.compile(r"\b(1[2478])\s*\+\s*2\s+(?:d[ií]as|days)\b", re.IGNORECASE)


def departures_by_program(text: str) -> dict[str, list[date]]:
    """Departure dates per program ("18+2" → [date, ...]) from the season listing."""
    season = _SEASON_RE.search(text or "")
    if not season:
        return {}
    start_year = int(season.group(1))
    headers = list(_PROGRAM_HEADER_RE.finditer(text))
    programs: dict[str, list[date]] = {}
    for i, header in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        dates: list[date] = []
        for match in _MONTH_DAYS_RE.finditer(text[header.end() : end]):
            month = _MONTHS[match.group("month").lower()]
            year = start_year if month >= 7 else start_year + 1
            for day in re.findall(r"\d{1,2}", match.group("days")):
                try:
                    dates.append(date(year, month, int(day)))
                except ValueError:
                    continue
        programs[f"{header.group(1)}+2"] = dates
    return programs


def season_departures(rows: list[dict[str, Any]]) -> dict[str, list[date]]:
    """Departures per program from the dates FAQ entry in the index."""
    for row in rows:
        if is_departure_dates_entry(row):
            parsed = departures_by_program(str(row.get("answer") or ""))
            if parsed:
                return parsed
    return {}

