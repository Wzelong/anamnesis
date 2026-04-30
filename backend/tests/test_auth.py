"""Tests for context/auth.py — review token minting, validation, identity extraction."""
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from context.auth import (
    ReviewerIdentity,
    _SECRET,
    extract_clinician_identity,
    mint_review_token,
    validate_review_token,
)


def _encode_claims(claims: dict) -> str:
    return jwt.encode(claims, "irrelevant-key", algorithm="HS256")


class TestExtractIdentity:
    def test_fhir_user_and_name(self):
        token = _encode_claims({"fhirUser": "Practitioner/abc123", "name": "Dr. Smith"})
        identity = extract_clinician_identity(token)
        assert identity.display == "Dr. Smith"
        assert identity.fhir_reference == "Practitioner/abc123"

    def test_fhir_user_no_name(self):
        token = _encode_claims({"fhirUser": "Practitioner/xyz"})
        identity = extract_clinician_identity(token)
        assert identity.display == "Practitioner/xyz"
        assert identity.fhir_reference == "Practitioner/xyz"

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
        identity = ReviewerIdentity(display="Dr. Chen", fhir_reference="Practitioner/p99")
        token = mint_review_token("run-1", "patient-1", identity)
        result = validate_review_token(token)
        assert result.display == "Dr. Chen"
        assert result.fhir_reference == "Practitioner/p99"

    def test_roundtrip_no_fhir_reference(self):
        identity = ReviewerIdentity(display="Authenticated via Prompt Opinion")
        token = mint_review_token("run-2", "patient-2", identity)
        result = validate_review_token(token)
        assert result.display == "Authenticated via Prompt Opinion"
        assert result.fhir_reference is None

    def test_expired_token_raises(self):
        payload = {
            "sub": "test",
            "name": "Expired",
            "run_id": "r",
            "patient_id": "p",
            "iat": datetime.now(timezone.utc) - timedelta(hours=48),
            "exp": datetime.now(timezone.utc) - timedelta(hours=24),
        }
        token = jwt.encode(payload, _SECRET, algorithm="HS256")
        with pytest.raises(jwt.ExpiredSignatureError):
            validate_review_token(token)

    def test_bad_signature_raises(self):
        payload = {
            "sub": "test",
            "name": "Bad",
            "run_id": "r",
            "patient_id": "p",
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        token = jwt.encode(payload, "wrong-secret", algorithm="HS256")
        with pytest.raises(jwt.InvalidSignatureError):
            validate_review_token(token)

    def test_payload_contains_run_and_patient(self):
        identity = ReviewerIdentity(display="Dr. Test")
        token = mint_review_token("run-abc", "patient-xyz", identity)
        payload = jwt.decode(token, _SECRET, algorithms=["HS256"])
        assert payload["run_id"] == "run-abc"
        assert payload["patient_id"] == "patient-xyz"
