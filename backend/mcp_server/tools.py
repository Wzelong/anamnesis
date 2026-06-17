"""MCP tool implementations."""
import asyncio
import json

from mcp.server.fastmcp import Context

from context.sharp import get_fhir_context, get_patient_id, get_tenant_key
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

    await _top_up_run_creds(ctx)
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

    await _top_up_run_creds(ctx)
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


async def _top_up_run_creds(ctx: Context | None) -> None:
    """Refresh persisted FHIR creds for the SHARP patient's open runs.

    Any MCP call carrying fresh SHARP headers re-arms accept/refresh on the
    review surface without forcing a new pipeline run.
    """
    if ctx is None:
        return
    patient_id = get_patient_id(ctx)
    fhir_client = _get_fhir_client(ctx)
    if not patient_id or fhir_client is None:
        return
    async with AsyncSessionLocal() as session:
        await proposal_svc.refresh_creds_for_patient(patient_id, fhir_client, session)


def _format_duration(ms: int | None) -> str | None:
    if ms is None:
        return None
    if ms < 1000:
        return f"{ms}ms"
    s = ms / 1000
    if s < 60:
        return f"{s:.1f}s"
    m = int(s // 60)
    rem = round(s - m * 60)
    return f"{m}m {rem}s"


def _format_cost(usd: float) -> str:
    if usd == 0:
        return "$0"
    if usd < 0.01:
        return "<$0.01"
    return f"${usd:.2f}"


async def _format_run_summary(result: dict, ctx: Context | None) -> str:
    run_id = result["run_id"]
    total = result["total"]
    by_tier = result["by_tier"]
    cached = result.get("cached", False)

    tier_parts = [f"{tier}: {count}" for tier, count in sorted(by_tier.items())]
    status = "Found existing" if cached else "Generated"

    docs = result.get("total_documents") or 0
    duration = _format_duration(result.get("duration_ms"))
    cost = _format_cost(float(result.get("total_cost_usd") or 0))
    stats_parts = [f"{docs} docs"]
    if duration:
        stats_parts.append(duration)
    stats_parts.append(cost)
    stats_line = " · ".join(stats_parts)

    from context.sharp import get_clinician_identity
    from context.auth import mint_review_token
    from config import settings
    base = settings.frontend_base_url.rstrip("/")
    identity = get_clinician_identity(ctx) if ctx else None
    if identity:
        token = await mint_review_token(identity)
        link = f"{base}/{run_id}?token={token}"
    else:
        link = f"{base}/{run_id}"

    return (
        f"{status} {total} proposals for Patient/{result['patient_id']}:\n"
        f"  {', '.join(tier_parts)}\n"
        f"  {stats_line}\n\n"
        f"Review workspace: {link}\n\n"
        f"Show this link to the clinician exactly as-is. Use ListProposals to review in chat instead."
    )


async def _format_run_started(result: dict, ctx: Context | None) -> str:
    run_id = result["run_id"]

    from context.sharp import get_clinician_identity
    from context.auth import mint_review_token
    from config import settings
    base = settings.frontend_base_url.rstrip("/")
    identity = get_clinician_identity(ctx) if ctx else None
    if identity:
        token = await mint_review_token(identity)
        link = f"{base}/{run_id}?token={token}"
    else:
        link = f"{base}/{run_id}"

    return (
        f"Pipeline started (run {run_id}).\n\n"
        f"Review workspace: {link}\n\n"
        f"The workspace shows live stage-by-stage progress. "
        f"Call GetRunStatus with run_id={run_id} to check when proposals are ready."
    )


async def get_run_status(run_id: str, ctx: Context = None) -> str:
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        from db.models import PipelineRun, ProposalRecord
        run = (await session.execute(
            select(PipelineRun).where(PipelineRun.id == run_id)
        )).scalar_one_or_none()
        if not run:
            return f"Run {run_id} not found."

        if run.status == "running":
            meta = json.loads(run.meta_json or "{}") if run.meta_json else {}
            progress = meta.get("progress", {})
            current = progress.get("current_stage", "starting")
            completed = progress.get("stages_completed", [])
            return (
                f"Run {run_id}: running (stage: {current}, "
                f"{len(completed)} stages completed)"
            )

        if run.status == "failed":
            meta = json.loads(run.meta_json or "{}") if run.meta_json else {}
            return f"Run {run_id}: failed — {meta.get('error', 'unknown error')}"

        proposals = (await session.execute(
            select(ProposalRecord).where(ProposalRecord.run_id == run_id)
        )).scalars().all()
        by_tier: dict[str, int] = {}
        for p in proposals:
            by_tier[p.confidence_tier] = by_tier.get(p.confidence_tier, 0) + 1
        tier_parts = [f"{t}: {c}" for t, c in sorted(by_tier.items())]

        return (
            f"Run {run_id}: completed — {len(proposals)} proposals "
            f"({', '.join(tier_parts)})"
        )


async def propose_augmentations(ctx: Context = None) -> str:
    patient_id = get_patient_id(ctx)
    fhir_client = _get_fhir_client(ctx)

    async with AsyncSessionLocal() as session:
        if patient_id:
            from sqlalchemy import select
            from db.models import ProposalRecord
            existing = (await session.execute(
                select(ProposalRecord)
                .where(ProposalRecord.patient_id == patient_id, ProposalRecord.status == "pending")
                .limit(1)
            )).scalar_one_or_none()
            if existing:
                result = await proposal_svc.run_pipeline(patient_id, session, fhir_client=fhir_client)
                return await _format_run_summary(result, ctx)

    result = await proposal_svc.start_pipeline_background(
        patient_id, fhir_client=fhir_client, triggered_by="mcp",
    )
    return await _format_run_started(result, ctx)


_MAX_NOTE_BYTES = 200_000


async def propose_augmentations_from_notes(
    notes: list[str],
    note_type: str = "External record",
    note_date: str | None = None,
    ctx: Context = None,
) -> str:
    if not notes:
        raise ValueError("notes must contain at least one entry")
    for i, n in enumerate(notes):
        if not isinstance(n, str):
            raise ValueError(f"notes[{i}] must be a string")
        if len(n.encode("utf-8")) > _MAX_NOTE_BYTES:
            raise ValueError(f"notes[{i}] exceeds {_MAX_NOTE_BYTES} bytes")

    patient_id = get_patient_id(ctx)
    if not patient_id:
        raise ValueError("No patient id in SHARP context")
    fhir_client = _get_fhir_client(ctx)

    async with AsyncSessionLocal() as session:
        result = await proposal_svc.run_pipeline_with_inline_notes(
            patient_id,
            notes,
            session,
            note_type=note_type,
            note_date=note_date,
            fhir_client=fhir_client,
        )

    return await _format_run_summary(result, ctx)


def _truncate(text: str, limit: int = 120) -> str:
    s = " ".join(text.split())
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


async def list_proposals_tool(ctx: Context = None) -> str:
    patient_id = get_patient_id(ctx)
    if not patient_id:
        raise ValueError("No patient id in SHARP context")

    await _top_up_run_creds(ctx)
    async with AsyncSessionLocal() as session:
        from sqlalchemy import select
        from db.models import ProposalRecord
        proposals = await proposal_svc.list_proposals(session, patient_id=patient_id)
        rows = (await session.execute(
            select(ProposalRecord.id, ProposalRecord.citations_json)
            .where(ProposalRecord.patient_id == patient_id)
        )).all()
        snippets: dict[str, str] = {}
        for pid, cj in rows:
            try:
                items = json.loads(cj or "[]")
            except json.JSONDecodeError:
                items = []
            if items:
                top = next((c.get("text") for c in items if c.get("text")), "")
                if top:
                    snippets[pid] = _truncate(top)

    if not proposals:
        return "No proposals found. Run ProposeAugmentations first."

    grouped: dict[str, list[dict]] = {}
    for p in proposals:
        grouped.setdefault(p["confidence_tier"], []).append(p)

    lines: list[str] = []
    for tier in ("ATTENTION", "REVIEW", "CONFIDENT"):
        items = grouped.get(tier, [])
        if not items:
            continue
        lines.append(f"\n{tier} ({len(items)})")
        for p in items:
            flags = " | ".join(p.get("flags", [])[:2])
            status_tag = f" [{p['status']}]" if p["status"] != "pending" else ""
            score = f"{p['confidence_score']:.2f}"
            head = (
                f"  {p['id']} | {p['resource_type']} | {p['display_label']} | "
                f"{p['classification']} {score}{status_tag}"
            )
            if flags:
                head += f" | {flags}"
            lines.append(head)
            snip = snippets.get(p["id"])
            if snip:
                lines.append(f"      “{snip}”")

    lines.append("")
    lines.append("Use GetProposal(proposal_id) for full citations, reasoning, conflicts, and FHIR resource.")
    return "\n".join(lines)


async def get_proposal_tool(proposal_id: str, ctx: Context = None) -> str:
    await _top_up_run_creds(ctx)
    async with AsyncSessionLocal() as session:
        try:
            detail = await proposal_svc.get_proposal(proposal_id, session)
        except ValueError as e:
            return f"Error: {e}"

    return json.dumps(detail, indent=2, default=str)


_TERMINOLOGY_SYSTEMS = ("snomed", "rxnorm", "loinc", "icd10")


async def search_terminology_tool(
    query: str,
    system: str,
    top_k: int = 10,
    ctx: Context = None,
) -> str:
    if not query or not query.strip():
        raise ValueError("query must be a non-empty string")
    norm_system = system.lower().strip()
    if norm_system not in _TERMINOLOGY_SYSTEMS:
        raise ValueError(
            f"system must be one of {_TERMINOLOGY_SYSTEMS}, got {system!r}"
        )
    if top_k <= 0 or top_k > 50:
        raise ValueError("top_k must be between 1 and 50")

    from config import settings
    from core.retrieval import ApiRetriever, FaissRetriever

    retriever = FaissRetriever() if settings.coding_retriever == "faiss" else ApiRetriever()
    try:
        results = await retriever.search(query.strip(), norm_system, top_k)
    finally:
        client = getattr(retriever, "_client", None)
        if client is not None:
            await client.aclose()

    payload = [
        {"system": norm_system, "code": r.code, "display": r.display, "score": round(r.score, 4), "rank": r.rank}
        for r in results
    ]
    return json.dumps(payload, indent=2)


async def accept_proposal_tool(proposal_id: str, ctx: Context = None) -> str:
    fhir_client = _get_fhir_client(ctx)

    from context.sharp import get_clinician_identity
    identity = get_clinician_identity(ctx) if ctx else None

    await _top_up_run_creds(ctx)
    async with AsyncSessionLocal() as session:
        result = await proposal_svc.accept_proposal(
            proposal_id, session, fhir_client=fhir_client, reviewer=identity,
        )

    wr = result.get("write_result")
    if wr:
        return f"Accepted {proposal_id}. Written to FHIR: {wr['resource_ref']}, provenance: {wr['provenance_ref']}"
    return f"Accepted {proposal_id}. FHIR write-back deferred (no FHIR connection)."


async def reject_proposal_tool(proposal_id: str, reason: str, ctx: Context = None) -> str:
    from context.sharp import get_clinician_identity
    identity = get_clinician_identity(ctx) if ctx else None

    await _top_up_run_creds(ctx)
    async with AsyncSessionLocal() as session:
        await proposal_svc.reject_proposal(proposal_id, reason, session, reviewer=identity)

    return f"Rejected {proposal_id}. Reason: {reason}"


async def reopen_proposal_tool(proposal_id: str, ctx: Context = None) -> str:
    await _top_up_run_creds(ctx)
    async with AsyncSessionLocal() as session:
        await proposal_svc.reopen_proposal(proposal_id, session)

    return f"Reopened {proposal_id}. Status reset to pending; prior rejection preserved in decision history."


async def edit_proposal_tool(proposal_id: str, updated_resource: str, ctx: Context = None) -> str:
    try:
        resource = json.loads(updated_resource)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}") from e

    await _top_up_run_creds(ctx)
    async with AsyncSessionLocal() as session:
        result = await proposal_svc.edit_proposal(proposal_id, resource, session)

    return f"Updated {proposal_id}. Resource type: {result['resource_type']}, display: {result['display_label']}"


# ---------------------------------------------------------------------------
# Stateless path (MCP App)
#
# The server acts only on accept; everything else is a pure function or
# client-side. No PHI is persisted on this path.
# ---------------------------------------------------------------------------

_EXTRACTION_STAGES = [
    "guardrail",
    "stage1_preprocess",
    "stage2_extract",
    "stage3_merge",
    "stage4_code",
    "stage5_reconcile",
    "stage6_assemble",
]


async def review_launcher_tool(ctx: Context = None) -> dict:
    """Render the in-host review app and seed its patient header.

    Returns immediately (one Patient read); the app then drives RunExtraction.
    """
    fhir = get_fhir_context(ctx)
    patient_id = get_patient_id(ctx)
    if not patient_id:
        raise ValueError("No patient id in SHARP context")

    name = None
    birth_date = None
    if fhir:
        patient = await FhirClient(fhir.url, fhir.token).read(f"Patient/{patient_id}")
        if patient:
            np = (patient.get("name") or [{}])[0]
            given = " ".join(np.get("given") or [])
            family = np.get("family") or ""
            name = f"{given} {family}".strip() or None
            birth_date = patient.get("birthDate")

    return {"patient_id": patient_id, "patient_name": name, "birth_date": birth_date}


async def run_extraction_tool(
    notes: list[str] | None = None,
    note_type: str = "External record",
    note_date: str | None = None,
    ctx: Context = None,
) -> dict:
    """Run the augmentation pipeline and return proposals + source notes.

    Streams stage progress over the request; persists no PHI. With `notes`,
    runs against the supplied text; otherwise against chart-resident notes.
    """
    patient_id = get_patient_id(ctx)
    if not patient_id:
        raise ValueError("No patient id in SHARP context")
    fhir_client = _get_fhir_client(ctx)
    tenant_key = get_tenant_key(ctx)

    total = len(_EXTRACTION_STAGES)

    async def progress_cb(stage: str, detail: dict | None) -> None:
        if ctx is None:
            return
        try:
            idx = _EXTRACTION_STAGES.index(stage) + 1
        except ValueError:
            idx = 0
        await ctx.report_progress(progress=idx, total=total, message=stage)

    return await proposal_svc.run_extraction_ephemeral(
        patient_id,
        fhir_client=fhir_client,
        inline_notes=notes or None,
        note_type=note_type,
        note_date=note_date,
        tenant_key=tenant_key,
        progress_cb=progress_cb,
    )


async def accept_augmentation_tool(
    run_id: str | None = None,
    proposal_id: str | None = None,
    resource: str | None = None,
    citations: str | None = None,
    classification: str = "NEW",
    supersedes: list[str] | None = None,
    ctx: Context = None,
) -> str:
    """Accept an augmentation and write it to FHIR with Provenance.

    Pass run_id + proposal_id to resolve from the in-session cache, or pass the
    full resource (+citations) JSON as a fallback. Stores no PHI.
    """
    from context.sharp import get_clinician_identity

    patient_id = get_patient_id(ctx)
    fhir_client = _get_fhir_client(ctx)
    identity = get_clinician_identity(ctx) if ctx else None

    resource_obj = json.loads(resource) if resource else None
    citations_obj = json.loads(citations) if citations else None

    result = await proposal_svc.accept_augmentation(
        fhir_client=fhir_client,
        reviewer=identity,
        patient_id=patient_id,
        run_id=run_id,
        proposal_id=proposal_id,
        resource=resource_obj,
        citations=citations_obj,
        classification=classification,
        supersedes=supersedes,
    )

    wr = result.get("write_result")
    if wr:
        return f"Accepted {result['id']}. Written to FHIR: {wr['resource_ref']}, provenance: {wr['provenance_ref']}"
    return f"Accepted {result['id']}. FHIR write-back deferred (no FHIR connection)."


async def reject_augmentation_tool(
    run_id: str | None = None,
    proposal_id: str | None = None,
    resource_type: str | None = None,
    ctx: Context = None,
) -> str:
    """Record a non-PHI reject decision. The proposal is dropped client-side."""
    from context.sharp import get_clinician_identity

    identity = get_clinician_identity(ctx) if ctx else None
    await proposal_svc.record_decision(
        action="reject",
        run_id=run_id,
        resource_type=resource_type,
        reviewer=identity.display if identity else None,
    )
    return f"Rejected {proposal_id or '(client-side)'}."
