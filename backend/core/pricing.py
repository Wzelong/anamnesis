"""USD cost estimation for Gemini calls, per 1M tokens.

Source: https://ai.google.dev/gemini-api/docs/pricing (standard paid tier).
Promotional rates carry their own expiry and revert automatically; pass `on` to
price a call against a specific date.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from decimal import Decimal

log = logging.getLogger(__name__)

_D = Decimal


SHORT_CONTEXT: dict[str, dict[str, Decimal]] = {
    "gemini-3.7-flash": {"input": _D("1.50"), "cached": _D("0.15"), "output": _D("7.50")},
    "gemini-3.6-flash": {"input": _D("1.50"), "cached": _D("0.15"), "output": _D("7.50")},
    "gemini-3.5-flash": {"input": _D("1.50"), "cached": _D("0.15"), "output": _D("9.00")},
    "gemini-3.1-flash-lite": {"input": _D("0.25"), "cached": _D("0.025"), "output": _D("1.50")},
}

# Introductory rates that revert to SHORT_CONTEXT on the expiry date. Kept separate
# so the revert is automatic: hardcoding a promotional rate silently doubles every
# recorded cost the day it lapses.
PROMOTIONAL: dict[str, tuple[date, dict[str, Decimal]]] = {
    "gemini-3.7-flash": (
        date(2027, 1, 1),
        {"input": _D("0.75"), "cached": _D("0.075"), "output": _D("3.75")},
    ),
    "gemini-3.6-flash": (
        date(2027, 1, 1),
        {"input": _D("0.75"), "cached": _D("0.075"), "output": _D("3.75")},
    ),
}

# Gemini 3.x Flash models have no context-length price tiers.
LONG_CONTEXT: dict[str, dict[str, Decimal]] = {}

LONG_CONTEXT_THRESHOLD = 200_000
REGIONAL_UPLIFT = Decimal("1.10")
_PER_MILLION = Decimal("1000000")
_ZERO = Decimal("0")
_warned_models: set[str] = set()


def _normalize(model: str) -> str:
    return model.split("-20", 1)[0] if "-20" in model else model


def _rates_for(model: str, input_tokens: int, on: date) -> dict[str, Decimal] | None:
    key = _normalize(model)
    if input_tokens > LONG_CONTEXT_THRESHOLD and key in LONG_CONTEXT:
        return LONG_CONTEXT[key]
    promo = PROMOTIONAL.get(key)
    if promo is not None and on < promo[0]:
        return promo[1]
    if key in SHORT_CONTEXT:
        return SHORT_CONTEXT[key]
    if key not in _warned_models:
        log.warning("pricing: unknown model %r; usd_cost will be 0", model)
        _warned_models.add(key)
    return None


def estimate_cost(
    model: str,
    input_tokens: int,
    cached_tokens: int,
    output_tokens: int,
    *,
    regional: bool = False,
    on: date | None = None,
) -> Decimal:
    rates = _rates_for(model, input_tokens, on or datetime.now(UTC).date())
    if rates is None:
        return _ZERO

    billed_input = max(input_tokens - cached_tokens, 0)
    cost = (
        Decimal(billed_input) * rates["input"]
        + Decimal(cached_tokens) * rates["cached"]
        + Decimal(output_tokens) * rates["output"]
    ) / _PER_MILLION

    if regional:
        cost = cost * REGIONAL_UPLIFT
    return cost.quantize(Decimal("0.000001"))
