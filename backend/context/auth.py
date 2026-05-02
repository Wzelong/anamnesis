"""Review-link aliases for the Prompt Opinion clinician session.

Prompt Opinion authenticates the clinician and mints the SHARP access token.
We extract the identity claims at MCP-call time and persist them under a
short opaque alias (e.g. `rev_a3f9k2x8`) so the deep-link URL stays clean.
The alias is just an addressing handle to the identity we already verified —
production would front this surface with platform SSO instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import delete, select

from core.ids import short_id

_TOKEN_LIFETIME = timedelta(hours=24)


@dataclass
class ReviewerIdentity:
    display: str
    fhir_reference: str | None = None


class InvalidReviewToken(jwt.InvalidTokenError):
    """Raised when a review token is unknown or expired."""


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
