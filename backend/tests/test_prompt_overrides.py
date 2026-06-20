"""Stage 2b-3: per-type prompt overrides resolve and bust the stage-2 cache."""
from __future__ import annotations

from types import SimpleNamespace

from core.effective_profile import resolve_effective_profile
from core.extraction import _note_cache_key, _override_digest, _resolve_prompts
from core.prompts import PROMPTS_BY_TYPE

_PRESET = {"id": "p", "prompts": {"Condition": {"active_version": 1, "versions": [
    {"version": 1, "text": "MY CONDITION PROMPT"}]}}}


def _note():
    return SimpleNamespace(original_text="some clinical note text")


def test_override_digest_empty_without_overrides():
    assert _override_digest(None) == ""
    assert _override_digest(resolve_effective_profile(None)) == ""


def test_override_digest_stable_and_nonempty():
    eff = resolve_effective_profile(_PRESET)
    assert _override_digest(eff) and _override_digest(eff) == _override_digest(eff)


def test_cache_key_unchanged_without_override():
    n = _note()
    assert _note_cache_key(n, "gemini") == _note_cache_key(n, "gemini", "")


def test_cache_key_busts_with_override():
    n = _note()
    eff = resolve_effective_profile(_PRESET)
    assert _note_cache_key(n, "gemini", _override_digest(eff)) != _note_cache_key(n, "gemini", "")


def test_resolve_prompts_default_uses_base():
    p = _resolve_prompts(resolve_effective_profile(None))
    assert p["Condition"] == PROMPTS_BY_TYPE["Condition"]


def test_resolve_prompts_applies_override():
    p = _resolve_prompts(resolve_effective_profile(_PRESET))
    assert p["Condition"] == "MY CONDITION PROMPT"
    assert p["Observation"] == PROMPTS_BY_TYPE["Observation"]
