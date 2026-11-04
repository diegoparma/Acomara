#!/usr/bin/env python3
"""Evaluate Nico with hundreds of simulated conversations (docs/sales-agent/16-evals.md).

Examples:
    # offline smoke test (no key needed: stub model, scripted customers)
    python3 scripts/run_evals.py --n 40 --offline

    # baseline on main, real models
    python3 scripts/run_evals.py --n 300 --llm-personas 30 --label baseline-main \
        --out evals/baselines/main

    # a change, compared against the baseline (same seed and n => paired diff)
    python3 scripts/run_evals.py --n 300 --llm-personas 30 --compare evals/baselines/main/summary.json

    # re-render a report / diff from saved runs without calling any model
    python3 scripts/run_evals.py --report evals/runs/<dir>/run.json --compare evals/baselines/main/summary.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from evals.personas import INTENTS, LANGUAGES  # noqa: E402
from evals.report import write_outputs  # noqa: E402
from evals.runner import EvalConfig, run_eval  # noqa: E402


def calibrate(args: argparse.Namespace) -> int:
    from evals.calibration import regex_results, run_judge_calibration

    bad = [r for r in regex_results() if r["missing"] or r["unexpected"]]
    print(f"Regex: {len(regex_results()) - len(bad)}/{len(regex_results())} casos OK")
    for r in bad:
        print(f"  {r['name']}: faltan {r['missing']} · sobran {r['unexpected']}")
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key or args.offline:
        print("Sin OPENAI_API_KEY: solo se calibraron los regex.")
        return 1 if bad else 0
    from evals.judge import LLMJudge
    from evals.llm import ChatJSON, UsageTracker, make_openai_client

    tracker = UsageTracker()
    judge = LLMJudge(ChatJSON(make_openai_client(key), args.judge_model, tracker, "judge", temperature=0.0))
    result = run_judge_calibration(judge)
    print(f"Juez {args.judge_model}: {result['passed']}/{result['total']} casos dentro de lo esperado · USD {tracker.summary()['total_cost_usd']:.3f}")
    for r in result["rows"]:
        if not r["ok"] or r["codes_missed_by_judge"]:
            print(f"  {r['name']}: {'; '.join(r['problems'])} {'· no marcó ' + ', '.join(r['codes_missed_by_judge']) if r['codes_missed_by_judge'] else ''}")
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=50, help="combinatorial personas (default 50)")
    ap.add_argument("--llm-personas", type=int, default=0, help="extra personas written by the simulator model")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--nico-model", default=os.environ.get("EVAL_NICO_MODEL", "gpt-4.1-mini"), help="Nico's chat model (production: gpt-4.1-mini)")
    ap.add_argument("--embed-model", default=None, help="embeddings model (default OPENAI_EMBED_MODEL or text-embedding-3-small)")
    ap.add_argument("--simulator-model", default=os.environ.get("EVAL_SIMULATOR_MODEL", "gpt-4.1-mini"))
    ap.add_argument("--judge-model", default=os.environ.get("EVAL_JUDGE_MODEL", "gpt-4.1"))
    ap.add_argument("--no-judge", action="store_true", help="skip the LLM judge (deterministic checks only)")
    ap.add_argument("--offline", action="store_true", help="no model calls at all (automatic without OPENAI_API_KEY)")
    ap.add_argument("--max-turns", type=int, default=None, help="cap turns per conversation")
    ap.add_argument("--intent", action="append", choices=INTENTS, help="only these intents (repeatable)")
    ap.add_argument("--language", action="append", choices=LANGUAGES, help="only these languages (repeatable)")
    ap.add_argument("--label", default="")
    ap.add_argument("--out", default=None, help="output dir (default evals/runs/<timestamp>_<label>)")
    ap.add_argument("--compare", default=None, help="baseline summary.json / run.json / dir to diff against")
    ap.add_argument("--fail-on-regression", type=float, default=None, metavar="POINTS", help="exit 1 if overall drops more than POINTS vs --compare")
    ap.add_argument("--report", default=None, help="only re-render outputs from an existing run.json")
    ap.add_argument("--calibrate", action="store_true", help="score the hand-labelled calibration cases with the judge (needs a key) and exit")
    ap.add_argument("--no-run-json", action="store_true", help="don't write run.json (all transcripts)")
    args = ap.parse_args(argv)

    if args.calibrate:
        return calibrate(args)
    if args.report:
        run = json.loads(Path(args.report).read_text(encoding="utf-8"))
        out = Path(args.out) if args.out else Path(args.report).parent
        summary = write_outputs(run, out, Path(args.compare) if args.compare else None, keep_run=False)
    else:
        if not os.environ.get("OPENAI_API_KEY") and not args.offline:
            print("Sin OPENAI_API_KEY: corriendo OFFLINE (stub de Nico, clientes guionados, sin juez).", file=sys.stderr)
        cfg = EvalConfig(
            n=args.n,
            seed=args.seed,
            llm_personas=args.llm_personas,
            concurrency=args.concurrency,
            nico_model=args.nico_model,
            simulator_model=args.simulator_model,
            judge_model=args.judge_model,
            embed_model=args.embed_model,
            offline=args.offline,
            judge=not args.no_judge,
            max_turns=args.max_turns,
            intents=args.intent or [],
            languages=args.language or [],
            label=args.label,
        )
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out = Path(args.out) if args.out else ROOT / "evals" / "runs" / f"{stamp}{'_' + args.label if args.label else ''}"
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "server.log", "w", encoding="utf-8") as log:
            run = run_eval(cfg, server_log=log)
        summary = write_outputs(run, out, Path(args.compare) if args.compare else None, keep_run=not args.no_run_json)

    print(f"\nOverall {summary['overall']['mean']} (±{summary['overall']['ci95']}) · n={summary['n']} · USD {summary['usage']['total_cost_usd']:.2f}")
    for p in summary["failure_patterns"][:10]:
        print(f"  {p['code']:<32} {p['conversations']:>4} conv  sev {p['severity']}")
    print(f"Reporte: {out / 'report.md'}  ·  {out / 'report.html'}")
    comparison = summary.get("comparison")
    if comparison:
        print(f"Δ overall vs baseline: {comparison['overall_delta']}")
        if args.fail_on_regression is not None and comparison["overall_delta"] is not None and comparison["overall_delta"] < -args.fail_on_regression:
            print("REGRESIÓN", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
