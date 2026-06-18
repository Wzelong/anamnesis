"""Clinician identity from the Prompt Opinion SHARP access token.

PO authenticates the clinician and mints the token; we read identity claims at
MCP-call time. `sub` is the clinician's stable OIDC subject (per-user key);
`po_ws_id` is the workspace. We mint nothing and store no tokens.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import jwt

_UUID_LIKE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


@dataclass
class ReviewerIdentity:
    display: str
    fhir_reference: str | None = None


@dataclass
class UserContext:
    user_key: str  # token `sub` — stable per clinician
    display_name: str | None = None
    workspace_id: str | None = None
    role: str | None = None


def _claims(access_token: str) -> dict:
    return jwt.decode(access_token, options={"verify_signature": False})


def _is_human_label(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if "/" in value:
        return False
    if _UUID_LIKE.match(value):
        return False
    return True


def _display_from_claims(claims: dict) -> str | None:
    if _is_human_label(claims.get("name")):
        return str(claims["name"])
    full = f"{claims.get('given_name') or ''} {claims.get('family_name') or ''}".strip()
    if full:
        return full
    if _is_human_label(claims.get("fhirUser")):
        return str(claims["fhirUser"])
    return None


def extract_clinician_identity(access_token: str) -> ReviewerIdentity:
    claims = _claims(access_token)
    fhir_user = claims.get("fhirUser")
    fhir_reference = str(fhir_user) if fhir_user and "/" in str(fhir_user) else None
    display = _display_from_claims(claims) or "Authenticated via Prompt Opinion"
    return ReviewerIdentity(display=display, fhir_reference=fhir_reference)


def extract_user_context(access_token: str) -> UserContext | None:
    claims = _claims(access_token)
    sub = claims.get("sub")
    if not sub:
        return None
    return UserContext(
        user_key=str(sub),
        display_name=_display_from_claims(claims),
        workspace_id=claims.get("po_ws_id"),
        role=claims.get("role"),
    )
