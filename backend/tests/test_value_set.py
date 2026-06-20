"""Lane B parse helpers: supported-system filtering (LLM + grounding are integration)."""
from core.value_set import SUPPORTED_SYSTEMS, _supported


def test_supported_filters_unknown_and_empty():
    codes = [
        {"system": "http://snomed.info/sct", "code": "44054006"},
        {"system": "http://example.org/foo", "code": "2"},
        {"system": "http://loinc.org", "code": ""},
        {"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": "E11.9", "display": "x"},
    ]
    assert [c["code"] for c in _supported(codes)] == ["44054006", "E11.9"]


def test_supported_systems_uris():
    assert SUPPORTED_SYSTEMS["snomed"] == "http://snomed.info/sct"
    assert SUPPORTED_SYSTEMS["icd10"] == "http://hl7.org/fhir/sid/icd-10-cm"
