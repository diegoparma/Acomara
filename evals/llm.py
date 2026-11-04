"""LLM access for the harness: token/cost accounting and a JSON chat helper.

Every model call made during a run (Nico's replies and embeddings, the
customer simulator, the judge, persona writing) goes through a UsageTracker so
the report can say what the run cost. Prices are USD per 1M tokens; update
PRICES when OpenAI changes them.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from typing import Any

# USD per 1M tokens: (input, cached input, output). Embeddings: output 0.
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-4.1": (2.00, 0.50, 8.00),
    "gpt-4.1-mini": (0.40, 0.10, 1.60),
    "gpt-4.1-nano": (0.10, 0.025, 0.40),
    "gpt-4o": (2.50, 1.25, 10.00),
    "gpt-4o-mini": (0.15, 0.075, 0.60),
    "gpt-5": (1.25, 0.125, 10.00),
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "gpt-5-nano": (0.05, 0.005, 0.40),
    "text-embedding-3-small": (0.02, 0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.13, 0.0),
}


def price_for(model: str) -> tuple[float, float, float] | None:
    if model in PRICES:
        return PRICES[model]
    # Dated snapshots ("gpt-4.1-mini-2025-04-14") price like their family.
    for name in sorted(PRICES, key=len, reverse=True):
        if model.startswith(name + "-"):
            return PRICES[name]
    return None


def cost_usd(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float | None:
    price = price_for(model)
    if price is None:
        return None
    p_in, p_cached, p_out = price
    uncached = max(0, input_tokens - cached_tokens)
    return (uncached * p_in + cached_tokens * p_cached + output_tokens * p_out) / 1_000_000


@dataclass
class UsageTracker:
    """Thread-safe token counter grouped by role ("nico", "simulator", "judge"...)."""

    rows: dict[tuple[str, str], dict[str, int]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, role: str, model: str, input_tokens: int = 0, cached_tokens: int = 0, output_tokens: int = 0) -> None:
        with self._lock:
            row = self.rows.setdefault((role, model), {"calls": 0, "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0})
            row["calls"] += 1
            row["input_tokens"] += int(input_tokens or 0)
            row["cached_input_tokens"] += int(cached_tokens or 0)
            row["output_tokens"] += int(output_tokens or 0)

    def record_openai_usage(self, role: str, model: str, usage: Any) -> None:
        """Accept a Responses-API or Chat-Completions usage object (or None)."""
        if usage is None:
            self.record(role, model)
            return
        inp = getattr(usage, "input_tokens", None)
        if inp is None:
            inp = getattr(usage, "prompt_tokens", 0)
        out = getattr(usage, "output_tokens", None)
        if out is None:
            out = getattr(usage, "completion_tokens", 0)
        details = getattr(usage, "input_tokens_details", None) or getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) if details is not None else 0
        self.record(role, model, int(inp or 0), int(cached or 0), int(out or 0))

    def summary(self) -> dict[str, Any]:
        with self._lock:
            items = sorted(self.rows.items())
        by_role: list[dict[str, Any]] = []
        total = 0.0
        unknown = []
        for (role, model), row in items:
            cost = cost_usd(model, row["input_tokens"], row["cached_input_tokens"], row["output_tokens"])
            if cost is None:
                unknown.append(model)
            else:
                total += cost
            by_role.append({"role": role, "model": model, **row, "cost_usd": None if cost is None else round(cost, 4)})
        return {"by_role": by_role, "total_cost_usd": round(total, 4), "models_without_price": sorted(set(unknown))}


class ChatJSON:
    """Chat Completions call that must return a JSON object, with retries."""

    def __init__(self, client: Any, model: str, tracker: UsageTracker, role: str, temperature: float = 0.7) -> None:
        self.client = client
        self.model = model
        self.tracker = tracker
        self.role = role
        self.temperature = temperature

    def __call__(self, system: str, user: str, *, seed: int | None = None, max_tokens: int = 800, attempts: int = 3) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                    "response_format": {"type": "json_object"},
                    "max_tokens": max_tokens,
                }
                # Reasoning models reject temperature; everything else takes it.
                if not self.model.startswith(("o1", "o3", "o4", "gpt-5")):
                    kwargs["temperature"] = self.temperature
                if seed is not None:
                    kwargs["seed"] = seed
                resp = self.client.chat.completions.create(**kwargs)
                self.tracker.record_openai_usage(self.role, self.model, getattr(resp, "usage", None))
                text = resp.choices[0].message.content or "{}"
                return json.loads(text)
            except json.JSONDecodeError as exc:
                last_error = exc
            except Exception as exc:  # network / rate limit: back off and retry
                last_error = exc
                time.sleep(2 ** attempt)
        raise RuntimeError(f"{self.role} call failed after {attempts} attempts: {last_error}")


def make_openai_client(api_key: str) -> Any:
    from openai import OpenAI

    return OpenAI(api_key=api_key, max_retries=6, timeout=90)
