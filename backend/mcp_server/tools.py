"""MCP tool implementations."""
import asyncio

from mcp.server.fastmcp import Context

from context.sharp import get_fhir_context, get_patient_id
from fhir.client import FhirClient
from fhir.read import read_documents, read_patient_context


async def who_is_patient(ctx: Context = None) -> str:
    fhir = get_fhir_context(ctx)
    if not fhir:
        raise ValueError("FHIR context missing: SHARP headers not received")

    patient_id = get_patient_id(ctx)
    if not patient_id:
        raise ValueError("No patient id in SHARP context")

    patient = await FhirClient(fhir.url, fhir.token).read(f"Patient/{patient_id}")
    if not patient:
        raise ValueError(f"Patient/{patient_id} not found")

    name = (patient.get("name") or [{}])[0]
    given = " ".join(name.get("given") or [])
    family = name.get("family") or ""
    full = f"{given} {family}".strip() or "(unnamed)"
    return f"Patient {patient_id}: {full} (birthDate={patient.get('birthDate', 'unknown')})"


async def get_patient_context(ctx: Context = None) -> str:
    fhir = get_fhir_context(ctx)
    if not fhir:
        raise ValueError("FHIR context missing: SHARP headers not received")

    patient_id = get_patient_id(ctx)
    if not patient_id:
        raise ValueError("No patient id in SHARP context")

    client = FhirClient(fhir.url, fhir.token)
    pctx, docs = await asyncio.gather(
        read_patient_context(client, patient_id),
        read_documents(client, patient_id),
    )

    name = (pctx.patient.get("name") or [{}])[0]
    given = " ".join(name.get("given") or [])
    family = name.get("family") or ""
    full = f"{given} {family}".strip() or "(unnamed)"

    return (
        f"{full} (Patient/{patient_id}) — "
        f"{len(pctx.conditions)} conditions, "
        f"{len(pctx.medications)} meds, "
        f"{len(pctx.allergies)} allergies, "
        f"{len(pctx.observations)} observations, "
        f"{len(pctx.family_history)} family history entries, "
        f"{len(pctx.procedures)} procedures, "
        f"{len(pctx.encounters)} encounters, "
        f"{len(docs)} documents."
    )
