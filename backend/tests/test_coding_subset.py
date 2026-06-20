"""Conformance Layer 3 (local): preset coding-subset enforcement."""
from fhir.coding_subset import check_coding_subset, primary_codings

SNOMED = "http://snomed.info/sct"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"


def _cond(system):
    return {"resourceType": "Condition", "code": {"coding": [{"system": system, "code": "1", "display": "x"}]}}


def test_primary_codings_condition():
    assert primary_codings(_cond(SNOMED))[0]["system"] == SNOMED


def test_primary_codings_medication_uses_medication_concept():
    r = {"resourceType": "MedicationRequest", "medicationCodeableConcept": {"coding": [{"system": RXNORM, "code": "1"}]}}
    assert primary_codings(r)[0]["system"] == RXNORM


def test_primary_codings_fmh_walks_conditions():
    r = {"resourceType": "FamilyMemberHistory", "condition": [{"code": {"coding": [{"system": SNOMED, "code": "1"}]}}]}
    assert primary_codings(r)[0]["system"] == SNOMED


def test_no_allowlist_no_issues():
    assert check_coding_subset(_cond(ICD10), None) == []
    assert check_coding_subset(_cond(ICD10), []) == []


def test_allowed_system_passes():
    assert check_coding_subset(_cond(SNOMED), ["snomed"]) == []


def test_disallowed_system_flags_error():
    issues = check_coding_subset(_cond(ICD10), ["snomed"])
    assert len(issues) == 1
    assert issues[0]["severity"] == "error" and issues[0]["path"] == "Condition.code"


def test_multi_system_allowlist():
    assert check_coding_subset(_cond(ICD10), ["snomed", "icd10"]) == []


def test_unknown_allowlist_name_means_no_enforcement():
    assert check_coding_subset(_cond(ICD10), ["bogus"]) == []


def test_system_uris_mirror_code_candidates():
    from core.code_candidates import SYSTEM_URIS as canonical
    from fhir.coding_subset import SYSTEM_URIS as local
    assert local == canonical


def test_structural_codings_not_gated():
    r = {
        "resourceType": "Condition",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": "c"}]}],
        "code": {"coding": [{"system": SNOMED, "code": "1"}]},
    }
    assert check_coding_subset(r, ["snomed"]) == []
