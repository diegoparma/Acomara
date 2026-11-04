#!/usr/bin/env python3
"""Generate Nico's knowledge files from the canonical source in docs/knowledge/fuente/.

    python3 scripts/build_knowledge.py           # write the generated files
    python3 scripts/build_knowledge.py --check   # exit 1 if they are out of date

Source (edit these):
    fuente/valores.yaml      every price, percentage, date or link, written once
    fuente/salidas.yaml      the season's scheduled departures
    fuente/datos-clave.yaml  key facts pinned in the system prompt
    fuente/faq.yaml          FAQ entries (question/answer per language)

Generated (never edit by hand):
    datos-clave.md           appended to the system prompt by orchestrator/server.py
    faq_rag_chunks.jsonl     one chunk per entry and language; input of build_cloud_index.py
    faq_structured.md        human-readable FAQ, values table and sources

The embeddings index (faq_cloud_index.jsonl) needs OPENAI_API_KEY and is built
afterwards by scripts/build_cloud_index.py.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "docs" / "knowledge"
SOURCE = KNOWLEDGE / "fuente"

LANGS = ("es", "en", "pt")
CONFIDENCE = ("confirmed", "web", "pending")
TOPICS = {
    "programas": "Programas e itinerarios",
    "precios": "Precios, reserva y pago",
    "fechas": "Fechas de salida",
    "temporada": "Temporada y clima",
    "incluye": "Qué incluye y qué no",
    "opcionales": "Servicios opcionales",
    "treks": "Treks",
    "logistica": "Logística (vuelos, hotel, equipaje, comunicación)",
    "permiso-y-seguro": "Permiso del Parque y seguro",
    "requisitos": "Requisitos (experiencia, edad, documentos)",
    "equipo": "Equipo",
    "comida": "Comida y menús",
    "guias-y-porteadores": "Guías, porteadores y grupo",
    "preparacion": "Preparación (entrenamiento, nutrición, salud)",
    "politicas": "Políticas (abandono, descenso, propinas)",
}
_PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*)\}")
_ID = re.compile(r"^faq-\d{3}$")

MONTHS = {
    "es": ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"],
    "pt": ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"],
}
DAYS_WORD = {"es": "DÍAS", "en": "DAYS", "pt": "DIAS"}


class KnowledgeError(ValueError):
    """The source files are inconsistent; the message says where."""


@dataclass
class Sources:
    values: dict[str, dict[str, Any]]
    departures: dict[str, Any]
    key_facts: dict[str, Any]
    faq: list[dict[str, Any]]


def _load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_sources(source_dir: Path = SOURCE) -> Sources:
    return Sources(
        values=_load_yaml(source_dir / "valores.yaml") or {},
        departures=_load_yaml(source_dir / "salidas.yaml") or {},
        key_facts=_load_yaml(source_dir / "datos-clave.yaml") or {},
        faq=_load_yaml(source_dir / "faq.yaml") or [],
    )


# --- values ------------------------------------------------------------------

def format_usd(amount: int | float, lang: str) -> str:
    """USD 7.250 in Spanish and Portuguese, USD 7,250 in English."""
    text = f"{int(amount):,}"
    if lang != "en":
        text = text.replace(",", ".")
    return f"USD {text}"


def format_percent(value: float, lang: str) -> str:
    text = f"{value:g}"
    if lang != "en":
        text = text.replace(".", ",")
    return f"{text}%"


def _text_for(value: Any, lang: str) -> str:
    if isinstance(value, dict):
        return str(value.get(lang) or value.get("es") or next(iter(value.values())))
    return str(value)


def render_departures(departures: dict[str, Any], lang: str) -> str:
    lines: list[str] = []
    for program in departures.get("programs") or []:
        lines.append(f"{program['program']} {DAYS_WORD[lang]} | {_text_for(program['label'], lang)}")
        by_month: dict[tuple[int, int], list[int]] = {}
        for d in program["dates"]:
            d = d if isinstance(d, date) else date.fromisoformat(str(d))
            by_month.setdefault((d.year, d.month), []).append(d.day)
        for (_, month), days in sorted(by_month.items()):
            lines.append(f"{MONTHS[lang][month - 1]}: {' | '.join(str(x) for x in sorted(days))}")
    return "\n".join(lines)


def render_value(sources: Sources, name: str, lang: str) -> str:
    if name == "departures_list":
        return render_departures(sources.departures, lang)
    spec = sources.values.get(name)
    if spec is None:
        raise KnowledgeError(f"{{{name}}} no está en valores.yaml")
    if "usd" in spec:
        return format_usd(spec["usd"], lang)
    if "percent" in spec:
        return format_percent(float(spec["percent"]), lang)
    if "text" in spec:
        return _text_for(spec["text"], lang)
    raise KnowledgeError(f"valores.yaml: {name} no tiene usd, percent ni text")


def render(sources: Sources, text: str, lang: str) -> str:
    return _PLACEHOLDER.sub(lambda m: render_value(sources, m.group(1), lang), text)


def placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text or ""))


# --- validation --------------------------------------------------------------

def _as_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def entry_ids(entry: dict[str, Any]) -> dict[str, str]:
    """Chunk id per answer language."""
    ids = entry.get("id")
    answers = entry.get("answer") or {}
    if isinstance(ids, dict):
        return {lang: ids[lang] for lang in answers if lang in ids}
    return {lang: ids for lang in answers}


def validate(sources: Sources, today: date | None = None) -> list[str]:
    """Problems that must be fixed before generating. Empty list = OK."""
    today = today or date.today()
    errors: list[str] = []

    def check_validity(where: str, spec: dict[str, Any]) -> None:
        until = _as_date(spec.get("valid_until"))
        if until and until < today:
            errors.append(f"{where}: vencido (valid_until {until}); actualizar o confirmar con Fernando")
        conf = spec.get("confidence")
        if conf is not None and conf not in CONFIDENCE:
            errors.append(f"{where}: confidence '{conf}' no es {CONFIDENCE}")

    for name, spec in sources.values.items():
        if not isinstance(spec, dict) or not ({"usd", "percent", "text"} & spec.keys()):
            errors.append(f"valores.yaml: {name} necesita usd, percent o text")
            continue
        check_validity(f"valores.yaml:{name}", spec)
    check_validity("salidas.yaml", sources.departures)
    for program in sources.departures.get("programs") or []:
        for d in program.get("dates") or []:
            try:
                _as_date(d)
            except ValueError:
                errors.append(f"salidas.yaml: {program.get('program')}: fecha inválida {d!r}")

    known = set(sources.values) | {"departures_list"}
    fact_ids: set[str] = set()
    for section in sources.key_facts.get("sections") or []:
        for name in placeholders(section.get("title", "")) - known:
            errors.append(f"datos-clave.yaml: sección '{section.get('title')}': {{{name}}} no existe")
        for fact in section.get("facts") or []:
            fid = fact.get("id")
            if not fid or fid in fact_ids:
                errors.append(f"datos-clave.yaml: id vacío o repetido: {fid!r}")
            fact_ids.add(fid)
            for name in placeholders(fact.get("text", "")) - known:
                errors.append(f"datos-clave.yaml:{fid}: {{{name}}} no está en valores.yaml")
            if not fact.get("rule") and not fact.get("source"):
                errors.append(f"datos-clave.yaml:{fid}: falta source")
            check_validity(f"datos-clave.yaml:{fid}", fact)

    keys: set[str] = set()
    chunk_ids: set[str] = set()
    for entry in sources.faq:
        key = entry.get("key")
        where = f"faq.yaml:{key}"
        if not key or key in keys:
            errors.append(f"faq.yaml: key vacía o repetida: {key!r}")
        keys.add(key)
        if entry.get("topic") not in TOPICS:
            errors.append(f"{where}: topic '{entry.get('topic')}' no es uno de {sorted(TOPICS)}")
        answers = entry.get("answer") or {}
        questions = entry.get("question") or {}
        if not answers:
            errors.append(f"{where}: sin respuesta")
        for lang in answers:
            if lang not in LANGS:
                errors.append(f"{where}: idioma '{lang}' no soportado")
            if lang not in questions:
                errors.append(f"{where}: falta la pregunta en '{lang}'")
            for name in placeholders(answers[lang]) - known:
                errors.append(f"{where}: {{{name}}} no está en valores.yaml")
        ids = entry_ids(entry)
        if set(ids) != set(answers):
            errors.append(f"{where}: falta id para algún idioma de la respuesta")
        for cid in ids.values():
            if not isinstance(cid, str) or not _ID.match(cid):
                errors.append(f"{where}: id inválido {cid!r} (formato faq-NNN)")
            elif cid in chunk_ids:
                errors.append(f"{where}: id repetido {cid}")
            chunk_ids.add(cid)
        if not entry.get("source"):
            errors.append(f"{where}: falta source")
        check_validity(where, entry)
    return errors


# --- generators --------------------------------------------------------------

def build_key_facts_md(sources: Sources) -> str:
    kf = sources.key_facts
    out = [f"# {kf['title']}", "", kf["intro"].strip(), ""]
    for section in kf.get("sections") or []:
        out.append(f"## {render(sources, section['title'], 'es')}")
        for fact in section.get("facts") or []:
            if fact.get("confidence") == "pending":
                continue
            text = " ".join(render(sources, fact["text"], "es").split())
            if not fact.get("rule"):
                text += f" [{', '.join(fact['source'])}]"
            out.append(f"- {text}")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def build_chunks(sources: Sources) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for entry in sources.faq:
        if entry.get("confidence") == "pending":
            continue
        ids = entry_ids(entry)
        for lang, answer in entry["answer"].items():
            # The question in the other languages helps a Spanish or Portuguese
            # message find an entry answered only in English.
            other_questions = [q.strip() for ql, q in entry["question"].items() if ql != lang]
            chunk = {
                "id": ids[lang],
                "key": entry["key"],
                "lang": lang,
                "topic": entry["topic"],
                "question": entry["question"][lang].strip(),
                "answer": render(sources, answer, lang).strip(),
                "also_asked": other_questions + [a.strip() for a in entry.get("also_asked") or []],
                "source": str(entry["source"]),
                "confidence": entry.get("confidence", "web"),
            }
            until = _as_date(entry.get("valid_until"))
            if until:
                chunk["valid_until"] = until.isoformat()
            chunks.append(chunk)
    return chunks


def build_chunks_jsonl(sources: Sources) -> str:
    return "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in build_chunks(sources))


def _md_cell(text: Any) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def build_faq_md(sources: Sources) -> str:
    out = [
        "# Preguntas frecuentes de Acomara",
        "",
        "> Generado por `scripts/build_knowledge.py` desde `docs/knowledge/fuente/`. No editar a mano:",
        "> los textos se cambian en `fuente/faq.yaml` y los precios y fechas en `fuente/valores.yaml` y `fuente/salidas.yaml`.",
        "",
        "## Valores vigentes",
        "",
        "| Valor | es | Fuente | Confianza | Vigente hasta | Revisar en |",
        "|---|---|---|---|---|---|",
    ]
    for name, spec in sources.values.items():
        out.append(
            f"| `{name}` | {_md_cell(render_value(sources, name, 'es'))} | {_md_cell(spec.get('source'))} "
            f"| {_md_cell(spec.get('confidence'))} | {_md_cell(spec.get('valid_until'))} "
            f"| {_md_cell(', '.join(spec.get('check_with') or []))} |"
        )
    out += ["", "## Índice", ""]
    by_topic: dict[str, list[dict[str, Any]]] = {}
    for entry in sources.faq:
        by_topic.setdefault(entry["topic"], []).append(entry)
    for topic in TOPICS:
        if topic in by_topic:
            out.append(f"- [{TOPICS[topic]}](#{topic}) ({len(by_topic[topic])})")
    for topic, title in TOPICS.items():
        entries = by_topic.get(topic)
        if not entries:
            continue
        out += ["", f'<a id="{topic}"></a>', f"## {title}", ""]
        for entry in entries:
            q = entry["question"]
            heading = q.get("es") or q.get("en") or next(iter(q.values()))
            ids = ", ".join(f"{lang}: {cid}" for lang, cid in entry_ids(entry).items())
            meta = f"`{entry['key']}` · {ids} · fuente: {entry['source']} · confianza: {entry.get('confidence', 'web')}"
            if entry.get("valid_until"):
                meta += f" · vigente hasta {entry['valid_until']}"
            out += [f"### {heading.strip()}", "", meta, ""]
            if entry.get("note"):
                out += [f"> Nota para el equipo: {' '.join(str(entry['note']).split())}", ""]
            if entry.get("also_asked"):
                out += ["También preguntan: " + " · ".join(a.strip() for a in entry["also_asked"]), ""]
            for lang, answer in entry["answer"].items():
                label = lang.upper()
                if len(entry["answer"]) > 1 or lang != "en":
                    out += [f"**{label}** — {q[lang].strip()}", ""]
                rendered = render(sources, answer, lang).strip()
                out += [line + "  " if line else "" for line in rendered.split("\n")]
                out.append("")
    return "\n".join(out).rstrip() + "\n"


def build_all(sources: Sources) -> dict[Path, str]:
    return {
        KNOWLEDGE / "datos-clave.md": build_key_facts_md(sources),
        KNOWLEDGE / "faq_rag_chunks.jsonl": build_chunks_jsonl(sources),
        KNOWLEDGE / "faq_structured.md": build_faq_md(sources),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="no escribe; falla si algo está desactualizado")
    parser.add_argument("--today", help="fecha para revisar vigencias (AAAA-MM-DD)")
    args = parser.parse_args(argv)

    sources = load_sources()
    errors = validate(sources, date.fromisoformat(args.today) if args.today else None)
    if errors:
        print("Errores en docs/knowledge/fuente/:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    stale = []
    for path, content in build_all(sources).items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            continue
        if args.check:
            stale.append(path.relative_to(ROOT))
        else:
            path.write_text(content, encoding="utf-8")
            print(f"escrito {path.relative_to(ROOT)}")
    if stale:
        print("Desactualizado (correr python3 scripts/build_knowledge.py): " + ", ".join(map(str, stale)), file=sys.stderr)
        return 1
    if not args.check:
        print(f"{len(build_chunks(sources))} fragmentos. Para el índice: python3 scripts/build_cloud_index.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
