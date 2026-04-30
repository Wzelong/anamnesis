"""Review token minting, validation, and clinician identity extraction."""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt

from config import settings

_SECRET = settings.review_token_secret or secrets.token_urlsafe(32)
_ALGORITHM = "HS256"
_TOKEN_LIFETIME = timedelta(hours=24)


@dataclass
class ReviewerIdentity:
    display: str
    fhir_reference: str | None = None


def extract_clinician_identity(access_token: str) -> ReviewerIdentity:
    claims = jwt.decode(access_token, options={"verify_signature": False})

    fhir_user = claims.get("fhirUser")
    fhir_reference = None
    if fhir_user and "/" in str(fhir_user):
        fhir_reference = str(fhir_user)

    name = claims.get("name")
    sub = claims.get("sub")

    display = name or (str(fhir_user) if fhir_user else None) or (str(sub) if sub else None)
    if not display:
        display = "Authenticated via Prompt Opinion"

    return ReviewerIdentity(display=display, fhir_reference=fhir_reference)


def mint_review_token(
    run_id: str,
    patient_id: str,
    identity: ReviewerIdentity,
) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": identity.fhir_reference or identity.display,
        "name": identity.display,
        "run_id": run_id,
        "patient_id": patient_id,
        "iat": now,
        "exp": now + _TOKEN_LIFETIME,
    }
    return jwt.encode(payload, _SECRET, algorithm=_ALGORITHM)


def validate_review_token(token: str) -> ReviewerIdentity:
    payload = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
    fhir_ref = payload.get("sub")
    if fhir_ref and "/" not in fhir_ref:
        fhir_ref = None
    return ReviewerIdentity(
        display=payload.get("name", "Unknown"),
        fhir_reference=fhir_ref,
    )
