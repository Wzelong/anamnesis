"""Phase 3: mCODE fixed-code observations — recognition, fixed code, value binding, profile."""
from __future__ import annotations

from core.augment.builders import build_fhir_resource
from core.augment.mcode import apply_specialty_profiles
from core.code_candidates import match_fixed
from core.effective_profile import resolve_effective_profile
from core.mcode_obs import match_mcode_obs, spec_for_codings
from core.schemas import MergedCandidate

LOINC = "http://loinc.org"
NCIT = "http://ncicb.nci.nih.gov/xml/owl/EVS/Thesaurus.owl"
MCODE = "http://hl7.org/fhir/us/mcode/StructureDefinition"
MCODE_PRESET = {"id": "p", "ig": {"base": "us-core@6.1.0", "specialty": "mcode@4.0.0"}}


def _eff():
    return resolve_effective_profile(MCODE_PRESET)


def test_match_recognizes_concepts():
    assert match_mcode_obs("ECOG performance status")["code"] == "89247-1"
    assert match_mcode_obs("Karnofsky")["code"] == "89243-0"
    assert match_mcode_obs("cancer disease status")["code"] == "97509-4"
    assert match_mcode_obs("histologic grade")["system"] == NCIT
    assert match_mcode_obs("blood pressure") is None


def test_match_fixed_gated_on_specialty():
    item = {"name": "ECOG performance status", "value": "1"}
    assert match_fixed("Observation", item, resolve_effective_profile(None)) is None
    assert match_fixed("Observation", item, _eff()) == [
        {"system": LOINC, "code": "89247-1", "display": "ECOG performance status"}]


def test_us_core_fixed_still_works_under_mcode():
    item = {"name": "blood pressure", "value": "120/80"}
    assert match_fixed("Observation", item, _eff())[0]["code"] == "85354-9"


def _obs(name, value, coding):
    item = {"name": name, "full_name": name, "value": value, "coding": coding, "category": "exam"}
    return MergedCandidate(resource_type="Observation", item=item, source_refs=[])


def test_builder_ecog_value_integer():
    res = build_fhir_resource(_obs("ECOG", "1", [{"system": LOINC, "code": "89247-1", "display": "ECOG performance status"}]), "pt", {})
    assert res["valueInteger"] == 1 and "valueString" not in res


def test_builder_grade_value_codeable():
    res = build_fhir_resource(_obs("histologic grade", "high grade", [{"system": NCIT, "code": "C18000", "display": "Grade"}]), "pt", {})
    assert res["valueCodeableConcept"] == {"text": "high grade"}


def test_builder_disease_status_codeable():
    res = build_fhir_resource(_obs("cancer disease status", "stable", [{"system": LOINC, "code": "97509-4", "display": "Cancer disease status"}]), "pt", {})
    assert res["valueCodeableConcept"] == {"text": "stable"}


def test_apply_attaches_ecog_profile():
    res = {"resourceType": "Observation", "code": {"coding": [{"system": LOINC, "code": "89247-1"}]}}
    cands = resolve_effective_profile(MCODE_PRESET).rule("Observation").candidate_profiles
    out = apply_specialty_profiles(res, "Observation", cands)
    assert out["meta"]["profile"] == [f"{MCODE}/mcode-ecog-performance-status"]


def test_apply_attaches_grade_profile():
    res = {"resourceType": "Observation", "code": {"coding": [{"system": NCIT, "code": "C18000"}]}}
    cands = resolve_effective_profile(MCODE_PRESET).rule("Observation").candidate_profiles
    out = apply_specialty_profiles(res, "Observation", cands)
    assert out["meta"]["profile"] == [f"{MCODE}/mcode-histologic-grade"]


def test_apply_noop_for_unknown_observation():
    res = {"resourceType": "Observation", "code": {"coding": [{"system": LOINC, "code": "9999-9"}]}}
    cands = resolve_effective_profile(MCODE_PRESET).rule("Observation").candidate_profiles
    assert apply_specialty_profiles(res, "Observation", cands) == res


def test_tumor_size_recognized_value_quantity_profiled():
    assert match_mcode_obs("tumor greatest dimension")["code"] == "21889-1"
    res = build_fhir_resource(MergedCandidate(resource_type="Observation", source_refs=[], item={
        "name": "tumor size", "value": "3.5", "unit": "cm",
        "coding": [{"system": LOINC, "code": "21889-1", "display": "Size.maximum dimension Tumor"}],
        "category": "exam"}), "pt", {})
    assert res["valueQuantity"] == {"value": 3.5, "unit": "cm", "system": "http://unitsofmeasure.org", "code": "cm"}
    cands = resolve_effective_profile(MCODE_PRESET).rule("Observation").candidate_profiles
    out = apply_specialty_profiles({"resourceType": "Observation", "code": {"coding": [{"system": LOINC, "code": "21889-1"}]}}, "Observation", cands)
    assert out["meta"]["profile"] == [f"{MCODE}/mcode-tumor-size"]


def test_spec_for_codings_roundtrip():
    assert spec_for_codings([{"system": LOINC, "code": "89243-0"}])["profile"] == "karnofsky-performance-status"
    assert spec_for_codings([{"system": LOINC, "code": "1234-5"}]) is None
