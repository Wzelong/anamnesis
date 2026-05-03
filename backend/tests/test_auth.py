"""Tests for context/auth.py — review token minting, validation, identity extraction."""
import asyncio
import importlib
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import update

from context.auth import (
    InvalidReviewToken,
    ReviewerIdentity,
    extract_clinician_identity,
    mint_review_token,
    validate_review_token,
)


def _encode_claims(claims: dict) -> str:
    return jwt.encode(claims, "irrelevant-key", algorithm="HS256")


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "auth.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    import db.session as session_mod
    import db as db_pkg
    importlib.reload(session_mod)
    importlib.reload(db_pkg)

    asyncio.run(db_pkg.init_db())
    yield


def _run(coro):
    return asyncio.run(coro)


class TestExtractIdentity:
    def test_fhir_user_and_name(self):
        token = _encode_claims({"fhirUser": "Practitioner/abc123", "name": "Dr. Smith"})
        identity = extract_clinician_identity(token)
        assert identity.display == "Dr. Smith"
        assert identity.fhir_reference == "Practitioner/abc123"

    def test_fhir_user_no_name(self):
        token = _encode_claims({"fhirUser": "Practitioner/xyz"})
        identity = extract_clinician_identity(token)
        assert identity.display == "Authenticated via Prompt Opinion"
        assert identity.fhir_reference == "Practitioner/xyz"

    def test_uuid_sub_not_used_as_display(self):
        token = _encode_claims({"sub": "019dbc8e-914c-7447-9054-4c18443bd188"})
        identity = extract_clinician_identity(token)
        assert identity.display == "Authenticated via Prompt Opinion"
        assert identity.fhir_reference is None

    def test_sub_fallback(self):
        token = _encode_claims({"sub": "user-42"})
        identity = extract_clinician_identity(token)
        assert identity.display == "user-42"
        assert identity.fhir_reference is None

    def test_name_only(self):
        token = _encode_claims({"name": "Jane Doe"})
        identity = extract_clinician_identity(token)
        assert identity.display == "Jane Doe"
        assert identity.fhir_reference is None

    def test_no_identity_claims(self):
        token = _encode_claims({"patient": "p1", "aud": "https://fhir.example.org"})
        identity = extract_clinician_identity(token)
        assert identity.display == "Authenticated via Prompt Opinion"
        assert identity.fhir_reference is None

    def test_fhir_user_without_slash_not_reference(self):
        token = _encode_claims({"fhirUser": "just-a-string", "name": "Test"})
        identity = extract_clinician_identity(token)
        assert identity.fhir_reference is None
        assert identity.display == "Test"


class TestMintAndValidate:
    def test_roundtrip(self):
        async def run():
            identity = ReviewerIdentity(display="Dr. Chen", fhir_reference="Practitioner/p99")
            token = await mint_review_token(identity)
            result = await validate_review_token(token)
            assert result.display == "Dr. Chen"
            assert result.fhir_reference == "Practitioner/p99"
        _run(run())

    def test_roundtrip_no_fhir_reference(self):
        async def run():
            identity = ReviewerIdentity(display="Authenticated via Prompt Opinion")
            token = await mint_review_token(identity)
            result = await validate_review_token(token)
            assert result.display == "Authenticated via Prompt Opinion"
            assert result.fhir_reference is None
        _run(run())

    def test_token_is_short_and_prefixed(self):
        async def run():
            identity = ReviewerIdentity(display="Dr. Test")
            token = await mint_review_token(identity)
            assert token.startswith("rev_")
            assert len(token) <= 16
        _run(run())

    def test_each_mint_yields_a_distinct_token(self):
        async def run():
            identity = ReviewerIdentity(display="Dr. Test")
            t1 = await mint_review_token(identity)
            t2 = await mint_review_token(identity)
            assert t1 != t2
        _run(run())

    def test_unknown_token_raises(self):
        async def run():
            with pytest.raises(InvalidReviewToken):
                await validate_review_token("rev_doesnotexist")
        _run(run())

    def test_expired_token_raises(self):
        async def run():
            from db import AsyncSessionLocal, ReviewToken

            identity = ReviewerIdentity(display="Dr. Test")
            token = await mint_review_token(identity)
            async with AsyncSessionLocal() as session:
                await session.execute(
                    update(ReviewToken)
                    .where(ReviewToken.token == token)
                    .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
                )
                await session.commit()
            with pytest.raises(InvalidReviewToken):
                await validate_review_token(token)
        _run(run())

    def test_invalid_token_is_jwt_compatible(self):
        async def run():
            with pytest.raises(jwt.InvalidTokenError):
                await validate_review_token("rev_nope")
        _run(run())
