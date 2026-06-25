"""Stage 4 routing: preset codeset resolves to open systems + pinned codes."""
from __future__ import annotations

from core.code_candidates import _extract_search_terms, _resolve_coding, _systems_for, match_fixed
from core.effective_profile import resolve_effective_profile

SNOMED = "http://snomed.info/sct"
CPT = "http://www.ama-assn.org/go/cpt"


def _preset(coding: dict) -> dict:
    return {"id": "p", "coding": coding}


def test_default_open_systems():
    open_sys, pinned = _resolve_coding(None, "Condition", {})
    assert open_sys == ["snomed", "icd10"] and pinned == {}
    eff = resolve_effective_profile(None)
    assert _resolve_coding(eff, "Condition", {})[0] == ["snomed", "icd10"]


def test_open_systems_from_preset():
    eff = resolve_effective_profile(_preset({"Condition": {"systems": ["icd10"]}}))
    assert _resolve_coding(eff, "Condition", {})[0] == ["icd10"]


def test_non_retrievable_systems_cannot_be_open():
    eff = resolve_effective_profile(_preset({"Condition": {"systems": ["snomed", "icdo3"]}}))
    assert _resolve_coding(eff, "Condition", {})[0] == ["snomed"]


def test_empty_open_systems_restricts():
    eff = resolve_effective_profile(_preset({"Condition": {"systems": []}}))
    assert _resolve_coding(eff, "Condition", {})[0] == []


def test_pinned_codes_grouped_by_system():
    eff = resolve_effective_profile(_preset({"Procedure": {
        "systems": ["snomed"],
        "codes": [{"system": CPT, "code": "99213", "display": "office visit"}],
    }}))
    open_sys, pinned = _resolve_coding(eff, "Procedure", {})
    assert open_sys == ["snomed"]
    assert list(pinned) == ["cpt"] and pinned["cpt"][0]["code"] == "99213"


def test_legacy_subset_migrates_to_restrict():
    eff = resolve_effective_profile(_preset({"Condition": {"subset": [{"system": SNOMED, "code": "1"}]}}))
    open_sys, pinned = _resolve_coding(eff, "Condition", {})
    assert open_sys == [] and list(pinned) == ["snomed"]


def test_systems_for_unions_pinned():
    assert _systems_for("Procedure", ["snomed"], {"cpt": [{}]}) == ["snomed", "cpt"]


def test_systems_for_bespoke_ignores_pins():
    assert _systems_for("AllergyIntolerance", ["snomed"], {"cpt": [{}]}) == ["snomed"]


def test_extract_search_terms_uses_open_systems():
    terms = _extract_search_terms("Condition", {"name": "hypertension", "code_queries": ["hypertension"]}, ["icd10"])
    assert terms[0] == ("code", "hypertension", ["hypertension"], ["icd10"])


def test_observation_default_routing_per_item():
    item = {"name": "A1c", "codeset_hint": "LOINC"}
    assert _resolve_coding(None, "Observation", item)[0] == ["loinc"]


# -- deterministic term->code overrides ------------------------------------

_OVERRIDE = {"id": "p", "coding": {"Condition": {"code_overrides": [
    {"match": "diabetes", "system": SNOMED, "code": "44054006", "display": "Diabetes mellitus type 2"}]}}}


def test_code_override_matches_substring():
    eff = resolve_effective_profile(_OVERRIDE)
    assert match_fixed("Condition", {"name": "type 2 diabetes mellitus"}, eff) == [
        {"system": SNOMED, "code": "44054006", "display": "Diabetes mellitus type 2"}]


def test_code_override_no_match_falls_through():
    eff = resolve_effective_profile(_OVERRIDE)
    assert match_fixed("Condition", {"name": "hypertension"}, eff) is None


def test_code_override_absent_without_preset():
    assert match_fixed("Condition", {"name": "diabetes"}, resolve_effective_profile(None)) is None
