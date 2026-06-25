"""Conformance Layer 3 (local): preset coding-subset enforcement (see CONFORMANCE.md).

A preset can pin which terminology systems a resource type's primary clinical code
may draw from (`EffectiveProfile.rule(rt).coding_systems`). This checks the built
resource's primary code against that allow-list locally, no network. The
authoritative value-set membership check (`$validate-code` against a dedicated
validator) is L3-remote, deferred until value-set bindings are authored.

Only the primary clinical code is gated. Structural codings (category, status,
relationship, units) are builder-fixed and never subject to the preset allow-list.
"""
from __future__ import annotations

# core.systems is pure data (no LLM/heavy imports), so the fhir layer can share the
# single source of truth for system URIs without dragging in the core graph.
from core.systems import SYSTEM_URIS

_PRIMARY_CODE_KEY: dict[str, str] = {
    "Condition": "code",
    "Procedure": "code",
    "AllergyIntolerance": "code",
    "Observation": "code",
    "MedicationRequest": "medicationCodeableConcept",
}


def _codings(concept: dict | None) -> list[dict]:
    return (concept or {}).get("coding") or []


def primary_codings(resource: dict) -> list[dict]:
    """The resource's primary clinical-concept codings (the element a preset gates)."""
    rt = resource.get("resourceType")
    if rt == "FamilyMemberHistory":
        out: list[dict] = []
        for cond in resource.get("condition") or []:
            out.extend(_codings(cond.get("code")))
        return out
    key = _PRIMARY_CODE_KEY.get(rt or "")
    return _codings(resource.get(key)) if key else []


def _open_uris(open_systems: list[str] | None) -> set[str] | None:
    """None = no constraint (default all open). Else the open systems' URIs."""
    if open_systems is None:
        return None
    return {SYSTEM_URIS[s] for s in open_systems if s in SYSTEM_URIS}


def _pinned_keys(pinned: list[dict] | None) -> set[tuple]:
    return {(c.get("system"), c.get("code")) for c in (pinned or []) if c.get("system") and c.get("code")}


def code_allowed(
    resource: dict, open_systems: list[str] | None,
    pinned: list[dict] | None = None, fixed: list[dict] | None = None,
) -> bool:
    """True if a primary code is permitted: its system is OPEN, or the exact
    (system, code) is pinned or profile-fixed. `open_systems` None = no constraint
    (regression-safe). A resource with no codeable primary code is not gated.
    """
    open_uris = _open_uris(open_systems)
    if open_uris is None and not pinned and not fixed:
        return True
    pins = _pinned_keys(pinned) | _pinned_keys(fixed)
    codings = primary_codings(resource)
    if not codings:
        return True
    for c in codings:
        system = c.get("system")
        if open_uris is None or system in open_uris:
            return True
        if (system, c.get("code")) in pins:
            return True
    return False


def check_coding_subset(
    resource: dict, open_systems: list[str] | None,
    pinned: list[dict] | None = None, fixed: list[dict] | None = None,
) -> list[dict]:
    """Issues for primary codings outside the preset allow-list: system not OPEN and
    code neither pinned nor profile-fixed. `open_systems` None = no constraint.
    """
    open_uris = _open_uris(open_systems)
    if open_uris is None:
        return []
    pins = _pinned_keys(pinned) | _pinned_keys(fixed)
    rt = resource.get("resourceType")
    issues: list[dict] = []
    for coding in primary_codings(resource):
        system = coding.get("system")
        if system and system not in open_uris and (system, coding.get("code")) not in pins:
            issues.append({
                "severity": "error",
                "path": f"{rt}.code",
                "message": f"coding {system}|{coding.get('code')} outside preset allow-list",
            })
    return issues
