"""Add-only prompt composition: addon appends to the validated base, never replaces."""
from core.effective_profile import resolve_effective_profile
from core.extraction import ADDON_HEADER, _resolve_prompts, compose_prompt
from core.prompts import PROMPTS_BY_TYPE


def test_compose_empty_returns_base():
    assert compose_prompt("BASE", "") == "BASE"
    assert compose_prompt("BASE", None) == "BASE"
    assert compose_prompt("BASE", "   ") == "BASE"


def test_compose_appends_addon():
    out = compose_prompt("BASE", "record stage separately")
    assert out.startswith("BASE")
    assert ADDON_HEADER in out
    assert "record stage separately" in out


def test_resolve_appends_only_for_active_type():
    eff = resolve_effective_profile(
        {"prompts": {"Condition": {"active_version": 1, "versions": [{"version": 1, "text": "my rule"}]}}}
    )
    prompts = _resolve_prompts(eff)
    assert prompts["Condition"].startswith(PROMPTS_BY_TYPE["Condition"])
    assert "my rule" in prompts["Condition"]
    assert ADDON_HEADER not in prompts["Procedure"]  # untouched types stay base-only


def test_resolve_none_is_all_base():
    prompts = _resolve_prompts(None)
    assert prompts["Condition"] == PROMPTS_BY_TYPE["Condition"]
