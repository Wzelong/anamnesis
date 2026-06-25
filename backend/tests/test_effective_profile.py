"""Stage 2b-1: resolve a preset into an EffectiveProfile (defaults = no preset)."""
from __future__ import annotations

from core.effective_profile import resolve_effective_profile, resolve_from_config
from core.schemas import RESOURCE_TYPES


def test_none_preset_is_pure_defaults():
    ep = resolve_effective_profile(None)
    assert ep.preset_id is None and ep.ig_specialty is None
    for rt in RESOURCE_TYPES:
        r = ep.rule(rt)
        assert r.enabled and r.coding_systems is None and r.prompt_override is None and r.extensions == []


def test_unknown_type_defaults():
    ep = resolve_effective_profile({"id": "p1", "resources": {}})
    assert ep.rule("NotAResourceType").enabled is True


def test_overrides_applied():
    preset = {
        "id": "p1",
        "ig": {"base": "us-core@6.1.0", "specialty": "mcode@4.0.0"},
        "resources": {"Procedure": {"enabled": False}},
        "coding": {"Condition": {"systems": ["snomed", "icd10"]}},
        "prompts": {"Observation": {"active_version": 2, "versions": [
            {"version": 1, "text": "old"}, {"version": 2, "text": "new prompt"}]}},
        "extensions": [{"id": "e1", "attach_to": "Condition", "url": "u", "datatype": "string", "name": "x"}],
    }
    ep = resolve_effective_profile(preset)
    assert ep.preset_id == "p1" and ep.ig_specialty == "mcode@4.0.0"
    assert ep.rule("Procedure").enabled is False
    assert ep.rule("Condition").coding_systems == ["snomed", "icd10"]
    assert ep.rule("Observation").prompt_override == "new prompt"
    assert ep.rule("Condition").extensions[0]["id"] == "e1"
    assert ep.rule("MedicationRequest").enabled is True  # untouched default


def test_active_prompt_falls_back_to_last_version():
    preset = {"id": "p", "prompts": {"Condition": {"active_version": 9, "versions": [
        {"version": 1, "text": "v1"}, {"version": 2, "text": "v2"}]}}}
    assert resolve_effective_profile(preset).rule("Condition").prompt_override == "v2"


def test_resolve_from_config_picks_active():
    cfg = {"active_preset_id": "b", "presets": [
        {"id": "a", "resources": {"Procedure": {"enabled": False}}},
        {"id": "b", "resources": {"Condition": {"enabled": False}}}]}
    ep = resolve_from_config(cfg)
    assert ep.preset_id == "b"
    assert ep.rule("Condition").enabled is False
    assert ep.rule("Procedure").enabled is True


def test_resolve_from_config_empty_is_defaults():
    ep = resolve_from_config({})
    assert ep.preset_id is None and ep.rule("Condition").enabled is True


def test_specialty_populates_candidate_profiles():
    preset = {"id": "p", "ig": {"base": "us-core@6.1.0", "specialty": "mcode@4.0.0"}}
    ep = resolve_effective_profile(preset)
    assert ep.rule("Condition").candidate_profiles[0].endswith("mcode-primary-cancer-condition")
    assert ep.rule("Condition").profiles == []  # candidates are not blanket-attached
    assert ep.rule("FamilyMemberHistory").candidate_profiles == []  # absent from mcode manifest


def test_no_specialty_has_no_candidate_profiles():
    ep = resolve_effective_profile({"id": "p", "ig": {"base": "us-core@6.1.0", "specialty": None}})
    assert all(ep.rule(rt).candidate_profiles == [] for rt in RESOURCE_TYPES)
