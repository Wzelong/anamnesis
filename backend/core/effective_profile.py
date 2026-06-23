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
from core.schemas import RESOURCE_TYPES

DEFAULT_BASE_IG = f"us-core@{US_CORE_VERSION}"


@dataclass
class ResourceRule:
    enabled: bool = True
    profiles: list[str] = field(default_factory=list)     # overlay profiles to ADD (base computed by builder)
    coding_systems: list[str] | None = None               # None = backend default routing
    code_subset: list[dict] = field(default_factory=list)  # value-set scope: only these (system,code) survive
    extensions: list[dict] = field(default_factory=list)  # UserExtension declarations to apply
    prompt_override: str | None = None                    # add-only EXTRACT rules → stage-2 parse prompt
    capture_override: str | None = None                   # add-only CAPTURE rules → stage-2 scan routing


@dataclass
class EffectiveProfile:
    preset_id: str | None = None
    ig_base: str = DEFAULT_BASE_IG
    ig_specialty: str | None = None
    rules: dict[str, ResourceRule] = field(default_factory=dict)

    def rule(self, resource_type: str) -> ResourceRule:
        return self.rules.get(resource_type) or ResourceRule()


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
        return EffectiveProfile(rules={rt: ResourceRule() for rt in RESOURCE_TYPES})

    ig = preset.get("ig") or {}
    resources = preset.get("resources") or {}
    coding = preset.get("coding") or {}
    prompts = preset.get("prompts") or {}
    capture_prompts = preset.get("capture_prompts") or {}
    extensions = preset.get("extensions") or []

    rules: dict[str, ResourceRule] = {}
    for rt in RESOURCE_TYPES:
        res = resources.get(rt) or {}
        cod = coding.get(rt) or {}
        rules[rt] = ResourceRule(
            enabled=bool(res.get("enabled", True)),
            coding_systems=(cod.get("systems") or None),
            code_subset=[c for c in (cod.get("subset") or []) if isinstance(c, dict)],
            extensions=[e for e in extensions if isinstance(e, dict) and e.get("attach_to") == rt],
            prompt_override=_active_prompt_text(prompts.get(rt)),
            capture_override=_active_prompt_text(capture_prompts.get(rt)),
        )
    return EffectiveProfile(
        preset_id=preset.get("id"),
        ig_base=ig.get("base") or DEFAULT_BASE_IG,
        ig_specialty=ig.get("specialty"),
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
