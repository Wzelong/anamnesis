import asyncio
from decimal import Decimal

import pytest

from core.pricing import (
    REGIONAL_UPLIFT,
    SHORT_CONTEXT,
    estimate_cost,
)
from core.validation import FHIR_DATE_RE, validate_fhir_date


def test_pricing_short_tier_flash():
    cost = estimate_cost("gemini-3.5-flash", 100_000, 0, 10_000)
    expected = (Decimal(100_000) * SHORT_CONTEXT["gemini-3.5-flash"]["input"]
                + Decimal(10_000) * SHORT_CONTEXT["gemini-3.5-flash"]["output"]) / Decimal(1_000_000)
    assert cost == expected.quantize(Decimal("0.000001"))


def test_pricing_cached_input_subtracted():
    cost = estimate_cost("gemini-3.5-flash", 100_000, 80_000, 0)
    rates = SHORT_CONTEXT["gemini-3.5-flash"]
    expected = (Decimal(20_000) * rates["input"]
                + Decimal(80_000) * rates["cached"]) / Decimal(1_000_000)
    assert cost == expected.quantize(Decimal("0.000001"))


def test_pricing_regional_uplift():
    base = estimate_cost("gemini-3.5-flash", 100_000, 0, 10_000)
    regional = estimate_cost("gemini-3.5-flash", 100_000, 0, 10_000, regional=True)
    assert regional == (base * REGIONAL_UPLIFT).quantize(Decimal("0.000001"))


def test_pricing_unknown_model_is_zero():
    assert estimate_cost("model-nonexistent", 1000, 0, 100) == Decimal("0")


def test_fhir_date_regex_accepts_all_three_precisions():
    assert FHIR_DATE_RE.match("2025")
    assert FHIR_DATE_RE.match("2025-10")
    assert FHIR_DATE_RE.match("2025-10-15")
    assert not FHIR_DATE_RE.match("10-15")
    assert not FHIR_DATE_RE.match("2025-10-15T00:00:00")


def test_validate_rejects_year_not_in_snippet():
    kept, reason = validate_fhir_date("1015-10-01", "catheterization (10/2025)", "2025-12-15")
    assert kept is None
    assert reason == "year_not_in_snippet"


def test_validate_rejects_drift_too_large():
    kept, reason = validate_fhir_date("1985-05-01", "seen in 1985", "2025-01-01")
    assert kept is None
    assert reason == "drift_gt_20y"


def test_validate_accepts_partial_date():
    kept, reason = validate_fhir_date("2025-10", "catheterization (10/2025)", "2025-12-15")
    assert kept == "2025-10"
    assert reason is None


def test_validate_passthrough_none():
    assert validate_fhir_date(None, "", None) == (None, None)


def test_record_call_no_active_run_is_noop():
    from core import telemetry

    async def run():
        await telemetry.record_call(
            stage="stage2",
            call_type="scan",
            model="gemini-3.5-flash",
            prompt_version="test",
            started_at=__import__("datetime").datetime.now(),
            finished_at=__import__("datetime").datetime.now(),
            usage={},
            status="ok",
            error=None,
            document_id=None,
        )

    asyncio.run(run())
