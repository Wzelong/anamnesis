"""Clinician identity from the Prompt Opinion SHARP access token.

Prompt Opinion authenticates the clinician and mints the SHARP access token.
We read the identity claims at MCP-call time for audit attribution
(Provenance.author) — we do not mint or store our own tokens.
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


def _is_human_label(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if "/" in value:
        return False
    if _UUID_LIKE.match(value):
        return False
    return True


def extract_clinician_identity(access_token: str) -> ReviewerIdentity:
    claims = jwt.decode(access_token, options={"verify_signature": False})

    fhir_user = claims.get("fhirUser")
    fhir_reference = str(fhir_user) if fhir_user and "/" in str(fhir_user) else None

    for candidate in (claims.get("name"), fhir_user, claims.get("sub")):
        if _is_human_label(candidate):
            return ReviewerIdentity(display=str(candidate), fhir_reference=fhir_reference)

    return ReviewerIdentity(display="Authenticated via Prompt Opinion", fhir_reference=fhir_reference)
