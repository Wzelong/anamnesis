"""Layered conformance assessment (see CONFORMANCE.md).

One verdict from up to four layers, best-available wins:

- L1   in-process base R4         (`validate_r4`, always, local)
- L3   preset coding-subset       (`check_coding_subset`, local)
- L2a  target server `$validate`   (`validate_profile`, opportunistic)
- L2b  dedicated validator `$validate` (same op against `validator_base_url`, authoritative)

`assess_local` is the sync L1+L3 verdict used at assembly for the pre-accept UI badge.
`assess_conformance` is the async accept-time verdict that enriches it with the
strongest available remote `$validate`. Shape stays wire-compatible with the
frontend `Conformance` type: {valid, level, issues, profile, supported}.
"""
from __future__ import annotations

from config import settings
from fhir.client import FhirClient
from fhir.coding_subset import check_coding_subset
from fhir.profile_validate import validate_profile
from fhir.validate import validate_r4


_US_CORE_NS = "http://hl7.org/fhir/us/core/"
_UNVERIFIED_PREFIX = "profile asserted but not validated locally:"


def validator_client() -> FhirClient | None:
    """The dedicated L2b/L3 validator client, or None when unconfigured."""
    base = settings.validator_base_url
    return FhirClient(base) if base else None


def _asserted_specialty_profiles(resource: dict) -> list[str]:
    """meta.profile entries outside US Core — claimed but not structurally built here."""
    profiles = (resource.get("meta") or {}).get("profile") or []
    return [p for p in profiles if isinstance(p, str) and not p.startswith(_US_CORE_NS)]


def assess_local(
    resource: dict, allowed_systems: list[str] | None = None,
    pinned: list[dict] | None = None, fixed: list[dict] | None = None,
) -> dict:
    """L1 base R4 + L3 coding allow-list. Local, sync, no network.

    A specialty profile (e.g. mCODE) asserted in `meta.profile` is not structurally
    validated locally, so it never claims support — it surfaces an informational
    issue instead, kept honest until a remote `$validate` confirms it.
    """
    base = validate_r4(resource).to_dict()
    issues = list(base["issues"]) + check_coding_subset(resource, allowed_systems, pinned, fixed)
    asserted = _asserted_specialty_profiles(resource)
    if asserted:
        issues.append({"severity": "information", "path": "meta.profile",
                       "message": f"{_UNVERIFIED_PREFIX} {', '.join(asserted)}"})
    valid = not any(i["severity"] in ("error", "fatal") for i in issues)
    return {"valid": valid, "level": "r4", "profile": None, "issues": issues, "supported": False}


async def assess_conformance(
    resource: dict,
    *,
    profiles: list[str] | None = None,
    allowed_systems: list[str] | None = None,
    pinned: list[dict] | None = None,
    fixed: list[dict] | None = None,
    target_client: FhirClient | None = None,
    validator: FhirClient | None = None,
) -> dict:
    """Full verdict: local L1+L3, then enriched by the strongest available `$validate`."""
    verdict = assess_local(resource, allowed_systems, pinned, fixed)

    client = validator or target_client
    if client is not None:
        remote = await validate_profile(client, resource, profiles or [])
        if remote.get("supported"):
            verdict["level"] = "validator" if validator is not None else "profile"
            verdict["profile"] = remote.get("profile")
            verdict["supported"] = True
            kept = [i for i in verdict["issues"]
                    if not str(i.get("message", "")).startswith(_UNVERIFIED_PREFIX)]
            verdict["issues"] = kept + remote.get("issues", [])
            if remote.get("valid") is False:
                verdict["valid"] = False
    return verdict
