"""Verify the Prompt Opinion access token as a pure OAuth 2.1 resource server.

PO publishes a JWKS (one RS256 signing key); we verify signature + `iss` + `exp`
against the cached keys. PO issues no `aud` claim, so audience binding is
optional via the `po_mcp_id` pseudo-audience when `settings.po_mcp_id` is set.

Required before keying any per-user write (config today, BYOK secrets next) to a
token's `sub`: an unverified `sub` is forgeable. Read paths stay host-delegated
(a forged token self-fails at the FHIR server). See AUTH.md.
"""
from __future__ import annotations

from functools import lru_cache

import jwt
from jwt import PyJWKClient

from config import settings


class TokenVerificationError(Exception):
    pass


@lru_cache(maxsize=1)
def _jwk_client() -> PyJWKClient:
    return PyJWKClient(settings.po_jwks_uri, cache_keys=True)


def verify_po_token(access_token: str) -> dict:
    """Return verified claims, or raise TokenVerificationError."""
    if not access_token:
        raise TokenVerificationError("missing token")
    try:
        signing_key = _jwk_client().get_signing_key_from_jwt(access_token)
        claims = jwt.decode(
            access_token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.po_issuer,
            options={"verify_aud": False, "require": ["exp", "iss", "sub"]},
        )
    except Exception as exc:  # JWKS fetch, parse, signature, iss/exp all deny
        raise TokenVerificationError(str(exc)) from exc

    if settings.po_mcp_id and claims.get("po_mcp_id") != settings.po_mcp_id:
        raise TokenVerificationError("po_mcp_id mismatch (pseudo-audience)")
    return claims
