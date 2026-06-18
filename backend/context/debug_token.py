"""One-shot SHARP token-claim capture for auth design (DEV ONLY).

Gated by DEBUG_TOKEN_CLAIMS=1. Decodes the per-request PO token WITHOUT
verification and logs the identity-relevant claims so we can see which
user/tenant/issuer claims are stable before keying config to them. Patient and
unknown claims are redacted (key shown, value withheld) to keep PHI out of logs.
Delete this module once the auth schema is committed.
"""
from __future__ import annotations

import logging
import os

import jwt
from fastmcp.server.dependencies import get_http_headers

log = logging.getLogger("anamnesis.debug_token")

_IDENTITY_CLAIMS = {
    "iss", "sub", "aud", "azp", "client_id", "fhirUser", "name",
    "preferred_username", "email", "tenant", "tenant_id", "workspace",
    "workspace_id", "org", "scope", "scp", "exp", "iat",
}
_REDACT = {"patient", "fhirContext", "encounter"}


def capture(source: str) -> None:
    if os.environ.get("DEBUG_TOKEN_CLAIMS") != "1":
        return
    h = get_http_headers(include_all=True)
    sharp = {k: v for k, v in h.items() if k.lower().startswith("x-fhir") or k.lower() == "x-patient-id"}
    log.warning("[%s] SHARP headers present: %s", source, sorted(sharp.keys()))
    log.warning("[%s] x-fhir-server-url: %s", source, h.get("x-fhir-server-url"))

    token = h.get("x-fhir-access-token")
    if not token:
        log.warning("[%s] no x-fhir-access-token on this call", source)
        return
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.InvalidTokenError as e:
        log.warning("[%s] token did not decode as JWT: %s", source, e)
        return

    log.warning("[%s] all claim keys: %s", source, sorted(claims.keys()))
    for k in sorted(claims.keys()):
        if k in _REDACT:
            log.warning("[%s]   %s = <redacted PHI>", source, k)
        elif k in _IDENTITY_CLAIMS:
            log.warning("[%s]   %s = %r", source, k, claims[k])
        else:
            log.warning("[%s]   %s = <%s, value withheld>", source, k, type(claims[k]).__name__)
