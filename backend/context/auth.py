"""Review-link aliases for the Prompt Opinion clinician session.

Prompt Opinion authenticates the clinician and mints the SHARP access token.
We extract the identity claims at MCP-call time and persist them under a
short opaque alias (e.g. `rev_a3f9k2x8`) so the deep-link URL stays clean.
The alias is just an addressing handle to the identity we already verified —
production would front this surface with platform SSO instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import delete, select

from core.ids import short_id

_TOKEN_LIFETIME = timedelta(hours=24)
_UUID_LIKE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


@dataclass
class ReviewerIdentity:
    display: str
    fhir_reference: str | None = None


class InvalidReviewToken(jwt.InvalidTokenError):
    """Raised when a review token is unknown or expired."""


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


async def mint_review_token(identity: ReviewerIdentity) -> str:
    from db import AsyncSessionLocal, ReviewToken

    token = short_id("rev")
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        session.add(ReviewToken(
            token=token,
            display=identity.display,
            fhir_reference=identity.fhir_reference,
            expires_at=now + _TOKEN_LIFETIME,
            created_at=now,
        ))
        await session.commit()
    return token


async def validate_review_token(token: str) -> ReviewerIdentity:
    from db import AsyncSessionLocal, ReviewToken

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(ReviewToken).where(ReviewToken.token == token)
        )).scalar_one_or_none()
        if row is None:
            raise InvalidReviewToken("token not recognized")
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < now:
            await session.execute(delete(ReviewToken).where(ReviewToken.token == token))
            await session.commit()
            raise InvalidReviewToken("token expired")
        return ReviewerIdentity(display=row.display, fhir_reference=row.fhir_reference)
