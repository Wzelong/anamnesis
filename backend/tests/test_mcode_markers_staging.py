"""Phase 4: tumor markers (retrieved code + role tag) and TNM stage group (fixed-code)."""
from __future__ import annotations

from core.augment.builders import build_fhir_resource
from core.augment.mcode import apply_specialty_profiles
from core.code_candidates import _tag_mcode_roles, match_fixed
from core.effective_profile import resolve_effective_profile
from core.mcode_obs import is_tumor_marker, match_mcode_obs, match_tnm_category
from core.schemas import MergedCandidate

LOINC = "http://loinc.org"
MCODE = "http://hl7.org/fhir/us/mcode/StructureDefinition"
MCODE_PRESET = {"id": "p", "ig": {"base": "us-core@6.1.0", "specialty": "mcode@4.0.0"}}


def _cands():
    return resolve_effective_profile(MCODE_PRESET).rule("Observation").candidate_profiles


def _eff():
    return resolve_effective_profile(MCODE_PRESET)


# -- tumor marker recognition + tagging ------------------------------------

def test_is_tumor_marker():
    assert is_tumor_marker("ER")
    assert is_tumor_marker("estrogen receptor status")
    assert is_tumor_marker("HER2/neu")
    assert is_tumor_marker("alpha-fetoprotein")  # hyphen normalized to match "alpha fetoprotein"
    assert is_tumor_marker("choriogonadotropin, quantitative")  # hCG by full name
    assert is_tumor_marker("hCG")
    assert not is_tumor_marker("hemoglobin")
    assert not is_tumor_marker("performance")  # 'er' is mid-word, no match


def _obs_candidate(name, value, category="laboratory"):
    return MergedCandidate(resource_type="Observation",
                           item={"name": name, "full_name": name, "value": value, "category": category},
                           source_refs=[])


def test_tag_sets_role_when_active():
    out = _tag_mcode_roles(_obs_candidate("ER", "positive"), resolve_effective_profile(MCODE_PRESET))
    assert out.item["mcode_role"] == "tumor-marker" and out.item["codeset_hint"] == "LOINC"


def test_tag_noop_without_specialty():
    out = _tag_mcode_roles(_obs_candidate("ER", "positive"), resolve_effective_profile(None))
    assert "mcode_role" not in out.item


def test_tag_skips_fixed_code_obs():
    # ECOG is a fixed-code mCODE obs -> handled by match_fixed, not tumor-marker tagging
    out = _tag_mcode_roles(_obs_candidate("ECOG", "1"), resolve_effective_profile(MCODE_PRESET))
    assert "mcode_role" not in out.item


# -- tumor marker value + profile ------------------------------------------

def _build(item):
    return build_fhir_resource(MergedCandidate(resource_type="Observation", item=item, source_refs=[]), "pt", {})


def test_tumor_marker_posneg_is_codeable():
    res = _build({"name": "ER", "value": "positive", "coding": [{"system": LOINC, "code": "16112-5", "display": "Estrogen receptor"}],
                  "mcode_role": "tumor-marker", "category": "laboratory"})
    assert res["valueCodeableConcept"] == {"text": "positive"}


def test_tumor_marker_quantitative_is_quantity():
    res = _build({"name": "PSA", "value": "4.5", "unit": "ng/mL", "coding": [{"system": LOINC, "code": "2857-1", "display": "PSA"}],
                  "mcode_role": "tumor-marker", "category": "laboratory"})
    assert res["valueQuantity"]["value"] == 4.5 and res["valueQuantity"]["unit"] == "ng/mL"


def test_tumor_marker_numeric_without_unit_is_quantity():
    # AFP "1.6" with no unit should still be a Quantity, not a CodeableConcept or string.
    res = _build({"name": "alpha-fetoprotein", "value": "1.6",
                  "coding": [{"system": LOINC, "code": "111004-8", "display": "AFP"}], "mcode_role": "tumor-marker"})
    assert res["valueQuantity"] == {"value": 1.6} and "valueCodeableConcept" not in res


def test_tumor_marker_profile_selected():
    res = {"resourceType": "Observation", "code": {"coding": [{"system": LOINC, "code": "16112-5"}]}}
    out = apply_specialty_profiles(res, "Observation", _cands(), {"mcode_role": "tumor-marker"})
    assert out["meta"]["profile"] == [f"{MCODE}/mcode-tumor-marker-test"]


def test_tumor_marker_profile_skipped_without_role():
    res = {"resourceType": "Observation", "code": {"coding": [{"system": LOINC, "code": "16112-5"}]}}
    assert apply_specialty_profiles(res, "Observation", _cands(), {}) == res


# -- TNM stage group (fixed-code path) -------------------------------------

def test_stage_group_recognized_and_fixed():
    spec = match_mcode_obs("AJCC stage group")
    assert spec["code"] == "21908-9" and spec["profile"] == "tnm-stage-group"


def test_stage_group_value_codeable():
    res = _build({"name": "stage", "value": "IIA",
                  "coding": [{"system": LOINC, "code": "21908-9", "display": "Stage group.clinical Cancer"}], "category": "exam"})
    assert res["valueCodeableConcept"] == {"text": "IIA"}


def test_stage_group_profile_selected():
    res = {"resourceType": "Observation", "code": {"coding": [{"system": LOINC, "code": "21908-9"}]}}
    out = apply_specialty_profiles(res, "Observation", _cands())
    assert out["meta"]["profile"] == [f"{MCODE}/mcode-tnm-stage-group"]


# -- TNM categories (value-driven, clinical vs pathologic code) -------------

def test_tnm_category_clinical_vs_pathologic():
    assert match_tnm_category("T2") == [{"system": LOINC, "code": "21905-5", "display": "Primary tumor.clinical [Class] Cancer"}]
    assert match_tnm_category("pT3")[0]["code"] == "21899-0"  # pathologic primary tumor
    assert match_tnm_category("cN0")[0]["code"] == "21906-3"  # clinical regional nodes
    assert match_tnm_category("pM1")[0]["code"] == "21901-4"  # pathologic distant metastases
    assert match_tnm_category("NX")[0]["code"] == "21906-3"
    assert match_tnm_category("Tis")[0]["code"] == "21905-5"


def test_tnm_category_rejects_combined_and_stage_group():
    assert match_tnm_category("pT2N1M0") is None  # combined -> split upstream, not one category
    assert match_tnm_category("IIA") is None      # stage group, no T/N/M letter
    assert match_tnm_category("high grade") is None


def test_tnm_category_beats_stage_term_in_match_fixed():
    item = {"name": "primary tumor category", "value": "pT3"}
    assert match_fixed("Observation", item, _eff())[0]["code"] == "21899-0"


def test_tnm_category_value_codeable_and_profiled():
    res = _build({"name": "primary tumor category", "value": "pT3",
                  "coding": [{"system": LOINC, "code": "21899-0", "display": "Primary tumor.pathology [Class] Cancer"}], "category": "exam"})
    assert res["valueCodeableConcept"] == {"text": "pT3"}
    out = apply_specialty_profiles(res, "Observation", _cands(), {"name": "primary tumor category"})
    assert out["meta"]["profile"][-1] == f"{MCODE}/mcode-tnm-primary-tumor-category"
