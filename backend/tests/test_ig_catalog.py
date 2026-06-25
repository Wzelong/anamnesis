"""Backend reader for the shared IG catalog (single source of truth with frontend)."""
from __future__ import annotations

from core.ig_catalog import specialty_candidate_profiles

MCODE = "http://hl7.org/fhir/us/mcode/StructureDefinition"


def test_mcode_candidate_profiles():
    c = specialty_candidate_profiles("mcode@4.0.0")
    assert c["Condition"] == [f"{MCODE}/mcode-primary-cancer-condition", f"{MCODE}/mcode-secondary-cancer-condition"]
    assert c["MedicationRequest"] == [f"{MCODE}/mcode-cancer-related-medication-request"]
    assert "Observation" in c and "Procedure" in c


def test_unknown_and_none_specialty_empty():
    assert specialty_candidate_profiles(None) == {}
    assert specialty_candidate_profiles("nope@1.0.0") == {}
