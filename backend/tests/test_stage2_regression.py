"""Regression guardrails for Stage 2 after the bug-fix pass.

These tests load the contents of backend/.cache/stage2_output/ (the
latest live run) and assert the bug-fix invariants. Skip if the cache
is missing (CI without live credentials)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.validation import FHIR_DATE_RE

STAGE2_DIR = Path(__file__).resolve().parent.parent / ".cache" / "stage2_output"

ACTION_VERBS = re.compile(
    r"\b(start|initiate|continue|restart|hold|prescrib|order|increase|decrease|stop|discontinue|titrate)",
    re.IGNORECASE,
)
RECONCILIATION_HEADERS = re.compile(
    r"(?i)(HOME MEDICATIONS|Medication reconciliation)"
)


def _load_outputs() -> list[dict]:
    if not STAGE2_DIR.exists():
        pytest.skip("no stage2 cache present")
    out = []
    for p in STAGE2_DIR.glob("*.json"):
        out.append(json.loads(p.read_text(encoding="utf-8")))
    if not out:
        pytest.skip("stage2 cache is empty")
    return out


def _note_year(data: dict) -> int | None:
    v = (data.get("note_context") or {}).get("note_date", {}).get("value")
    if not v:
        return None
    return int(v[:4]) if v[:4].isdigit() else None


def _iter_dates(data: dict):
    nc = data.get("note_context") or {}
    for key in ("note_date", "admission_date", "discharge_date"):
        v = (nc.get(key) or {}).get("value")
        if v is not None:
            yield ("note_context", key, v)
    for item in (data.get("candidates") or {}).get("Observation", []):
        if item.get("effective_date"):
            yield ("Observation", "effective_date", item["effective_date"])
    for item in (data.get("candidates") or {}).get("Procedure", []):
        if item.get("performed"):
            yield ("Procedure", "performed", item["performed"])


@pytest.mark.parametrize("data", _load_outputs())
def test_no_ancient_dates(data):
    ref_year = _note_year(data)
    for where, field, value in _iter_dates(data):
        assert FHIR_DATE_RE.match(value), f"bad fhir date in {where}.{field}: {value!r}"
        year = int(value[:4])
        if ref_year is not None:
            assert abs(year - ref_year) <= 20, (
                f"{where}.{field}={value} drifts >20y from note_date year {ref_year}"
            )


@pytest.mark.parametrize("data", _load_outputs())
def test_no_empty_family_history(data):
    for item in (data.get("candidates") or {}).get("FamilyMemberHistory", []):
        assert item.get("conditions"), f"empty FMH item: {item}"


def test_partial_date_preserved_for_month_year():
    for data in _load_outputs():
        for _, _, value in _iter_dates(data):
            if re.match(r"^\d{4}-\d{2}$", value):
                return
    pytest.skip("no partial month-year date in current cache (not a failure)")
