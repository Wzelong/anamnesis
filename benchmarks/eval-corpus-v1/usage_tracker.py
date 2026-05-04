"""Per-stage usage tracking for the augmentation benchmark.

Wraps an AsyncOpenAI client so every responses.parse / responses.create call
is intercepted, attributed to the current stage (via a contextvar), and rolled
up by stage. Pricing comes from core.pricing so cost numbers match production.
"""
from __future__ import annotations

import time
from collections import defaultdict
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal

from core.pricing import estimate_cost

_current_stage: ContextVar[str] = ContextVar("benchmark_stage", default="unattributed")


@dataclass
class StageStats:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    wall_ms: int = 0
    usd: Decimal = field(default_factory=lambda: Decimal("0"))
    by_model: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def to_dict(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "wall_ms": self.wall_ms,
            "usd": float(self.usd),
            "by_model": dict(self.by_model),
        }


class UsageTracker:
    def __init__(self) -> None:
        self.stages: dict[str, StageStats] = defaultdict(StageStats)

    def record(self, stage: str, model: str, usage, wall_ms: int) -> None:
        s = self.stages[stage]
        in_t = int(getattr(usage, "input_tokens", 0) or 0)
        out_t = int(getattr(usage, "output_tokens", 0) or 0)
        cached = 0
        reasoning = 0
        in_details = getattr(usage, "input_tokens_details", None)
        if in_details is not None:
            cached = int(getattr(in_details, "cached_tokens", 0) or 0)
        out_details = getattr(usage, "output_tokens_details", None)
        if out_details is not None:
            reasoning = int(getattr(out_details, "reasoning_tokens", 0) or 0)

        s.calls += 1
        s.input_tokens += in_t
        s.output_tokens += out_t
        s.cached_tokens += cached
        s.reasoning_tokens += reasoning
        s.wall_ms += wall_ms
        s.usd += estimate_cost(
            model=model, input_tokens=in_t, cached_tokens=cached, output_tokens=out_t,
        )
        s.by_model[model] += 1

    def totals(self) -> dict:
        out = StageStats()
        models: dict[str, int] = defaultdict(int)
        for s in self.stages.values():
            out.calls += s.calls
            out.input_tokens += s.input_tokens
            out.output_tokens += s.output_tokens
            out.cached_tokens += s.cached_tokens
            out.reasoning_tokens += s.reasoning_tokens
            out.wall_ms += s.wall_ms
            out.usd += s.usd
            for m, c in s.by_model.items():
                models[m] += c
        out.by_model = models
        return out.to_dict()

    def to_dict(self) -> dict:
        return {
            "by_stage": {k: v.to_dict() for k, v in self.stages.items()},
            "totals": self.totals(),
        }


class _StageScope:
    def __init__(self, stage: str) -> None:
        self.stage = stage
        self._token = None

    def __enter__(self):
        self._token = _current_stage.set(self.stage)
        return self

    def __exit__(self, *exc):
        _current_stage.reset(self._token)


def stage_scope(stage: str) -> _StageScope:
    return _StageScope(stage)


class _TrackedResponses:
    def __init__(self, real, tracker: UsageTracker) -> None:
        self._real = real
        self._tracker = tracker

    async def parse(self, **kwargs):
        return await self._dispatch(self._real.parse, kwargs)

    async def create(self, **kwargs):
        return await self._dispatch(self._real.create, kwargs)

    async def _dispatch(self, fn, kwargs):
        t0 = time.perf_counter()
        resp = await fn(**kwargs)
        wall_ms = int((time.perf_counter() - t0) * 1000)
        usage = getattr(resp, "usage", None)
        if usage is not None:
            self._tracker.record(
                stage=_current_stage.get(),
                model=kwargs.get("model", "unknown"),
                usage=usage,
                wall_ms=wall_ms,
            )
        return resp

    def __getattr__(self, name):
        return getattr(self._real, name)


class TrackedClient:
    """Transparent proxy: only `responses.parse` / `responses.create` are intercepted."""

    def __init__(self, real, tracker: UsageTracker) -> None:
        self._real = real
        self._tracker = tracker
        self.responses = _TrackedResponses(real.responses, tracker)

    def __getattr__(self, name):
        return getattr(self._real, name)


def wrap_client(client, tracker: UsageTracker) -> TrackedClient:
    return TrackedClient(client, tracker)
