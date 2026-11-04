"""Aggregate a run into a summary, render Markdown/HTML, and diff against a baseline.

summary.json is small (no transcripts except the worst ones) and is what you
commit as a baseline; run.json has every transcript and stays local.
"""
from __future__ import annotations

import html
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from evals.checks import CODES
from evals.judge import DIMENSIONS, JUDGE_CODES, render_transcript

WORST_N = 12
Block = tuple  # ("p", text) | ("table", headers, rows) | ("quote", text) | ("pre", title, text) | ("list", items)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _ci95(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    m = sum(values) / len(values)
    var = sum((v - m) ** 2 for v in values) / (len(values) - 1)
    return round(1.96 * math.sqrt(var / len(values)), 3)


def _severity_sum(rec: dict[str, Any]) -> int:
    det = sum(f["severity"] for f in rec["findings"])
    jud = sum(JUDGE_CODES.get(v["code"], (1,))[0] for v in rec["verdict"].get("violations", []))
    return det + jud


def summarize(run: dict[str, Any]) -> dict[str, Any]:
    records = run["records"]
    n = len(records)
    overall = [r["verdict"]["overall"] for r in records]
    dims = {d: [r["verdict"]["scores"][d] for r in records] for d in DIMENSIONS}

    det_conv: Counter = Counter()
    det_total: Counter = Counter()
    det_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    judge_conv: Counter = Counter()
    judge_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tags: Counter = Counter()
    tag_examples: dict[str, list[str]] = defaultdict(list)
    for r in records:
        pid = r["persona"]["id"]
        codes = set()
        for f in r["findings"]:
            det_total[f["code"]] += 1
            codes.add(f["code"])
            if len(det_examples[f["code"]]) < 3:
                det_examples[f["code"]].append({"persona": pid, "turn": f["turn"], "text": f["text"], "detail": f.get("detail", "")})
        for c in codes:
            det_conv[c] += 1
        jcodes = set()
        for v in r["verdict"].get("violations", []):
            jcodes.add(v["code"])
            if len(judge_examples[v["code"]]) < 3:
                judge_examples[v["code"]].append({"persona": pid, "turn": v["turn"], "text": v["quote"], "detail": v["why"]})
        for c in jcodes:
            judge_conv[c] += 1
        for t in r["verdict"].get("failure_tags", []):
            key = _norm_tag(t)
            tags[key] += 1
            if len(tag_examples[key]) < 3:
                tag_examples[key].append(pid)

    def breakdown(field: str) -> dict[str, Any]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in records:
            groups[str(r["persona"][field])].append(r)
        out = {}
        for key, recs in sorted(groups.items()):
            out[key] = {
                "n": len(recs),
                "overall": _mean([x["verdict"]["overall"] for x in recs]),
                "critical_rate": round(sum(1 for x in recs if any(f["severity"] >= 3 for f in x["findings"])) / len(recs), 3),
            }
        return out

    outcome_keys = ("email_requested", "client_gave_email", "email_captured", "videocall_offered", "paused")
    outcome_rates = {k: round(sum(1 for r in records if r["outcomes"].get(k)) / n, 3) if n else None for k in outcome_keys}
    turns = [r["outcomes"]["turns"] for r in records]

    patterns = failure_patterns(n, det_conv, det_examples, judge_conv, judge_examples)

    worst = sorted(records, key=lambda r: (r["verdict"]["overall"], -_severity_sum(r)))[:WORST_N]
    worst_out = [
        {
            "persona": r["persona"],
            "overall": r["verdict"]["overall"],
            "scores": r["verdict"]["scores"],
            "summary": r["verdict"].get("summary", ""),
            "findings": r["findings"][:8],
            "violations": r["verdict"].get("violations", [])[:8],
            "transcript": render_transcript(r["transcript"]),
        }
        for r in worst
    ]

    calibration = {}
    if run["mode"] == "real":
        for code in CODES:
            both = sum(1 for r in records if code in {f["code"] for f in r["findings"]} and code in {v["code"] for v in r["verdict"].get("violations", [])})
            det_only = det_conv[code] - both
            judge_only = judge_conv[code] - both
            if both or det_only or judge_only:
                calibration[code] = {"both": both, "regex_only": det_only, "judge_only": judge_only}

    cost = run["usage"]["total_cost_usd"]
    return {
        "schema": 1,
        "mode": run["mode"],
        "started_at": run["started_at"],
        "config": run["config"],
        "git": run["git"],
        "n": n,
        "errors": sum(1 for r in records if r.get("error")),
        "ended_by": dict(Counter(r["ended_by"] for r in records)),
        "avg_turns": _mean(turns),
        "overall": {"mean": _mean(overall), "ci95": _ci95(overall)},
        "dimensions": {d: {"mean": _mean(v), "ci95": _ci95(v)} for d, v in dims.items()},
        "deterministic": {
            c: {"conversations": det_conv[c], "rate": round(det_conv[c] / n, 4) if n else 0, "occurrences": det_total[c], "severity": CODES[c][0], "examples": det_examples[c]}
            for c in sorted(det_conv, key=lambda c: (-det_conv[c], c))
        },
        "judge_violations": {
            c: {"conversations": judge_conv[c], "rate": round(judge_conv[c] / n, 4) if n else 0, "severity": JUDGE_CODES.get(c, (1,))[0], "examples": judge_examples[c]}
            for c in sorted(judge_conv, key=lambda c: (-judge_conv[c], c))
        },
        "failure_tags": [{"tag": t, "conversations": c, "examples": tag_examples[t]} for t, c in tags.most_common(25)],
        "failure_patterns": patterns,
        "outcomes": outcome_rates,
        "by_language": breakdown("language"),
        "by_intent": breakdown("intent"),
        "by_style": breakdown("style"),
        "by_experience": breakdown("experience"),
        "calibration": calibration,
        "usage": run["usage"],
        "cost_per_conversation_usd": round(cost / n, 5) if n else None,
        "per_conversation": [
            {"id": r["persona"]["id"], "overall": r["verdict"]["overall"], "severity": _severity_sum(r), "codes": sorted({f["code"] for f in r["findings"]} | {v["code"] for v in r["verdict"].get("violations", [])})}
            for r in records
        ],
        "worst": worst_out,
    }


def _norm_tag(tag: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s/+-]", "", tag.lower())).strip()


def failure_patterns(n: int, det_conv: Counter, det_examples: dict, judge_conv: Counter, judge_examples: dict) -> list[dict[str, Any]]:
    """Codes ranked by how often they hit a conversation times their severity."""
    rows = []
    for code in set(det_conv) | set(judge_conv):
        if code in ("FAQ_ONLY_PRICE",):
            continue
        severity, dimension, desc = JUDGE_CODES.get(code, (1, "other", code))
        convs = max(det_conv.get(code, 0), judge_conv.get(code, 0))
        rows.append(
            {
                "code": code,
                "description": desc,
                "dimension": dimension,
                "severity": severity,
                "conversations": convs,
                "rate": round(convs / n, 4) if n else 0,
                "regex": det_conv.get(code, 0),
                "judge": judge_conv.get(code, 0),
                "impact": round(severity * convs / n, 4) if n else 0,
                "examples": (det_examples.get(code) or [])[:2] + (judge_examples.get(code) or [])[:2],
            }
        )
    rows.sort(key=lambda r: (-r["impact"], -r["conversations"], r["code"]))
    return rows


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------


def compare(current: dict[str, Any], baseline: dict[str, Any], threshold: float = 2.0) -> dict[str, Any]:
    """Diff two summaries. Positive deltas in scores are good; in rates, bad."""
    def delta(a: float | None, b: float | None) -> float | None:
        return None if a is None or b is None else round(a - b, 3)

    dims = {d: delta(current["dimensions"][d]["mean"], baseline["dimensions"].get(d, {}).get("mean")) for d in DIMENSIONS}
    codes = set(current["deterministic"]) | set(baseline["deterministic"]) | set(current["judge_violations"]) | set(baseline["judge_violations"])
    rate_deltas = {}
    for c in codes:
        cur = max(current["deterministic"].get(c, {}).get("rate", 0), current["judge_violations"].get(c, {}).get("rate", 0))
        base = max(baseline["deterministic"].get(c, {}).get("rate", 0), baseline["judge_violations"].get(c, {}).get("rate", 0))
        if cur or base:
            rate_deltas[c] = {"baseline": base, "current": cur, "delta": round(cur - base, 4)}
    paired = []
    base_by_id = {p["id"]: p for p in baseline.get("per_conversation", [])}
    for p in current.get("per_conversation", []):
        b = base_by_id.get(p["id"])
        if b:
            paired.append({"id": p["id"], "delta": round(p["overall"] - b["overall"], 1), "baseline": b["overall"], "current": p["overall"], "new_codes": sorted(set(p["codes"]) - set(b["codes"])), "fixed_codes": sorted(set(b["codes"]) - set(p["codes"]))})
    paired.sort(key=lambda x: x["delta"])
    overall_delta = delta(current["overall"]["mean"], baseline["overall"]["mean"])
    same_setup = (
        current["config"].get("seed") == baseline["config"].get("seed")
        and current["config"].get("n") == baseline["config"].get("n")
        and current["mode"] == baseline["mode"]
    )
    return {
        "baseline": {"commit": baseline["git"].get("commit"), "branch": baseline["git"].get("branch"), "mode": baseline["mode"], "n": baseline["n"], "started_at": baseline["started_at"]},
        "same_setup": same_setup,
        "overall_delta": overall_delta,
        "dimensions_delta": dims,
        "outcomes_delta": {k: delta(current["outcomes"].get(k), baseline["outcomes"].get(k)) for k in current["outcomes"]},
        "codes": dict(sorted(rate_deltas.items(), key=lambda kv: -abs(kv[1]["delta"]))),
        "cost_delta_per_conversation": delta(current.get("cost_per_conversation_usd"), baseline.get("cost_per_conversation_usd")),
        "regressed": paired[:10],
        "improved": list(reversed(paired[-10:])) if paired else [],
        "regression": overall_delta is not None and overall_delta < -threshold,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt(x: Any, pct: bool = False) -> str:
    if x is None:
        return "—"
    if pct:
        return f"{100 * x:.1f}%"
    if isinstance(x, float):
        return f"{x:.2f}"
    return str(x)


def _signed(x: float | None, pct: bool = False) -> str:
    if x is None:
        return "—"
    return f"{'+' if x > 0 else ''}{100 * x:.1f} pp" if pct else f"{'+' if x > 0 else ''}{x:.2f}"


def build_sections(summary: dict[str, Any], comparison: dict[str, Any] | None = None, top_patterns: int = 10) -> list[tuple[str, list[Block]]]:
    s = summary
    sections: list[tuple[str, list[Block]]] = []
    cfg = s["config"]
    head: list[Block] = [
        ("p", f"Modo: **{s['mode']}** · commit `{s['git'].get('commit')}` ({s['git'].get('branch')}{', con cambios sin commitear' if s['git'].get('dirty') else ''}) · {s['started_at']}"),
        ("p", f"{s['n']} conversaciones (semilla {cfg['seed']}, {cfg['llm_personas']} personas escritas por LLM) · {s['avg_turns']} turnos promedio · errores: {s['errors']} · Nico: `{cfg['nico_model']}` · simulador: `{cfg['simulator_model']}` · juez: `{cfg['judge_model'] if cfg['judge'] else 'sin juez'}`"),
        ("p", f"Costo total: **USD {s['usage']['total_cost_usd']:.2f}** (USD {s['cost_per_conversation_usd'] or 0:.4f} por conversación)"),
    ]
    if s["mode"] != "real":
        head.append(("quote", "Corrida OFFLINE: Nico respondió con un stub (inicio de la respuesta del FAQ), el cliente fue un guion fijo y los puntajes salen solo de los chequeos deterministas. Sirve para probar el harness y las reglas fijas del código, no la calidad del prompt."))
    sections.append(("Resumen", head))

    rows = [["**overall (0-100)**", _fmt(s["overall"]["mean"]), f"±{_fmt(s['overall']['ci95'])}"]]
    rows += [[d, _fmt(v["mean"]), f"±{_fmt(v['ci95'])}"] for d, v in s["dimensions"].items()]
    sections.append(("Puntajes por dimensión (1-5)", [("table", ["dimensión", "media", "IC 95%"], rows)]))

    if comparison:
        c = comparison
        blocks: list[Block] = [
            ("p", f"Baseline: commit `{c['baseline']['commit']}` ({c['baseline']['branch']}, {c['baseline']['mode']}, n={c['baseline']['n']}, {c['baseline']['started_at']}). Mismo set de personas: {'sí' if c['same_setup'] else 'NO (los deltas por conversación no aplican)'}."),
            ("p", f"Overall: **{_signed(c['overall_delta'])}**{' ⚠️ REGRESIÓN' if c['regression'] else ''} · costo por conversación: {_signed(c['cost_delta_per_conversation'])} USD"),
            ("table", ["dimensión", "Δ"], [[d, _signed(v)] for d, v in c["dimensions_delta"].items()]),
            ("table", ["resultado", "Δ"], [[k, _signed(v, pct=True)] for k, v in c["outcomes_delta"].items()]),
            ("table", ["código", "baseline", "ahora", "Δ"], [[k, _fmt(v["baseline"], True), _fmt(v["current"], True), _signed(v["delta"], True)] for k, v in list(c["codes"].items())[:20]]),
        ]
        if c["same_setup"] and c["regressed"]:
            blocks.append(("table", ["persona", "baseline", "ahora", "Δ", "códigos nuevos", "códigos resueltos"], [[x["id"], x["baseline"], x["current"], x["delta"], ", ".join(x["new_codes"]), ", ".join(x["fixed_codes"])] for x in c["regressed"] if x["delta"] < 0]))
        sections.append(("Comparación con baseline", blocks))

    pats = s["failure_patterns"][:top_patterns]
    items = []
    for i, p in enumerate(pats, 1):
        ex = p["examples"][0] if p["examples"] else None
        quote = f' Ej. ({ex["persona"]}, turno {ex["turn"]}): "{_short(ex["text"], 160)}"' if ex else ""
        items.append(f"**{p['code']}** ({p['dimension']}, sev {p['severity']}): {p['description']}. {p['conversations']} conv. ({_fmt(p['rate'], True)}; regex {p['regex']}, juez {p['judge']}).{quote}")
    sections.append((f"Top {top_patterns} patrones de falla", [("list", items or ["Sin fallas detectadas."])]))

    if s["failure_tags"]:
        sections.append(("Etiquetas libres del juez", [("table", ["etiqueta", "conv.", "ejemplos"], [[t["tag"], t["conversations"], ", ".join(t["examples"])] for t in s["failure_tags"][:15]])]))

    det_rows = [[c, v["severity"], v["conversations"], _fmt(v["rate"], True), v["occurrences"]] for c, v in s["deterministic"].items()]
    sections.append(("Chequeos deterministas (regex)", [("table", ["código", "sev", "conv.", "tasa", "ocurrencias"], det_rows or [["—", "", "", "", ""]])]))
    if s["judge_violations"]:
        sections.append(("Violaciones según el juez", [("table", ["código", "sev", "conv.", "tasa"], [[c, v["severity"], v["conversations"], _fmt(v["rate"], True)] for c, v in s["judge_violations"].items()])]))

    sections.append(("Resultados de venta", [("table", ["resultado", "tasa"], [[k, _fmt(v, True)] for k, v in s["outcomes"].items()])]))
    for title, key in (("Por idioma", "by_language"), ("Por intención", "by_intent"), ("Por estilo", "by_style"), ("Por experiencia", "by_experience")):
        sections.append((title, [("table", ["grupo", "n", "overall", "% con falla crítica"], [[k, v["n"], _fmt(v["overall"]), _fmt(v["critical_rate"], True)] for k, v in s[key].items()])]))

    if s["calibration"]:
        sections.append(("Calibración juez vs regex", [
            ("p", "Para los códigos que detectan los dos: cuántas conversaciones marcó cada uno. Mucho 'solo regex' = regex con falsos positivos o juez distraído; mucho 'solo juez' = falta un regex o el juez exagera."),
            ("table", ["código", "ambos", "solo regex", "solo juez"], [[c, v["both"], v["regex_only"], v["judge_only"]] for c, v in s["calibration"].items()]),
        ]))

    usage_rows = [[u["role"], u["model"], u["calls"], u["input_tokens"], u["cached_input_tokens"], u["output_tokens"], _fmt(u["cost_usd"])] for u in s["usage"]["by_role"]]
    sections.append(("Tokens y costo", [("table", ["rol", "modelo", "llamadas", "input", "cached", "output", "USD"], usage_rows)]))

    worst_blocks: list[Block] = []
    for w in s["worst"]:
        p = w["persona"]
        problems = [f"{f['code']} (t{f['turn']})" for f in w["findings"]] + [f"{v['code']} (t{v['turn']}): {_short(v['why'], 100)}" for v in w["violations"]]
        title = f"{p['id']} · {p['language']} · {p['intent']} · {p['style']} · {p['experience']} — overall {w['overall']}"
        body = (w["summary"] + "\n" if w["summary"] else "") + ("Problemas: " + "; ".join(problems) + "\n\n" if problems else "") + w["transcript"]
        worst_blocks.append(("pre", title, body))
    sections.append((f"Peores {len(s['worst'])} conversaciones", worst_blocks))
    return sections


def _short(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def render_markdown(sections: list[tuple[str, list[Block]]], title: str) -> str:
    out = [f"# {title}", ""]
    for name, blocks in sections:
        out += [f"## {name}", ""]
        for b in blocks:
            kind = b[0]
            if kind == "p":
                out += [b[1], ""]
            elif kind == "quote":
                out += [f"> {b[1]}", ""]
            elif kind == "list":
                out += [f"{i}. {item}" for i, item in enumerate(b[1], 1)] + [""]
            elif kind == "table":
                headers, rows = b[1], b[2]
                out.append("| " + " | ".join(headers) + " |")
                out.append("|" + "---|" * len(headers))
                for row in rows:
                    out.append("| " + " | ".join(str(c).replace("|", "\\|").replace("\n", " ") for c in row) + " |")
                out.append("")
            elif kind == "pre":
                out += [f"<details><summary>{html.escape(b[1])}</summary>", "", "```", b[2], "```", "", "</details>", ""]
    return "\n".join(out)


def _inline(text: str) -> str:
    t = html.escape(str(text))
    t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", t)


def render_html(sections: list[tuple[str, list[Block]]], title: str) -> str:
    parts = [
        "<!doctype html><html lang='es'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>",
        f"<title>{html.escape(title)}</title><style>",
        ":root{--bg:#fff;--fg:#1d2327;--muted:#5b6670;--line:#dde3e8;--accent:#0b6e4f;--code:#f4f6f8}",
        "@media (prefers-color-scheme:dark){:root{--bg:#14181b;--fg:#e6e9ec;--muted:#9aa5ae;--line:#2c343a;--accent:#4cc38a;--code:#1d2328}}",
        "body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:0 auto;padding:16px}",
        "h1{font-size:1.6em}h2{margin-top:2em;border-bottom:1px solid var(--line);padding-bottom:4px;color:var(--accent)}",
        "table{border-collapse:collapse;width:100%;display:block;overflow-x:auto;margin:8px 0}td,th{border:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}",
        "th{background:var(--code)}code,pre{background:var(--code);border-radius:4px}pre{padding:10px;white-space:pre-wrap;font-size:13px}",
        "blockquote{border-left:4px solid var(--accent);margin:8px 0;padding:4px 12px;color:var(--muted)}details{margin:6px 0}summary{cursor:pointer}",
        "</style></head><body>",
        f"<h1>{html.escape(title)}</h1>",
    ]
    for name, blocks in sections:
        parts.append(f"<h2>{html.escape(name)}</h2>")
        for b in blocks:
            kind = b[0]
            if kind == "p":
                parts.append(f"<p>{_inline(b[1])}</p>")
            elif kind == "quote":
                parts.append(f"<blockquote>{_inline(b[1])}</blockquote>")
            elif kind == "list":
                parts.append("<ol>" + "".join(f"<li>{_inline(i)}</li>" for i in b[1]) + "</ol>")
            elif kind == "table":
                parts.append("<table><thead><tr>" + "".join(f"<th>{html.escape(h)}</th>" for h in b[1]) + "</tr></thead><tbody>")
                for row in b[2]:
                    parts.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>")
                parts.append("</tbody></table>")
            elif kind == "pre":
                parts.append(f"<details><summary>{html.escape(b[1])}</summary><pre>{html.escape(b[2])}</pre></details>")
    parts.append("</body></html>")
    return "\n".join(parts)


def write_outputs(run: dict[str, Any], out_dir: Path, baseline_path: Path | None = None, keep_run: bool = True) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = summarize(run)
    comparison = None
    if baseline_path:
        baseline = load_summary(baseline_path)
        comparison = compare(summary, baseline)
        summary["comparison"] = comparison
    title = f"Evals de Nico — {summary['started_at'][:16].replace('T', ' ')}{' · ' + run['config']['label'] if run['config'].get('label') else ''}"
    sections = build_sections(summary, comparison)
    if keep_run:
        (out_dir / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "report.md").write_text(render_markdown(sections, title), encoding="utf-8")
    (out_dir / "report.html").write_text(render_html(sections, title), encoding="utf-8")
    return summary


def load_summary(path: Path) -> dict[str, Any]:
    """Accept a summary.json, a run.json, or a run directory."""
    path = Path(path)
    if path.is_dir():
        path = path / "summary.json" if (path / "summary.json").exists() else path / "run.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return summarize(data) if "records" in data else data
