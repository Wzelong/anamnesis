"""Effective-profile overlay applied to a built resource (CONFORMANCE.md guardrails 1, 3).

After a base US Core resource is built, the overlay layers the active preset /
specialty IG on top: extra profiles merged into `meta.profile` as a resolved
LIST (so an mCODE resource conforms to US Core AND mCODE), plus IG / user
extensions. Extension VALUES are not yet extracted from notes, so an extension
is applied only once its declaration carries a resolved `value` (the
LLM-fragment follow-on). A defaulted rule is a no-op.
"""
from __future__ import annotations

_EXT_VALUE_KEY = {
    "string": "valueString",
    "boolean": "valueBoolean",
    "integer": "valueInteger",
    "code": "valueCode",
    "dateTime": "valueDateTime",
}


def build_extension(declaration: dict, value) -> dict | None:
    """Build one FHIR extension element from a UserExtension declaration + value."""
    url = declaration.get("url")
    if not url:
        return None
    datatype = declaration.get("datatype", "string")
    if datatype == "CodeableConcept":
        return {"url": url, "valueCodeableConcept": value if isinstance(value, dict) else {"text": str(value)}}
    if datatype == "Quantity":
        return {"url": url, "valueQuantity": value if isinstance(value, dict) else {"value": value}}
    key = _EXT_VALUE_KEY.get(datatype)
    if key is None:
        return None
    return {"url": url, key: value}


def merge_profiles(resource: dict, profiles: list[str]) -> dict:
    """Add profile canonicals to `meta.profile` as a deduped list (order preserved)."""
    if not profiles:
        return resource
    meta = resource.setdefault("meta", {})
    existing = list(meta.get("profile") or [])
    for p in profiles:
        if p not in existing:
            existing.append(p)
    meta["profile"] = existing
    return resource


def apply_overlay(resource: dict, rule) -> dict:
    """Layer a ResourceRule onto a built resource: extra profiles + valued extensions."""
    merge_profiles(resource, getattr(rule, "profiles", None) or [])

    built = []
    for declaration in getattr(rule, "extensions", None) or []:
        value = declaration.get("value") if isinstance(declaration, dict) else None
        if value is None:
            continue
        element = build_extension(declaration, value)
        if element:
            built.append(element)
    if built:
        resource["extension"] = list(resource.get("extension") or []) + built
    return resource
