"""Service layer for proposal lifecycle: run pipeline, list, accept, reject, edit."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PipelineRun, ProposalRecord

log = logging.getLogger(__name__)

_TIER_ORDER = {"ATTENTION": 0, "REVIEW": 1, "CONFIDENT": 2}


def _display_label(resource: dict) -> str:
    for path in ("code", "medicationCodeableConcept", "relationship"):
        cc = resource.get(path)
        if isinstance(cc, dict) and cc.get("text"):
            return cc["text"]
    return resource.get("resourceType", "unknown")


def _proposal_to_record(proposal, run_id: str, patient_id: str) -> ProposalRecord:
    metadata = {
        "classification_reasoning": proposal.classification_reasoning,
        "extraction_reasoning": proposal.extraction_reasoning,
        "merge_reasoning": proposal.merge_reasoning,
        "flags": proposal.flags,
        "chart_matches": [m.model_dump(mode="json") for m in proposal.chart_matches],
        "supersedes": proposal.supersedes,
        "conflicts_with": proposal.conflicts_with,
    }
    return ProposalRecord(
        id=proposal.id,
        run_id=run_id,
        patient_id=patient_id,
        resource_type=proposal.resource_type,
        classification=proposal.classification,
        confidence_tier=proposal.confidence_tier,
        confidence_score=Decimal(str(round(proposal.confidence_score, 3))),
        status="pending",
        resource_json=json.dumps(proposal.resource),
        citations_json=json.dumps([c.model_dump(mode="json") for c in proposal.citations]),
        metadata_json=json.dumps(metadata),
        created_at=datetime.now(timezone.utc),
    )


def _record_to_dict(record: ProposalRecord, *, full: bool = False) -> dict:
    resource = json.loads(record.resource_json)
    metadata = json.loads(record.metadata_json)
    d: dict = {
        "id": record.id,
        "run_id": record.run_id,
        "resource_type": record.resource_type,
        "classification": record.classification,
        "confidence_tier": record.confidence_tier,
        "confidence_score": float(record.confidence_score),
        "status": record.status,
        "display_label": _display_label(resource),
        "flags": metadata.get("flags", []),
    }
    if full:
        d["resource"] = resource
        d["citations"] = json.loads(record.citations_json)
        d["classification_reasoning"] = metadata.get("classification_reasoning", "")
        d["extraction_reasoning"] = metadata.get("extraction_reasoning", "")
        d["merge_reasoning"] = metadata.get("merge_reasoning")
        d["chart_matches"] = metadata.get("chart_matches", [])
        d["supersedes"] = metadata.get("supersedes", [])
        d["conflicts_with"] = metadata.get("conflicts_with", [])
        d["reviewed_at"] = record.reviewed_at.isoformat() if record.reviewed_at else None
        d["reviewed_by"] = record.reviewed_by
    return d


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

async def run_pipeline(
    patient_id: str | None,
    session: AsyncSession,
    *,
    fhir_client=None,
) -> dict:
    effective_patient_id = patient_id

    if effective_patient_id:
        existing = await session.execute(
            select(ProposalRecord)
            .where(ProposalRecord.patient_id == effective_patient_id, ProposalRecord.status == "pending")
            .limit(1)
        )
        row = existing.scalar_one_or_none()
        if row:
            all_rows = (await session.execute(
                select(ProposalRecord).where(ProposalRecord.patient_id == effective_patient_id)
            )).scalars().all()
            by_tier: dict[str, int] = {}
            for r in all_rows:
                by_tier[r.confidence_tier] = by_tier.get(r.confidence_tier, 0) + 1
            return {
                "run_id": row.run_id,
                "patient_id": effective_patient_id,
                "total": len(all_rows),
                "by_tier": by_tier,
                "cached": True,
            }

    if fhir_client:
        from fhir.read import read_documents, read_patient_context
        patient_context, documents = await read_patient_context(fhir_client, effective_patient_id), await read_documents(fhir_client, effective_patient_id)
    else:
        from fhir.local_bundle import load_demo_data
        patient_context, documents = load_demo_data()

    effective_patient_id = patient_context.patient["id"]

    from core.preprocess import preprocess_documents
    notes = preprocess_documents(documents)

    from openai import AsyncOpenAI
    from config import settings
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    model = settings.openai_model_fast
    cache_dir = Path(__file__).resolve().parent.parent / ".cache"

    from core.cache import JsonCache
    from core.extraction import extract_candidates_batch, merge_across_notes
    from core.code_candidates import code_candidates
    from core.reconcile import reconcile
    from core.augment import assemble_proposals

    stage2_cache = JsonCache(cache_dir / "stage2_output")
    stage2 = await extract_candidates_batch(notes, client, model=model, cache=stage2_cache)

    stage3_cache = JsonCache(cache_dir / "stage3")
    stage3 = await merge_across_notes(stage2, client, model=model, cache=stage3_cache)

    stage4 = await code_candidates(stage3, client, model=model)

    stage5 = await reconcile(stage4, patient_context, client, model=model)

    stage6 = assemble_proposals(stage5, notes, patient_context)

    run_id = uuid4().hex
    now = datetime.now(timezone.utc)

    pipeline_run = PipelineRun(
        id=run_id,
        patient_id=effective_patient_id,
        triggered_by="api",
        status="completed",
        started_at=now,
        finished_at=datetime.now(timezone.utc),
    )
    session.add(pipeline_run)

    for proposal in stage6.proposals:
        session.add(_proposal_to_record(proposal, run_id, effective_patient_id))

    await session.commit()

    by_tier = {}
    for p in stage6.proposals:
        by_tier[p.confidence_tier] = by_tier.get(p.confidence_tier, 0) + 1

    log.info("pipeline run %s: %d proposals for %s", run_id, len(stage6.proposals), effective_patient_id)

    return {
        "run_id": run_id,
        "patient_id": effective_patient_id,
        "total": len(stage6.proposals),
        "by_tier": by_tier,
        "cached": False,
    }


async def list_proposals(
    session: AsyncSession,
    *,
    patient_id: str | None = None,
    run_id: str | None = None,
) -> list[dict]:
    if not patient_id and not run_id:
        raise ValueError("patient_id or run_id required")

    stmt = select(ProposalRecord)
    if patient_id:
        stmt = stmt.where(ProposalRecord.patient_id == patient_id)
    if run_id:
        stmt = stmt.where(ProposalRecord.run_id == run_id)

    rows = (await session.execute(stmt)).scalars().all()

    results = [_record_to_dict(r) for r in rows]
    results.sort(key=lambda d: (_TIER_ORDER.get(d["confidence_tier"], 9), d["confidence_score"]))
    return results


async def get_proposal(proposal_id: str, session: AsyncSession) -> dict:
    record = await session.get(ProposalRecord, proposal_id)
    if not record:
        raise ValueError(f"proposal {proposal_id} not found")
    return _record_to_dict(record, full=True)


async def accept_proposal(
    proposal_id: str,
    session: AsyncSession,
    *,
    fhir_client=None,
    reviewer: str | None = None,
) -> dict:
    record = await session.get(ProposalRecord, proposal_id)
    if not record:
        raise ValueError(f"proposal {proposal_id} not found")
    if record.status != "pending":
        raise ValueError(f"proposal {proposal_id} is already {record.status}")

    record.status = "accepted"
    record.reviewed_at = datetime.now(timezone.utc)
    record.reviewed_by = reviewer

    write_result = None
    if fhir_client:
        from fhir.write import AugmentationProposal as WriteProposal, Citation, apply_augmentation
        raw_citations = json.loads(record.citations_json)
        citations = [
            Citation(
                document_ref=f"DocumentReference/{c['document_id']}",
                start=c["char_start"], end=c["char_end"], text=c["text"],
            )
            for c in raw_citations
        ]
        metadata = json.loads(record.metadata_json)
        supersedes = metadata.get("supersedes", [])
        wp = WriteProposal(
            classification=record.classification,
            resource=json.loads(record.resource_json),
            citations=citations,
            supersedes_ref=supersedes[0] if supersedes else None,
        )
        result = await apply_augmentation(fhir_client, wp)
        write_result = {
            "resource_ref": result.resource_ref,
            "provenance_ref": result.provenance_ref,
            "superseded_ref": result.superseded_ref,
        }

    await session.commit()

    return {
        "id": record.id,
        "status": "accepted",
        "write_result": write_result,
    }


async def reject_proposal(
    proposal_id: str,
    reason: str,
    session: AsyncSession,
    *,
    reviewer: str | None = None,
) -> dict:
    record = await session.get(ProposalRecord, proposal_id)
    if not record:
        raise ValueError(f"proposal {proposal_id} not found")
    if record.status != "pending":
        raise ValueError(f"proposal {proposal_id} is already {record.status}")

    record.status = "rejected"
    record.reviewed_at = datetime.now(timezone.utc)
    record.reviewed_by = reviewer

    metadata = json.loads(record.metadata_json)
    metadata["rejection_reason"] = reason
    record.metadata_json = json.dumps(metadata)

    await session.commit()

    return {"id": record.id, "status": "rejected", "reason": reason}


async def edit_proposal(
    proposal_id: str,
    updated_resource: dict,
    session: AsyncSession,
) -> dict:
    record = await session.get(ProposalRecord, proposal_id)
    if not record:
        raise ValueError(f"proposal {proposal_id} not found")
    if record.status != "pending":
        raise ValueError(f"proposal {proposal_id} is already {record.status}")

    new_rt = updated_resource.get("resourceType", "")
    if new_rt != record.resource_type:
        raise ValueError(f"resourceType mismatch: expected {record.resource_type}, got {new_rt}")

    record.resource_json = json.dumps(updated_resource)
    await session.commit()

    return _record_to_dict(record, full=True)
