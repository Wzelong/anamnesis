"""MCP tool implementations."""
import asyncio
import json

from mcp.server.fastmcp import Context

from context.sharp import get_fhir_context, get_patient_id
from db import AsyncSessionLocal
from fhir.client import FhirClient
from fhir.read import read_documents, read_patient_context
from services import proposals as proposal_svc


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


def _get_fhir_client(ctx: Context) -> FhirClient | None:
    fhir = get_fhir_context(ctx)
    if not fhir:
        return None
    return FhirClient(fhir.url, fhir.token)


async def propose_augmentations(ctx: Context = None) -> str:
    patient_id = get_patient_id(ctx)
    fhir_client = _get_fhir_client(ctx)

    async with AsyncSessionLocal() as session:
        result = await proposal_svc.run_pipeline(patient_id, session, fhir_client=fhir_client)

    run_id = result["run_id"]
    total = result["total"]
    by_tier = result["by_tier"]
    cached = result.get("cached", False)

    tier_parts = [f"{tier}: {count}" for tier, count in sorted(by_tier.items())]
    status = "Found existing" if cached else "Generated"

    return (
        f"{status} {total} proposals for Patient/{result['patient_id']}:\n"
        f"  {', '.join(tier_parts)}\n"
        f"Use ListProposals to review, or open: /{run_id}"
    )


async def list_proposals_tool(ctx: Context = None) -> str:
    patient_id = get_patient_id(ctx)
    if not patient_id:
        raise ValueError("No patient id in SHARP context")

    async with AsyncSessionLocal() as session:
        proposals = await proposal_svc.list_proposals(session, patient_id=patient_id)

    if not proposals:
        return "No proposals found. Run ProposeAugmentations first."

    grouped: dict[str, list[dict]] = {}
    for p in proposals:
        grouped.setdefault(p["confidence_tier"], []).append(p)

    lines: list[str] = []
    tier_labels = {"ATTENTION": "ATTENTION", "REVIEW": "REVIEW", "CONFIDENT": "CONFIDENT"}
    for tier in ("ATTENTION", "REVIEW", "CONFIDENT"):
        items = grouped.get(tier, [])
        if not items:
            continue
        lines.append(f"\n{tier_labels[tier]} ({len(items)})")
        for p in items:
            flags = " | ".join(p.get("flags", [])[:2])
            status_tag = f" [{p['status']}]" if p["status"] != "pending" else ""
            lines.append(
                f"  {p['id'][:8]} | {p['resource_type']} | {p['display_label']} | "
                f"{p['classification']}{status_tag} | {flags}"
            )

    return "\n".join(lines)


async def accept_proposal_tool(proposal_id: str, ctx: Context = None) -> str:
    fhir_client = _get_fhir_client(ctx)

    async with AsyncSessionLocal() as session:
        result = await proposal_svc.accept_proposal(
            proposal_id, session, fhir_client=fhir_client,
        )

    wr = result.get("write_result")
    if wr:
        return f"Accepted {proposal_id}. Written to FHIR: {wr['resource_ref']}, provenance: {wr['provenance_ref']}"
    return f"Accepted {proposal_id}. FHIR write-back deferred (no FHIR connection or non-NEW classification)."


async def reject_proposal_tool(proposal_id: str, reason: str, ctx: Context = None) -> str:
    async with AsyncSessionLocal() as session:
        await proposal_svc.reject_proposal(proposal_id, reason, session)

    return f"Rejected {proposal_id}. Reason: {reason}"


async def edit_proposal_tool(proposal_id: str, updated_resource: str, ctx: Context = None) -> str:
    try:
        resource = json.loads(updated_resource)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    async with AsyncSessionLocal() as session:
        result = await proposal_svc.edit_proposal(proposal_id, resource, session)

    return f"Updated {proposal_id}. Resource type: {result['resource_type']}, display: {result['display_label']}"
