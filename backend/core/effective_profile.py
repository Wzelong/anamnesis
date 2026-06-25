"""Effective profile: a run's active preset resolved into per-resource rules.

The pipeline reads the clinician's active preset (persisted in app_user.config)
and resolves it here into an EffectiveProfile that stages 2/4/6 consume. An
unconfigured clinician resolves to pure defaults — identical to no preset. The
IG catalog stays frontend-side; the backend applies only the explicit overrides
over its US Core baseline (see CONFORMANCE.md).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.augment.config import US_CORE_VERSION
from core.ig_catalog import fixed_codings, specialty_candidate_profiles
from core.schemas import RESOURCE_TYPES
from core.specialty_prompts import specialty_prompt_addons

DEFAULT_BASE_IG = f"us-core@{US_CORE_VERSION}"


@dataclass
class ResourceRule:
    enabled: bool = True
    profiles: list[str] = field(default_factory=list)     # overlay profiles to ADD unconditionally (base computed by builder)
    candidate_profiles: list[str] = field(default_factory=list)  # specialty IG profiles a builder may select among (one fits)
    coding_systems: list[str] | None = None               # OPEN systems: None=default all open, []=none, [..]=those
    pinned: list[dict] = field(default_factory=list)       # pinned codes (system,code,display), any system; additive
    fixed: list[dict] = field(default_factory=list)        # profile-fixed codings (catalog); read-only, always allowed
    code_overrides: list[dict] = field(default_factory=list)  # deterministic term->code maps ({match,system,code,display}); bypass retrieval
    extensions: list[dict] = field(default_factory=list)  # UserExtension declarations to apply
    prompt_override: str | None = None                    # add-only EXTRACT rules → stage-2 parse prompt
    capture_override: str | None = None                   # add-only CAPTURE rules → stage-2 scan routing
    specialty_prompt_addon: str | None = None             # specialty IG EXTRACT guidance (add-only, under user override)
    specialty_capture_addon: str | None = None            # specialty IG CAPTURE guidance (additive to scan block)


@dataclass
class EffectiveProfile:
    preset_id: str | None = None
    ig_base: str = DEFAULT_BASE_IG
    ig_specialty: str | None = None
    rules: dict[str, ResourceRule] = field(default_factory=dict)

    def rule(self, resource_type: str) -> ResourceRule:
        return self.rules.get(resource_type) or ResourceRule()


def _resolve_coding(cod: dict) -> tuple[list[str] | None, list[dict]]:
    """A type's coding override -> (open_systems, pinned_codes).

    open_systems: None=default all open, []=none open, [..]=those open.
    Migrates the pre-redesign `subset` key (restrict-only) to pinned + no open
    systems, preserving its original "only these codes" behavior.
    """
    def _codes(v) -> list[dict]:
        return [c for c in (v or []) if isinstance(c, dict)]

    if "codes" in cod:
        systems = cod["systems"] if isinstance(cod.get("systems"), list) else None
        return systems, _codes(cod.get("codes"))
    if cod.get("subset"):
        return [], _codes(cod.get("subset"))
    systems = cod["systems"] if isinstance(cod.get("systems"), list) else None
    return systems, []


def _active_prompt_text(override: dict | None) -> str | None:
    if not isinstance(override, dict):
        return None
    versions = override.get("versions") or []
    active = override.get("active_version")
    for v in versions:
        if isinstance(v, dict) and v.get("version") == active:
            return v.get("text")
    return versions[-1].get("text") if versions and isinstance(versions[-1], dict) else None


def resolve_effective_profile(preset: dict | None) -> EffectiveProfile:
    """Resolve a single preset object into an EffectiveProfile.

    `preset` is None / empty for an unconfigured clinician → pure defaults.
    """
    if not isinstance(preset, dict):
        return EffectiveProfile(rules={rt: ResourceRule(fixed=fixed_codings(DEFAULT_BASE_IG, None, rt)) for rt in RESOURCE_TYPES})

    ig = preset.get("ig") or {}
    resources = preset.get("resources") or {}
    coding = preset.get("coding") or {}
    prompts = preset.get("prompts") or {}
    capture_prompts = preset.get("capture_prompts") or {}
    extensions = preset.get("extensions") or []
    ig_base = ig.get("base") or DEFAULT_BASE_IG
    ig_specialty = ig.get("specialty")
    candidates = specialty_candidate_profiles(ig_specialty)
    addons = specialty_prompt_addons(ig_specialty)

    rules: dict[str, ResourceRule] = {}
    for rt in RESOURCE_TYPES:
        res = resources.get(rt) or {}
        cod = coding.get(rt) or {}
        coding_systems, pinned = _resolve_coding(cod)
        addon = addons.get(rt, {})
        rules[rt] = ResourceRule(
            enabled=bool(res.get("enabled", True)),
            candidate_profiles=candidates.get(rt, []),
            coding_systems=coding_systems,
            pinned=pinned,
            fixed=fixed_codings(ig_base, ig_specialty, rt),
            code_overrides=[o for o in (cod.get("code_overrides") or []) if isinstance(o, dict) and o.get("code")],
            extensions=[e for e in extensions if isinstance(e, dict) and e.get("attach_to") == rt],
            prompt_override=_active_prompt_text(prompts.get(rt)),
            capture_override=_active_prompt_text(capture_prompts.get(rt)),
            specialty_prompt_addon=addon.get("extract"),
            specialty_capture_addon=addon.get("capture"),
        )
    return EffectiveProfile(
        preset_id=preset.get("id"),
        ig_base=ig_base,
        ig_specialty=ig_specialty,
        rules=rules,
    )


def resolve_from_config(config: dict | None) -> EffectiveProfile:
    """Pick the clinician's active preset from app_user.config and resolve it."""
    if not isinstance(config, dict):
        return resolve_effective_profile(None)
    presets = [p for p in (config.get("presets") or []) if isinstance(p, dict)]
    active_id = config.get("active_preset_id")
    active = next((p for p in presets if p.get("id") == active_id), None)
    if active is None and presets:
        active = presets[0]
    return resolve_effective_profile(active)
