"""SHARP-on-MCP context extraction from per-request headers."""
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
