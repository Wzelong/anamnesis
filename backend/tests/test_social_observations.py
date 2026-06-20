"""Stage 2a: social/SDOH Observations route to US Core profiles and stay valid R4."""
from __future__ import annotations

from core.augment.builders import _build_observation
from core.code_candidates import match_us_core_fixed
from fhir.validate import validate_r4

LOINC = "http://loinc.org"
OCCUPATION = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-occupation"
SEXUAL_ORIENTATION = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-sexual-orientation"
SIMPLE = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-simple-observation"


def _build(item: dict) -> dict:
    return _build_observation(item, "pt1", None, note_date="2026-06-01")


def test_occupation_fixed_loinc():
    assert match_us_core_fixed("Observation", {"name": "occupation"}) == [
        {"system": LOINC, "code": "11341-5", "display": "History of Occupation"}
    ]


def test_sexual_orientation_fixed_loinc():
    assert match_us_core_fixed("Observation", {"name": "sexual orientation"})[0]["code"] == "76690-7"


def test_occupation_observation_profiled_and_valid():
    r = _build({"name": "occupation", "value": "welder", "category": "social-history",
                "coding": [{"system": LOINC, "code": "11341-5", "display": "History of Occupation"}]})
    assert r["meta"]["profile"] == [OCCUPATION]
    assert validate_r4(r).valid


def test_sexual_orientation_observation_profiled_and_valid():
    r = _build({"name": "sexual orientation", "value": "gay", "category": "social-history",
                "coding": [{"system": LOINC, "code": "76690-7", "display": "Sexual orientation"}]})
    assert r["meta"]["profile"] == [SEXUAL_ORIENTATION]
    assert validate_r4(r).valid


def test_alcohol_use_falls_back_to_simple_observation():
    r = _build({"name": "alcohol use", "value": "3-4 beers on weekends",
                "category": "social-history", "coding": []})
    assert r["meta"]["profile"] == [SIMPLE]
    assert validate_r4(r).valid
