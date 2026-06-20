"""Conformance Layer 1: base FHIR R4 structural validation (CONFORMANCE.md)."""
from __future__ import annotations

import json
import pathlib

from fhir.validate import validate_r4

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
DEMO_PROPOSALS = REPO_ROOT / "mcp-app" / "src" / "demo" / "proposals.json"


def _condition() -> dict:
    return {
        "resourceType": "Condition",
        "clinicalStatus": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-clinical", "code": "active"}]},
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/condition-category", "code": "problem-list-item"}]}],
        "code": {"text": "Hypertension"},
        "subject": {"reference": "Patient/x"},
    }


def test_valid_resource_passes():
    result = validate_r4(_condition())
    assert result.valid
    assert result.issues == []
    assert result.to_dict() == {"valid": True, "level": "r4", "issues": []}


def test_missing_resource_type():
    result = validate_r4({"code": {"text": "x"}})
    assert not result.valid
    assert any(i.path == "resourceType" for i in result.issues)


def test_unknown_resource_type():
    result = validate_r4({"resourceType": "Nonsense"})
    assert not result.valid
    assert "unknown resource type" in result.issues[0].message


def test_wrong_field_type_fails():
    bad = _condition() | {"subject": "Patient/x"}  # Reference must be an object, not a string
    result = validate_r4(bad)
    assert not result.valid
    assert any(i.path.startswith("subject") for i in result.issues)


def test_extra_field_rejected():
    result = validate_r4(_condition() | {"notAFhirField": True})
    assert not result.valid
    assert any("Extra" in i.message for i in result.issues)


def test_family_member_history_base_fhir_valid():
    # US Core 6.1.0 has no FMH profile; base FHIR FamilyMemberHistory must validate.
    fmh = {
        "resourceType": "FamilyMemberHistory",
        "status": "completed",
        "patient": {"reference": "Patient/x"},
        "relationship": {"text": "father"},
    }
    assert validate_r4(fmh).valid


def test_all_demo_proposals_validate_clean():
    proposals = json.loads(DEMO_PROPOSALS.read_text())["proposals"]
    assert proposals, "demo proposals fixture is empty"
    invalid = [
        (p["resource"].get("resourceType"), p.get("id"), validate_r4(p["resource"]).issues)
        for p in proposals
        if not validate_r4(p["resource"]).valid
    ]
    assert invalid == [], f"{len(invalid)} demo resources failed R4 validation: {invalid[:3]}"
