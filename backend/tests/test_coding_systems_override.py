"""Stage 2b-4: preset coding-systems override changes stage-4 routing."""
from __future__ import annotations

from core.code_candidates import _extract_search_terms, _systems_override
from core.effective_profile import resolve_effective_profile


def _preset(coding: dict) -> dict:
    return {"id": "p", "coding": coding}


def test_no_override_is_none():
    assert _systems_override(None, "Condition") is None
    assert _systems_override(resolve_effective_profile(None), "Condition") is None


def test_override_returns_systems():
    eff = resolve_effective_profile(_preset({"Condition": {"systems": ["icd10"]}}))
    assert _systems_override(eff, "Condition") == ["icd10"]


def test_unknown_systems_filtered_out():
    eff = resolve_effective_profile(_preset({"Condition": {"systems": ["snomed", "icdo3"]}}))
    assert _systems_override(eff, "Condition") == ["snomed"]


def test_all_unknown_falls_back_to_none():
    eff = resolve_effective_profile(_preset({"Condition": {"systems": ["icdo3"]}}))
    assert _systems_override(eff, "Condition") is None


def test_condition_default_routing():
    terms = _extract_search_terms("Condition", {"name": "hypertension", "code_queries": ["hypertension"]})
    assert terms[0][2] == ["snomed", "icd10"]


def test_condition_override_routing():
    terms = _extract_search_terms("Condition", {"name": "hypertension"}, ["icd10"])
    assert terms[0][2] == ["icd10"]


def test_observation_override_beats_per_item_logic():
    item = {"name": "A1c", "codeset_hint": "LOINC"}
    assert _extract_search_terms("Observation", item)[0][2] == ["loinc"]          # default per-item
    assert _extract_search_terms("Observation", item, ["snomed"])[0][2] == ["snomed"]  # override wins
