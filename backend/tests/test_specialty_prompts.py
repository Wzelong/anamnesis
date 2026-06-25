"""Phase 5: specialty IG prompt addons compose into stage-2 capture + extract."""
from __future__ import annotations

from core.effective_profile import resolve_effective_profile
from core.extraction import _override_digest, _resolve_prompts, compose_scan_prompt
from core.prompts import PROMPT_SCAN, PROMPTS_BY_TYPE
from core.specialty_prompts import specialty_prompt_addons

MCODE_PRESET = {"id": "p", "ig": {"base": "us-core@6.1.0", "specialty": "mcode@4.0.0"}}
_USER_PRESET = {
    "id": "p", "ig": {"base": "us-core@6.1.0", "specialty": "mcode@4.0.0"},
    "prompts": {"Condition": {"active_version": 1, "versions": [{"version": 1, "text": "MY CONDITION RULE"}]}},
}


def test_addons_registry():
    a = specialty_prompt_addons("mcode@4.0.0")
    assert "extract" in a["Condition"] and "capture" in a["Observation"]
    assert specialty_prompt_addons(None) == {} and specialty_prompt_addons("nope") == {}


def test_bridge_populates_rule():
    eff = resolve_effective_profile(MCODE_PRESET)
    assert "metastatic" in eff.rule("Condition").specialty_prompt_addon
    assert eff.rule("Observation").specialty_capture_addon
    assert eff.rule("Condition").specialty_capture_addon is None


def test_no_specialty_leaves_rule_empty():
    eff = resolve_effective_profile({"id": "p"})
    assert eff.rule("Condition").specialty_prompt_addon is None


# -- extract lane -----------------------------------------------------------

def test_extract_unchanged_without_specialty():
    p = _resolve_prompts(resolve_effective_profile({"id": "p"}))
    assert p["Condition"] == PROMPTS_BY_TYPE["Condition"]


def test_extract_appends_specialty_addon():
    p = _resolve_prompts(resolve_effective_profile(MCODE_PRESET))
    assert p["Condition"].startswith(PROMPTS_BY_TYPE["Condition"])
    assert "Specialty IG additions" in p["Condition"] and "metastatic" in p["Condition"]
    assert "ECOG performance status" in p["Observation"]


def test_user_override_layers_on_top_of_specialty():
    p = _resolve_prompts(resolve_effective_profile(_USER_PRESET))["Condition"]
    # specialty addon comes first, the clinician's own rule is appended after it
    assert p.index("Specialty IG additions") < p.index("MY CONDITION RULE")


# -- capture lane -----------------------------------------------------------

def test_capture_unchanged_without_specialty():
    assert compose_scan_prompt(PROMPT_SCAN, resolve_effective_profile({"id": "p"})) == PROMPT_SCAN


def test_capture_appends_inside_observation_block():
    out = compose_scan_prompt(PROMPT_SCAN, resolve_effective_profile(MCODE_PRESET))
    assert "HER2 negative" in out
    # appended inside the Observation block, before its closing tag
    obs_block = out.split('<resource name="Observation">')[1].split("</resource>")[0]
    assert "HER2 negative" in obs_block
    # Condition block untouched (no capture addon for Condition)
    cond_block = out.split('<resource name="Condition">')[1].split("</resource>")[0]
    assert "HER2 negative" not in cond_block


# -- cache digest -----------------------------------------------------------

def test_digest_distinguishes_specialty():
    base = _override_digest(resolve_effective_profile({"id": "p"}))
    mcode = _override_digest(resolve_effective_profile(MCODE_PRESET))
    assert base == "" and mcode and mcode != base
