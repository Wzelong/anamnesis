"""Phase 2: deterministic primary/secondary cancer classification + profile selection."""
from __future__ import annotations

from core.augment.mcode import apply_specialty_profiles, classify_cancer_condition

MCODE = "http://hl7.org/fhir/us/mcode/StructureDefinition"
PRIMARY = f"{MCODE}/mcode-primary-cancer-condition"
SECONDARY = f"{MCODE}/mcode-secondary-cancer-condition"
CANDIDATES = [PRIMARY, SECONDARY]
SNOMED = "http://snomed.info/sct"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"


def _cond(display="", text="", system=SNOMED, code="1"):
    coding = [{"system": system, "code": code, "display": display}] if display else []
    return {"resourceType": "Condition", "code": {"coding": coding, "text": text}}


def test_primary_from_carcinoma():
    assert classify_cancer_condition(_cond("Infiltrating duct carcinoma of breast")) == "primary"


def test_secondary_from_metastatic_text():
    assert classify_cancer_condition(_cond("Metastatic carcinoma to liver")) == "secondary"


def test_secondary_from_icd10_c78():
    assert classify_cancer_condition(_cond("Secondary neoplasm", system=ICD10, code="C78.7")) == "secondary"


def test_non_cancer_is_none():
    assert classify_cancer_condition(_cond("Essential hypertension")) is None
    assert classify_cancer_condition(_cond("Benign nevus")) is None


def test_apply_attaches_primary_profile():
    out = apply_specialty_profiles(_cond("Ductal carcinoma in situ"), "Condition", CANDIDATES)
    assert out["meta"]["profile"] == [PRIMARY]


def test_apply_attaches_secondary_profile():
    out = apply_specialty_profiles(_cond("Metastatic melanoma"), "Condition", CANDIDATES)
    assert out["meta"]["profile"] == [SECONDARY]


def test_apply_noop_for_non_cancer():
    out = apply_specialty_profiles(_cond("Type 2 diabetes mellitus"), "Condition", CANDIDATES)
    assert "meta" not in out or not out["meta"].get("profile")


def test_apply_noop_without_candidates():
    out = apply_specialty_profiles(_cond("Carcinoma"), "Condition", [])
    assert "meta" not in out


def test_apply_preserves_existing_profiles():
    res = _cond("Carcinoma of breast")
    res["meta"] = {"profile": ["http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-problems-health-concerns"]}
    out = apply_specialty_profiles(res, "Condition", CANDIDATES)
    assert out["meta"]["profile"][-1] == PRIMARY and len(out["meta"]["profile"]) == 2


def test_apply_skips_non_condition_types():
    res = {"resourceType": "Observation", "code": {"text": "carcinoma marker"}}
    out = apply_specialty_profiles(res, "Observation", ["x/mcode-tumor-marker-test"])
    assert "meta" not in out


# -- cancer-related procedures + medications (reason-driven) ----------------

from core.effective_profile import resolve_effective_profile  # noqa: E402

_PRESET = {"id": "p", "ig": {"base": "us-core@6.1.0", "specialty": "mcode@4.0.0"}}


def _proc_cands():
    return resolve_effective_profile(_PRESET).rule("Procedure").candidate_profiles


def _med_cands():
    return resolve_effective_profile(_PRESET).rule("MedicationRequest").candidate_profiles


def test_surgical_procedure_with_cancer_reason_tagged():
    res = {"resourceType": "Procedure", "reasonCode": [{"text": "breast cancer"}]}
    out = apply_specialty_profiles(res, "Procedure", _proc_cands(), {"category": "surgical"})
    assert out["meta"]["profile"][-1].endswith("mcode-cancer-related-surgical-procedure")


def test_surgical_procedure_without_cancer_reason_not_tagged():
    res = {"resourceType": "Procedure", "reasonCode": [{"text": "diverticulitis"}]}
    assert apply_specialty_profiles(res, "Procedure", _proc_cands(), {"category": "surgical"}) == res


def test_diagnostic_procedure_with_cancer_reason_not_tagged():
    res = {"resourceType": "Procedure", "reasonCode": [{"text": "breast cancer"}]}
    assert apply_specialty_profiles(res, "Procedure", _proc_cands(), {"category": "diagnostic"}) == res


def test_medication_with_cancer_reason_tagged():
    res = {"resourceType": "MedicationRequest", "reasonCode": [{"text": "metastatic breast cancer"}]}
    out = apply_specialty_profiles(res, "MedicationRequest", _med_cands(), {})
    assert out["meta"]["profile"][-1].endswith("mcode-cancer-related-medication-request")


def test_medication_without_cancer_reason_not_tagged():
    res = {"resourceType": "MedicationRequest", "reasonCode": [{"text": "hypertension"}]}
    assert apply_specialty_profiles(res, "MedicationRequest", _med_cands(), {}) == res


# -- context-linking: surgical procedure tagged by cancer body-site overlap --

from core.augment.mcode import body_site_tokens  # noqa: E402


def test_body_site_tokens_drop_laterality():
    assert body_site_tokens({"bodySite": [{"text": "right testis"}]}) == {"testis"}
    assert body_site_tokens({"bodySite": [{"text": "right inguinal region"}]}) == {"inguinal"}


def test_surgery_tagged_by_site_overlap_without_reason():
    # orchiectomy (testis), no reason, but the run has a testis cancer -> tag
    res = {"resourceType": "Procedure", "bodySite": [{"text": "right testis"}]}
    out = apply_specialty_profiles(res, "Procedure", _proc_cands(), {"category": "surgical"}, {"testis"})
    assert out["meta"]["profile"][-1].endswith("mcode-cancer-related-surgical-procedure")


def test_unrelated_surgery_not_tagged_by_site():
    # inguinal hernia repair in a prostate-cancer patient -> NOT tagged (no organ overlap)
    res = {"resourceType": "Procedure", "bodySite": [{"text": "right inguinal region"}]}
    assert apply_specialty_profiles(res, "Procedure", _proc_cands(), {"category": "surgical"}, {"prostate"}) == res


def test_site_overlap_requires_surgical():
    res = {"resourceType": "Procedure", "bodySite": [{"text": "right testis"}]}
    assert apply_specialty_profiles(res, "Procedure", _proc_cands(), {"category": "diagnostic"}, {"testis"}) == res
