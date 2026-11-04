"""Run many simulated conversations against Nico and score them."""
from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.checks import check_conversation, outcomes
from evals.judge import LLMJudge, stub_verdict
from evals.llm import ChatJSON, UsageTracker, make_openai_client
from evals.nico_driver import NicoHarness
from evals.personas import Persona, generate_personas, write_llm_personas
from evals.simulator import LLMCustomer, ScriptedCustomer

ROOT = Path(__file__).resolve().parents[1]


@dataclass
class EvalConfig:
    n: int = 50
    seed: int = 7
    llm_personas: int = 0
    concurrency: int = 8
    nico_model: str = "gpt-4.1-mini"
    simulator_model: str = "gpt-4.1-mini"
    judge_model: str = "gpt-4.1"
    embed_model: str | None = None
    offline: bool = False
    judge: bool = True
    max_turns: int | None = None
    intents: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def git_info() -> dict[str, Any]:
    def run(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    return {
        "commit": run("rev-parse", "--short", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(run("status", "--porcelain", "--", "orchestrator", "docs")),
    }


def build_personas(cfg: EvalConfig, persona_chat: Any | None) -> list[Persona]:
    personas = generate_personas(cfg.n, cfg.seed)
    if cfg.llm_personas and persona_chat is not None:
        personas += write_llm_personas(persona_chat, cfg.llm_personas, cfg.seed, start_index=0)
    if cfg.intents:
        personas = [p for p in personas if p.intent in cfg.intents]
    if cfg.languages:
        personas = [p for p in personas if p.language in cfg.languages]
    if cfg.max_turns:
        for p in personas:
            p.max_turns = min(p.max_turns, cfg.max_turns)
    return personas


def run_conversation(
    harness: NicoHarness,
    persona: Persona,
    customer: Any,
    judge: Any | None,
    seed: int,
) -> dict[str, Any]:
    conv_id = f"eval-{persona.id}-{seed}"
    started = time.time()
    transcript: list[dict[str, Any]] = []
    history: list[dict[str, str]] = []
    ended_by = "max_turns"
    error = None
    with harness.conversation_usage() as nico_usage:
        try:
            for i in range(persona.max_turns):
                step = customer.next_turn(history)
                if not step["messages"]:
                    ended_by = "customer"
                    break
                turn = {"turn": i, "client": step["messages"], "nico": [], "errors": [], "paused": []}
                for msg in step["messages"]:
                    turn["paused"].append(bool(harness.session_vars(conv_id).get("conversation_paused")))
                    res = harness.send(conv_id, msg, persona.channel)
                    turn["nico"].append(res["bubbles"])
                    if res["error"]:
                        turn["errors"].append(res["error"])
                    history.append({"role": "client", "text": msg})
                    for bubble in res["bubbles"]:
                        history.append({"role": "nico", "text": bubble})
                transcript.append(turn)
                if step["done"]:
                    ended_by = "customer"
                    break
        except Exception as exc:  # keep the run going; the record says what broke
            error = f"{type(exc).__name__}: {exc}"
            ended_by = "error"
            traceback.print_exc(file=sys.stderr)
    session_vars = harness.session_vars(conv_id)
    findings = check_conversation(transcript, persona)
    outs = outcomes(transcript, session_vars)
    verdict = None
    if judge is not None and transcript:
        try:
            verdict = judge(persona, transcript, findings, seed=seed)
        except Exception as exc:
            error = (error or "") + f" judge: {exc}"
    if verdict is None:
        verdict = stub_verdict(findings, outs, persona)
    return {
        "persona": persona.to_dict(),
        "conversation_id": conv_id,
        "transcript": transcript,
        "findings": [f.to_dict() for f in findings],
        "outcomes": outs,
        "verdict": verdict,
        "nico_usage": dict(nico_usage),
        "ended_by": ended_by,
        "error": error,
        "seconds": round(time.time() - started, 2),
    }


def run_eval(cfg: EvalConfig, *, progress: bool = True, server_log: io.TextIOBase | None = None) -> dict[str, Any]:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        cfg.offline = True
    tracker = UsageTracker()
    client = None if cfg.offline else make_openai_client(api_key)
    persona_chat = None if cfg.offline else ChatJSON(client, cfg.simulator_model, tracker, "persona_writer", temperature=1.0)
    personas = build_personas(cfg, persona_chat)

    judge = None
    if not cfg.offline and cfg.judge:
        judge = LLMJudge(ChatJSON(client, cfg.judge_model, tracker, "judge", temperature=0.0))
    sim_chat = None if cfg.offline else ChatJSON(client, cfg.simulator_model, tracker, "simulator", temperature=0.9)

    started = datetime.now(timezone.utc)
    records: list[dict[str, Any]] = []
    lock = threading.Lock()
    with NicoHarness(
        tracker,
        offline=cfg.offline,
        nico_model=cfg.nico_model,
        embed_model=cfg.embed_model,
        api_key=api_key or None,
        server_log=server_log,
    ) as harness:

        def task(idx: int, persona: Persona) -> dict[str, Any]:
            seed = cfg.seed * 100_000 + idx
            customer = ScriptedCustomer(persona, cfg.seed) if cfg.offline else LLMCustomer(sim_chat, persona, seed)
            return run_conversation(harness, persona, customer, judge, seed)

        with ThreadPoolExecutor(max_workers=max(1, cfg.concurrency)) as pool:
            futures = [pool.submit(task, i, p) for i, p in enumerate(personas)]
            for fut in as_completed(futures):
                rec = fut.result()
                with lock:
                    records.append(rec)
                    if progress and (sys.stderr.isatty() or len(records) % 25 == 0 or len(records) == len(personas)):
                        cost = tracker.summary()["total_cost_usd"]
                        print(
                            f"\r[{len(records)}/{len(personas)}] {rec['persona']['id']} "
                            f"overall={rec['verdict']['overall']:.0f} costo=USD {cost:.2f}   ",
                            end="" if sys.stderr.isatty() else "\n",
                            file=sys.stderr,
                            flush=True,
                        )
    if progress:
        print(file=sys.stderr)
    records.sort(key=lambda r: r["persona"]["id"])
    return {
        "schema": 1,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": cfg.to_dict(),
        "git": git_info(),
        "mode": "offline-stub" if cfg.offline else "real",
        "usage": tracker.summary(),
        "records": records,
    }
