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

# Canonical FHIR system URIs for the short names a preset's coding allow-list uses.
# Mirrors core.code_candidates.SYSTEM_URIS; kept local so the fhir layer stays free
# of the core/LLM import graph.
SYSTEM_URIS: dict[str, str] = {
    "snomed": "http://snomed.info/sct",
    "loinc": "http://loinc.org",
    "rxnorm": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "icd10": "http://hl7.org/fhir/sid/icd-10-cm",
}

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


def code_in_subset(resource: dict, subset: list[dict] | None) -> bool:
    """True if the resource's primary code is in the value-set scope (system+code match).

    Empty subset = no scope constraint -> True (regression-safe). Used to drop
    out-of-set resources when a preset scopes a type to a value set.
    """
    if not subset:
        return True
    allowed = {(c.get("system"), c.get("code")) for c in subset if c.get("system") and c.get("code")}
    if not allowed:
        return True
    return any((c.get("system"), c.get("code")) in allowed for c in primary_codings(resource))


def check_coding_subset(resource: dict, allowed_systems: list[str] | None) -> list[dict]:
    """Issues for primary codings whose `system` falls outside the preset allow-list.

    `allowed_systems` is short names (e.g. ["snomed", "icd10"]). None / empty means
    no preset constraint -> no issues (regression-safe for unconfigured clinicians).
    """
    if not allowed_systems:
        return []
    allowed_uris = {SYSTEM_URIS[s] for s in allowed_systems if s in SYSTEM_URIS}
    if not allowed_uris:
        return []
    rt = resource.get("resourceType")
    issues: list[dict] = []
    for coding in primary_codings(resource):
        system = coding.get("system")
        if system and system not in allowed_uris:
            issues.append({
                "severity": "error",
                "path": f"{rt}.code",
                "message": f"coding system {system} outside preset allow-list {sorted(allowed_uris)}",
            })
    return issues
