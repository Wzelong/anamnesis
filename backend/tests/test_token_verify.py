"""Token verification deny paths (offline — no JWKS fetch).

The accept path needs PO's live JWKS, so it is exercised against a real token in
the opt-in e2e suite. Here we only assert that malformed / missing tokens are
rejected before any network call.
"""
import pytest

from context.token_verify import TokenVerificationError, verify_po_token


def test_empty_token_rejected():
    with pytest.raises(TokenVerificationError):
        verify_po_token("")


def test_garbage_token_rejected():
    # Not a JWT: header decode fails before any JWKS fetch.
    with pytest.raises(TokenVerificationError):
        verify_po_token("not-a-jwt")
