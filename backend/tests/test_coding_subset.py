"""Conformance Layer 3 (local): preset codeset allow-list enforcement."""
from fhir.coding_subset import check_coding_subset, code_allowed, primary_codings

SNOMED = "http://snomed.info/sct"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
RXNORM = "http://www.nlm.nih.gov/research/umls/rxnorm"
CPT = "http://www.ama-assn.org/go/cpt"


def _cond(system, code="1"):
    return {"resourceType": "Condition", "code": {"coding": [{"system": system, "code": code, "display": "x"}]}}


def test_primary_codings_condition():
    assert primary_codings(_cond(SNOMED))[0]["system"] == SNOMED


def test_primary_codings_medication_uses_medication_concept():
    r = {"resourceType": "MedicationRequest", "medicationCodeableConcept": {"coding": [{"system": RXNORM, "code": "1"}]}}
    assert primary_codings(r)[0]["system"] == RXNORM


def test_primary_codings_fmh_walks_conditions():
    r = {"resourceType": "FamilyMemberHistory", "condition": [{"code": {"coding": [{"system": SNOMED, "code": "1"}]}}]}
    assert primary_codings(r)[0]["system"] == SNOMED


def test_none_open_no_constraint():
    assert check_coding_subset(_cond(ICD10), None) == []


def test_open_system_passes():
    assert check_coding_subset(_cond(SNOMED), ["snomed"]) == []


def test_closed_system_flags_error():
    issues = check_coding_subset(_cond(ICD10), ["snomed"])
    assert len(issues) == 1
    assert issues[0]["severity"] == "error" and issues[0]["path"] == "Condition.code"


def test_empty_open_restricts_everything():
    assert len(check_coding_subset(_cond(ICD10), [])) == 1


def test_pinned_code_passes_despite_closed_system():
    assert check_coding_subset(_cond(CPT, "99213"), [], [{"system": CPT, "code": "99213"}]) == []


def test_multi_open_allowlist():
    assert check_coding_subset(_cond(ICD10), ["snomed", "icd10"]) == []


def test_structural_codings_not_gated():
    r = {
        "resourceType": "Condition",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": "c"}]}],
        "code": {"coding": [{"system": SNOMED, "code": "1"}]},
    }
    assert check_coding_subset(r, ["snomed"]) == []


def test_system_uris_are_single_source():
    from core.code_candidates import SYSTEM_URIS as canonical
    from fhir.coding_subset import SYSTEM_URIS as local
    assert local is canonical


def test_code_allowed_none_open_is_open():
    assert code_allowed(_cond(ICD10), None) is True


def test_code_allowed_open_system():
    assert code_allowed(_cond(SNOMED), ["snomed"]) is True


def test_code_allowed_closed_no_pin_is_blocked():
    assert code_allowed(_cond(SNOMED), []) is False


def test_code_allowed_pinned_match():
    pinned = [{"system": SNOMED, "code": "1"}, {"system": ICD10, "code": "E11"}]
    assert code_allowed(_cond(SNOMED, "1"), [], pinned) is True


def test_code_allowed_pinned_miss():
    pinned = [{"system": SNOMED, "code": "99"}]
    assert code_allowed(_cond(SNOMED, "1"), [], pinned) is False


def test_code_allowed_pinned_system_must_match():
    pinned = [{"system": ICD10, "code": "1"}]
    assert code_allowed(_cond(SNOMED, "1"), [], pinned) is False


def test_code_allowed_extend_open_plus_pin():
    pinned = [{"system": CPT, "code": "99213"}]
    assert code_allowed(_cond(SNOMED, "1"), ["snomed"], pinned) is True   # open system
    assert code_allowed(_cond(CPT, "99213"), ["snomed"], pinned) is True  # pinned
    assert code_allowed(_cond(ICD10, "1"), ["snomed"], pinned) is False   # neither
