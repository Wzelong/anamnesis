"""Post-parse validators for Stage 2 output."""
from __future__ import annotations

import re

FHIR_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
_YEAR_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _year_of(value: str) -> int | None:
    if not value or len(value) < 4:
        return None
    head = value[:4]
    return int(head) if head.isdigit() else None


def _years_in(text: str) -> set[str]:
    return set(_YEAR_RE.findall(text))


def validate_fhir_date(
    value: str | None,
    snippet: str,
    note_date: str | None,
    *,
    max_drift_years: int = 20,
) -> tuple[str | None, str | None]:
    """Return (kept_value, reject_reason). kept_value is None on reject."""
    if value is None or value == "":
        return None, None
    if not FHIR_DATE_RE.match(value):
        return None, "bad_format"

    year_str = value[:4]
    if year_str not in _years_in(snippet):
        return None, "year_not_in_snippet"

    ref_year = _year_of(note_date) if note_date else None
    if ref_year is not None:
        try:
            if abs(int(year_str) - ref_year) > max_drift_years:
                return None, f"drift_gt_{max_drift_years}y"
        except ValueError:
            return None, "bad_year"

    return value, None
