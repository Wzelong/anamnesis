"""Stage 2: specific US Core vital-sign profiles, routed by LOINC, valid R4."""
from __future__ import annotations

import pytest

from core.augment.builders import _build_observation
from fhir.validate import validate_r4

LOINC = "http://loinc.org"
BASE = "http://hl7.org/fhir/us/core/StructureDefinition"


def _vital(code: str, display: str, value: str, unit: str, cat: str = "vital-signs") -> dict:
    return _build_observation(
        {"name": display, "value": value, "unit": unit, "category": cat,
         "coding": [{"system": LOINC, "code": code, "display": display}]},
        "pt1", None, note_date="2026-06-01",
    )


@pytest.mark.parametrize("code,display,value,unit,profile", [
    ("8867-4", "Heart rate", "72", "bpm", "us-core-heart-rate"),
    ("9279-1", "Respiratory rate", "16", "breaths/min", "us-core-respiratory-rate"),
    ("8310-5", "Body temperature", "38.1", "Cel", "us-core-body-temperature"),
    ("29463-7", "Body weight", "80", "kg", "us-core-body-weight"),
    ("8302-2", "Body height", "175", "cm", "us-core-body-height"),
    ("39156-5", "Body mass index", "26.1", "kg/m2", "us-core-bmi"),
    ("59408-5", "Oxygen saturation by pulse oximetry", "98", "%", "us-core-pulse-oximetry"),
    ("9843-4", "Head circumference", "55", "cm", "us-core-head-circumference"),
])
def test_specific_vital_profile_and_valid(code, display, value, unit, profile):
    r = _vital(code, display, value, unit)
    assert r["meta"]["profile"] == [f"{BASE}/{profile}"]
    assert validate_r4(r).valid


def test_non_vital_lab_falls_back_to_category_profile():
    r = _build_observation(
        {"name": "Ferritin", "value": "210", "unit": "ng/mL", "category": "laboratory",
         "coding": [{"system": LOINC, "code": "2276-4", "display": "Ferritin"}]},
        "pt1", None, note_date="2026-06-01",
    )
    assert r["meta"]["profile"] == [f"{BASE}/us-core-observation-lab"]
    assert validate_r4(r).valid
