"""WhatsApp layout for Acomara's departure-date listings.

Moved verbatim from orchestrator/server.py: it knows Acomara's program titles
("18+2 DÍAS | RUTA NORMAL") and the season listing, so it is a tenant hook
(`format_reply`), not engine code.
"""
from __future__ import annotations

import re

_MONTH_ABBR: dict[str, str] = {
    "enero": "Ene", "febrero": "Feb", "marzo": "Mar", "abril": "Abr",
    "mayo": "May", "junio": "Jun", "julio": "Jul", "agosto": "Ago",
    "septiembre": "Sep", "setiembre": "Sep", "octubre": "Oct",
    "noviembre": "Nov", "diciembre": "Dic",
    "january": "Jan", "february": "Feb", "march": "Mar", "april": "Apr",
    "may": "May", "june": "Jun", "july": "Jul", "august": "Aug",
    "september": "Sep", "october": "Oct", "november": "Nov", "december": "Dec",
}

_TITLE_PATTERN = re.compile(
    r"^([ \t]*)(\d+\s*\+\s*\d+)\s+(?:D[ÍI]AS|d[íi]as)\s*\|\s*(.+?)\s*$",
    flags=re.MULTILINE,
)


def _format_program_title(match: "re.Match[str]") -> str:
    indent = match.group(1)
    days = re.sub(r"\s+", "", match.group(2))
    rest = match.group(3).strip()
    paren = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", rest)
    if paren:
        name = paren.group(1).strip().title()
        note = paren.group(2).strip().lower()
        return f"{indent}*{days} días - {name}* _({note})_"
    return f"{indent}*{days} días - {rest.title()}*"


def _format_inline_program_list(text: str) -> str:
    """Convert semicolon-separated inline program dates into a numbered list."""
    if ";" not in text or not re.search(r"\(\s*\d+\s*\+\s*\d+\s*d[íi]as\s*\)", text, re.IGNORECASE):
        return text

    prefix = ""
    body = text
    if ":" in text:
        maybe_prefix, maybe_body = text.split(":", 1)
        if re.search(r"\(\s*\d+\s*\+\s*\d+\s*d[íi]as\s*\)", maybe_body, re.IGNORECASE):
            prefix = maybe_prefix.strip()
            body = maybe_body.strip()

    entry_re = re.compile(
        r"^\s*(?P<name>[^()]+?)\s*\(\s*(?P<days>\d+\s*\+\s*\d+)\s*d[íi]as\s*\)\s*(?P<schedule>.+?)\s*$",
        re.IGNORECASE,
    )
    month_keys = "|".join(sorted(_MONTH_ABBR.keys(), key=len, reverse=True))
    abbr_keys = "|".join(sorted(set(_MONTH_ABBR.values()), key=len, reverse=True))
    month_day_re = re.compile(
        rf"\b(?P<month>{month_keys}|{abbr_keys})\.?\s*(?P<days>\d{{1,2}}(?:\s*,\s*\d{{1,2}})*)",
        re.IGNORECASE,
    )

    lines: list[str] = []
    for raw_entry in [p.strip() for p in body.split(";") if p.strip()]:
        entry = raw_entry.rstrip(".")
        m = entry_re.match(entry)
        if not m:
            return text

        name = m.group("name").strip().title()
        days = re.sub(r"\s+", "", m.group("days"))
        schedule = m.group("schedule").strip()
        month_chunks: list[str] = []
        for mm in month_day_re.finditer(schedule):
            month_raw = mm.group("month").lower()
            abbr = _MONTH_ABBR.get(month_raw, mm.group("month").title())
            day_list = [d.strip() for d in mm.group("days").split(",") if d.strip()]
            month_chunks.append(f"{abbr} {', '.join(day_list)}")
        schedule_fmt = " · ".join(month_chunks) if month_chunks else schedule
        lines.append(f"{len(lines) + 1}. *{name}* ({days} días): {schedule_fmt}")

    if not lines:
        return text
    return f"{prefix}:\n" + "\n".join(lines) if prefix else "\n".join(lines)


def format_whatsapp_departure_dates(reply_text: str, channel: str) -> str:
    """Render departure-date blocks compactly for WhatsApp readability."""
    if not reply_text or channel.strip().lower() != "whatsapp":
        return reply_text

    text = reply_text
    lower_text = text.lower()
    has_dates_marker = any(
        token in lower_text
        for token in (
            "fechas",
            "salidas",
            "departure",
            "departures",
        )
    )
    has_structured_dates = "|" in text or re.search(
        r"\(\s*\d+\s*\+\s*\d+\s*d[íi]as\s*\).+;",
        text,
        re.IGNORECASE,
    )
    looks_like_dates_response = bool(has_dates_marker and has_structured_dates)
    if not looks_like_dates_response:
        return reply_text

    month_pattern = re.compile(
        r"\b("
        r"enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre|"
        r"january|february|march|april|may|june|july|august|september|october|november|december"
        r")\s*:\s*([0-9]{1,2}(?:\s*(?:\||,)\s*[0-9]{1,2})+)",
        flags=re.IGNORECASE,
    )

    def _compact_month(match: "re.Match[str]") -> str:
        month_label = match.group(1)
        days = [d.strip() for d in re.split(r"\||,", match.group(2)) if d.strip()]
        if len(days) < 2:
            return match.group(0)
        abbr = _MONTH_ABBR.get(month_label.lower(), month_label)
        return f"{abbr} {', '.join(days)}"

    formatted = month_pattern.sub(_compact_month, text)

    # Collapse consecutive month lines into one compact line per program.
    abbr_set = set(_MONTH_ABBR.values())
    month_keys = "|".join(sorted(_MONTH_ABBR.keys(), key=len, reverse=True))
    abbr_keys = "|".join(sorted(abbr_set, key=len, reverse=True))
    month_line_re = re.compile(
        rf"^[ \t]*[-*]?[ \t]*(?P<month>{month_keys}|{abbr_keys})[ \t]*:?[ \t]+"
        rf"(?P<days>\d{{1,2}}(?:[ \t]*[,|][ \t]*\d{{1,2}})*)\s*$",
        re.IGNORECASE,
    )

    out_lines: list[str] = []
    buffer: list[str] = []
    for line in formatted.split("\n"):
        if re.fullmatch(r"[ \t]*[-*][ \t]*", line):
            continue
        m = month_line_re.match(line)
        if m:
            month_raw = m.group("month").lower()
            abbr = _MONTH_ABBR.get(month_raw, m.group("month").capitalize())
            days = [d.strip() for d in re.split(r"[,|]", m.group("days")) if d.strip()]
            buffer.append(f"{abbr} {', '.join(days)}")
            continue
        if buffer:
            out_lines.append(" · ".join(buffer))
            buffer = []
        out_lines.append(line)
    if buffer:
        out_lines.append(" · ".join(buffer))

    formatted = "\n".join(out_lines)
    formatted = _TITLE_PATTERN.sub(_format_program_title, formatted)
    formatted = _format_inline_program_list(formatted)
    formatted = re.sub(r"[ \t]+\n", "\n", formatted)
    formatted = re.sub(r"\n{3,}", "\n\n", formatted)
    return formatted.strip()
