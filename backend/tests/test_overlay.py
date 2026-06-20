"""Stage 2b-5: effective-profile overlay — meta.profile list + extensions (guardrails 1, 3)."""
from __future__ import annotations

from core.augment.overlay import apply_overlay, build_extension
from core.effective_profile import ResourceRule, resolve_effective_profile
from fhir.validate import validate_r4

US_CORE_COND = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-problems-health-concerns"
MCODE_COND = "http://hl7.org/fhir/us/mcode/StructureDefinition/mcode-primary-cancer-condition"


def _condition() -> dict:
    return {
        "resourceType": "Condition",
        "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
        "code": {"text": "Hypertension"},
        "subject": {"reference": "Patient/x"},
        "meta": {"profile": [US_CORE_COND]},
    }


def test_noop_for_default_rule():
    out = apply_overlay(_condition(), resolve_effective_profile(None).rule("Condition"))
    assert out["meta"]["profile"] == [US_CORE_COND]
    assert "extension" not in out


def test_merges_profiles_as_list_and_valid():
    out = apply_overlay(_condition(), ResourceRule(profiles=[MCODE_COND]))
    assert out["meta"]["profile"] == [US_CORE_COND, MCODE_COND]
    assert validate_r4(out).valid


def test_dedups_existing_profile():
    out = apply_overlay(_condition(), ResourceRule(profiles=[US_CORE_COND]))
    assert out["meta"]["profile"] == [US_CORE_COND]


def test_extension_without_value_not_stamped():
    out = apply_overlay(_condition(), ResourceRule(extensions=[{"url": "http://x/ext", "datatype": "string"}]))
    assert "extension" not in out


def test_extension_with_value_stamped_and_valid():
    rule = ResourceRule(extensions=[{"url": "http://x/eye-color", "datatype": "string", "value": "blue"}])
    out = apply_overlay(_condition(), rule)
    assert out["extension"] == [{"url": "http://x/eye-color", "valueString": "blue"}]
    assert validate_r4(out).valid


def test_build_extension_datatypes():
    assert build_extension({"url": "u", "datatype": "boolean"}, True) == {"url": "u", "valueBoolean": True}
    assert build_extension({"url": "u", "datatype": "integer"}, 3) == {"url": "u", "valueInteger": 3}
    assert build_extension({"url": "u", "datatype": "CodeableConcept"}, "x") == {"url": "u", "valueCodeableConcept": {"text": "x"}}
    assert build_extension({"url": "u", "datatype": "unknown"}, "x") is None
    assert build_extension({"datatype": "string"}, "x") is None  # missing url
