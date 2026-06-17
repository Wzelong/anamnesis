"""SHARP-on-MCP context extraction from per-request headers."""
import hashlib
from dataclasses import dataclass

import jwt
from mcp.server.fastmcp import Context

FHIR_SERVER_URL_HEADER = "x-fhir-server-url"
FHIR_ACCESS_TOKEN_HEADER = "x-fhir-access-token"
PATIENT_ID_HEADER = "x-patient-id"


@dataclass
class FhirContext:
    url: str
    token: str | None = None


def get_fhir_context(ctx: Context) -> FhirContext | None:
    req = ctx.request_context.request
    url = req.headers.get(FHIR_SERVER_URL_HEADER)
    if not url:
        return None
    token = req.headers.get(FHIR_ACCESS_TOKEN_HEADER)
    return FhirContext(url=url, token=token)


def get_patient_id(ctx: Context) -> str | None:
    req = ctx.request_context.request
    token = req.headers.get(FHIR_ACCESS_TOKEN_HEADER)
    if token:
        claims = jwt.decode(token, options={"verify_signature": False})
        patient = claims.get("patient")
        if patient:
            return str(patient)
    return req.headers.get(PATIENT_ID_HEADER)


def get_clinician_identity(ctx: Context):
    from context.auth import ReviewerIdentity, extract_clinician_identity
    req = ctx.request_context.request
    token = req.headers.get(FHIR_ACCESS_TOKEN_HEADER)
    if not token:
        return None
    return extract_clinician_identity(token)


def get_tenant_key(ctx: Context) -> str | None:
    """Stable, non-PHI tenant identity for telemetry + (later) config lookup.

    Derived per-request from SHARP — no session, no patient identifiers. Keys on
    the FHIR server (the organization's data home), falling back to the token
    issuer/client claim.
    """
    req = ctx.request_context.request
    basis = req.headers.get(FHIR_SERVER_URL_HEADER)
    if not basis:
        token = req.headers.get(FHIR_ACCESS_TOKEN_HEADER)
        if token:
            try:
                claims = jwt.decode(token, options={"verify_signature": False})
                basis = claims.get("iss") or claims.get("azp") or claims.get("aud")
            except jwt.InvalidTokenError:
                basis = None
    if not basis:
        return None
    return hashlib.sha256(str(basis).rstrip("/").lower().encode("utf-8")).hexdigest()[:16]
