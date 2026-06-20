"""Conformance Layer 2a: opportunistic profile $validate against the target FHIR server.

Best-effort. When the SHARP server supports the $validate operation, the accepted
resource is validated against its declared US Core profile before write; the
result rides on the accept response. A server without $validate (or any error)
yields {supported: False} and never blocks the write. See CONFORMANCE.md.
"""
from __future__ import annotations

_UNSUPPORTED = {"level": "profile", "supported": False, "valid": None, "issues": []}


def _location(issue: dict) -> str:
    loc = issue.get("expression") or issue.get("location") or []
    return loc[0] if isinstance(loc, list) and loc else ""


def _message(issue: dict) -> str:
    details = issue.get("details") or {}
    return details.get("text") or issue.get("diagnostics") or issue.get("code") or ""


async def validate_profile(client, resource: dict, profiles: list[str]) -> dict:
    """Validate `resource` against its first declared profile on the target server.

    Returns {level, supported, valid, issues, profile}. `supported` is False when
    no client, no `$validate`, or any error — the caller treats that as "skipped".
    """
    resource_type = resource.get("resourceType")
    if client is None or not resource_type:
        return dict(_UNSUPPORTED)
    profile = profiles[0] if profiles else None
    try:
        status, body = await client.validate(resource_type, resource, profile)
    except Exception:
        return dict(_UNSUPPORTED)
    if status == 404 or not isinstance(body, dict) or body.get("resourceType") != "OperationOutcome":
        return dict(_UNSUPPORTED)

    issues = [
        {"severity": i.get("severity", "information"), "path": _location(i), "message": _message(i)}
        for i in body.get("issue", [])
    ]
    has_error = any(i["severity"] in ("error", "fatal") for i in issues)
    return {"level": "profile", "supported": True, "valid": not has_error, "issues": issues, "profile": profile}
