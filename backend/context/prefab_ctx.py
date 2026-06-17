"""SHARP context for FastMCP v3 / Prefab tools.

Prefab tools have no `ctx` param; FHIR launch context comes from the per-request
HTTP headers via FastMCP's `get_http_headers()`. Mirrors `context.sharp` but
sourced from the v3 dependency instead of a passed Context.
"""
from __future__ import annotations

import hashlib

import jwt
from fastmcp.server.dependencies import get_http_headers

from context.auth import ReviewerIdentity, extract_clinician_identity
from fhir.client import FhirClient

_URL = "x-fhir-server-url"
_TOKEN = "x-fhir-access-token"
_PATIENT = "x-patient-id"


def _headers() -> dict:
    return get_http_headers(include_all=True)


def prefab_fhir_client() -> FhirClient | None:
    h = _headers()
    url = h.get(_URL)
    if not url:
        return None
    return FhirClient(url.rstrip("/"), h.get(_TOKEN))


def prefab_patient_id() -> str | None:
    h = _headers()
    token = h.get(_TOKEN)
    if token:
        try:
            patient = jwt.decode(token, options={"verify_signature": False}).get("patient")
            if patient:
                return str(patient)
        except jwt.InvalidTokenError:
            pass
    return h.get(_PATIENT)


def prefab_reviewer() -> ReviewerIdentity | None:
    token = _headers().get(_TOKEN)
    return extract_clinician_identity(token) if token else None


def prefab_tenant() -> str | None:
    h = _headers()
    basis = h.get(_URL)
    if not basis:
        token = h.get(_TOKEN)
        if token:
            try:
                claims = jwt.decode(token, options={"verify_signature": False})
                basis = claims.get("iss") or claims.get("azp") or claims.get("aud")
            except jwt.InvalidTokenError:
                basis = None
    if not basis:
        return None
    return hashlib.sha256(str(basis).rstrip("/").lower().encode()).hexdigest()[:16]
