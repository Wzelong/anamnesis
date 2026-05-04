"""Service layer for proposal lifecycle.

Entry points are framework-agnostic: each takes an `AsyncSession` (and a
`FhirClient` where chart I/O is needed) so both the REST surface
(`api/routes.py`) and the MCP surface (`mcp_server/tools.py`) can call them
unchanged. The service layer owns:

  * Pipeline execution — `run_pipeline` (chart-resident notes) and
    `run_pipeline_with_inline_notes` (agent-supplied text) both funnel into
    `_run_with_documents` -> `_execute_stages`, which runs the doc guardrail,
    Stages 2 - 5, and Stage 6 assembly. Persistence to `PipelineRun` and
    `ProposalRecord` happens at the end.
  * Proposal lifecycle — `accept_proposal` (writes a FHIR transaction Bundle
    via `apply_augmentation`), `reject_proposal`, `reopen_proposal`,
    `edit_proposal`. Status transitions are guarded so accepted proposals
    cannot be reopened.
  * Read-side queries — `list_proposals`, `get_proposal`, `run_stats`,
    `load_run_source`.
  * FHIR credential lifecycle — `_update_run_fhir_meta`,
    `refresh_creds_for_patient`, `fhir_token_expires_at` keep stored SHARP
    creds fresh so the review surface keeps working after token expiry.
  * Display helpers — `_cc_text`, `_observation_label`, `_display_label`,
    etc. turn FHIR resource dicts into human-readable strings for the UI
    and the MCP tool responses.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING
from core.ids import short_id

if TYPE_CHECKING:
    from context.auth import ReviewerIdentity

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import LLMCall, PipelineRun, ProposalRecord
from fhir.models import Document

log = logging.getLogger(__name__)

_TIER_ORDER = {"ATTENTION": 0, "REVIEW": 1, "CONFIDENT": 2}


INLINE_DOC_PREFIX = "inline_"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _documents_from_notes(
    raw_notes: list[str],
    note_type: str,
    note_date: str | None,
) -> list[Document]:
    """Build virtual Documents from agent-supplied note text.

    IDs are deterministic over content (sha256 prefix) so the same note
    re-uploaded yields the same id across runs.
    """
    date = note_date or _now_iso()
    out: list[Document] = []
    for raw in raw_notes:
        text = (raw or "").strip()
        if not text:
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        out.append(Document(
            id=f"{INLINE_DOC_PREFIX}{digest}",
            type=note_type,
            date=date,
            author="",
            text=text,
            encounter_id=None,
        ))
    if not out:
        raise ValueError("no usable notes provided")
    return out


async def _load_source(patient_id: str | None, *, fhir_client=None):
    if fhir_client and patient_id:
        import asyncio
        from fhir.read import read_documents, read_patient_context
        return await asyncio.gather(
            read_patient_context(fhir_client, patient_id),
            read_documents(fhir_client, patient_id),
        )
    from fhir.local_bundle import load_demo_data
    return load_demo_data()


async def run_stats(run_id: str, session: AsyncSession) -> dict:
    run = (await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))).scalar_one_or_none()
    duration_ms: int | None = None
    if run and run.started_at and run.finished_at:
        duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    usage = (await session.execute(
        select(
            func.coalesce(func.sum(LLMCall.input_tokens + LLMCall.output_tokens), 0).label("tokens"),
            func.coalesce(func.sum(LLMCall.usd_cost), 0).label("cost"),
            func.count(func.distinct(LLMCall.document_id)).label("docs"),
        ).where(LLMCall.run_id == run_id)
    )).one()
    return {
        "duration_ms": duration_ms,
        "total_documents": int(usage.docs or 0),
        "total_tokens": int(usage.tokens or 0),
        "total_cost_usd": float(usage.cost or 0),
    }


async def load_run_source(run_id: str, session: AsyncSession, *, fhir_client=None):
    run = (await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))).scalar_one_or_none()
    if run is None:
        return None
    from services import run_snapshot
    snapshot = run_snapshot.read(run_id)
    if snapshot is not None:
        return snapshot
    return await _load_source(run.patient_id, fhir_client=fhir_client)


def _fhir_meta_from_client(fhir_client) -> dict | None:
    if fhir_client is None:
        return None
    base_url = getattr(fhir_client, "base_url", None)
    token = getattr(fhir_client, "token", None)
    if not base_url or not token:
        return None
    return {"base_url": base_url, "token": token}


async def _update_run_fhir_meta(session: AsyncSession, run_id: str, fhir_meta: dict) -> None:
    run = (await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))).scalar_one_or_none()
    if run is None:
        return
    try:
        meta = json.loads(run.meta_json) if run.meta_json else {}
    except json.JSONDecodeError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    meta["fhir"] = fhir_meta
    run.meta_json = json.dumps(meta, default=str)
    await session.commit()


def read_run_fhir_meta(run: PipelineRun) -> dict | None:
    if not run.meta_json:
        return None
    try:
        meta = json.loads(run.meta_json)
    except json.JSONDecodeError:
        return None
    fhir = meta.get("fhir") if isinstance(meta, dict) else None
    if isinstance(fhir, dict) and fhir.get("base_url") and fhir.get("token"):
        return fhir
    return None


def fhir_token_expires_at(token: str) -> datetime | None:
    import jwt
    try:
        claims = jwt.decode(token, options={"verify_signature": False})
    except Exception:
        return None
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    return datetime.fromtimestamp(exp, tz=timezone.utc)


async def refresh_creds_for_patient(
    patient_id: str | None,
    fhir_client,
    session: AsyncSession,
) -> int:
    """Top up the stored FHIR creds for any of this patient's open runs.

    Called from MCP tool entrypoints so a clinician's "do anything" action
    silently re-arms accept/refresh on the review surface after an expired
    token, without forcing a fresh pipeline run. Returns the number of runs
    whose creds were updated.
    """
    if not patient_id:
        return 0
    fhir_meta = _fhir_meta_from_client(fhir_client)
    if fhir_meta is None:
        return 0
    rows = (await session.execute(
        select(PipelineRun).where(PipelineRun.patient_id == patient_id)
    )).scalars().all()
    updated = 0
    for run in rows:
        try:
            meta = json.loads(run.meta_json) if run.meta_json else {}
        except json.JSONDecodeError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        meta["fhir"] = fhir_meta
        run.meta_json = json.dumps(meta, default=str)
        updated += 1
    if updated:
        await session.commit()
    return updated


async def refresh_run_chart(run_id: str, session: AsyncSession):
    run = (await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))).scalar_one_or_none()
    if run is None:
        return None
    fhir = read_run_fhir_meta(run)
    if fhir is None:
        raise PermissionError("run has no live FHIR connection")
    expires = fhir_token_expires_at(fhir["token"])
    if expires is not None and expires <= datetime.now(timezone.utc):
        raise PermissionError("FHIR access token has expired")

    from fhir.client import FhirClient
    from fhir.read import read_patient_context
    from services import run_snapshot

    client = FhirClient(fhir["base_url"], fhir["token"])
    patient_context = await read_patient_context(client, run.patient_id)
    snapshot = run_snapshot.read(run_id)
    documents = snapshot[1] if snapshot else []
    run_snapshot.write(run_id, patient_context, documents)
    return patient_context, documents


def _cc_text(cc: dict | None) -> str | None:
    if not isinstance(cc, dict):
        return None
    if cc.get("text"):
        return cc["text"]
    coding = cc.get("coding") or []
    if coding and isinstance(coding[0], dict):
        return coding[0].get("display")
    return None


def _qty_str(q: dict | None) -> str | None:
    if not isinstance(q, dict) or q.get("value") is None:
        return None
    v = q["value"]
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    u = q.get("unit") or ""
    return f"{v} {u}".rstrip()


def _observation_label(r: dict) -> str:
    name = _cc_text(r.get("code")) or "observation"

    components = r.get("component") or []
    if components:
        sys_v = dia_v = None
        unit = "mmHg"
        for c in components:
            label = (_cc_text(c.get("code")) or "").lower()
            vq = c.get("valueQuantity") or {}
            v = vq.get("value")
            if v is None:
                continue
            if isinstance(v, float) and v.is_integer():
                v = int(v)
            u = vq.get("unit")
            if "systolic" in label:
                sys_v, unit = v, u or unit
            elif "diastolic" in label:
                dia_v, unit = v, u or unit
        if sys_v is not None and dia_v is not None:
            return f"BP {sys_v}/{dia_v} {unit}".rstrip()

    qty = _qty_str(r.get("valueQuantity"))
    if qty:
        return f"{name} {qty}"

    vc_text = _cc_text(r.get("valueCodeableConcept"))
    if vc_text:
        return f"{name}: {vc_text}"

    return name


def _family_hx_label(r: dict) -> str:
    rel = _cc_text(r.get("relationship")) or "family"
    conditions = r.get("condition") or []
    if conditions and isinstance(conditions[0], dict):
        c = conditions[0]
        cond = _cc_text(c.get("code"))
        onset = ""
        oa = c.get("onsetAge") or {}
        if isinstance(oa, dict) and oa.get("value") is not None:
            ov = oa["value"]
            if isinstance(ov, float) and ov.is_integer():
                ov = int(ov)
            onset = f" (onset {ov})"
        elif c.get("onsetString"):
            onset = f" ({c['onsetString']})"
        if cond:
            return f"{rel} — {cond}{onset}"
    return rel


def _allergy_label(r: dict) -> str:
    name = _cc_text(r.get("code")) or "allergy"
    reactions = r.get("reaction") or []
    if reactions and isinstance(reactions[0], dict):
        m = reactions[0].get("manifestation") or []
        if m and isinstance(m[0], dict):
            mt = _cc_text(m[0])
            if mt:
                return f"{name} ({mt})"
    return name


def _display_label(resource: dict) -> str:
    rt = resource.get("resourceType")
    if rt == "Observation":
        return _observation_label(resource)
    if rt == "FamilyMemberHistory":
        return _family_hx_label(resource)
    if rt == "AllergyIntolerance":
        return _allergy_label(resource)
    for path in ("code", "medicationCodeableConcept", "relationship"):
        text = _cc_text(resource.get(path))
        if text:
            return text
    return rt or "unknown"


def _proposal_to_record(proposal, run_id: str, patient_id: str) -> ProposalRecord:
    metadata = {
        "classification_reasoning": proposal.classification_reasoning,
        "extraction_reasoning": proposal.extraction_reasoning,
        "merge_reasoning": proposal.merge_reasoning,
        "flags": proposal.flags,
        "confidence_breakdown": proposal.confidence_breakdown.model_dump(mode="json") if proposal.confidence_breakdown else None,
        "chart_matches": [m.model_dump(mode="json") for m in proposal.chart_matches],
        "supersedes": proposal.supersedes,
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
        d["confidence_breakdown"] = metadata.get("confidence_breakdown")
        d["chart_matches"] = metadata.get("chart_matches", [])
        d["supersedes"] = metadata.get("supersedes", [])
        d["reviewed_at"] = record.reviewed_at.replace(tzinfo=timezone.utc).isoformat() if record.reviewed_at else None
        d["reviewed_by"] = record.reviewed_by
        d["rejection_reason"] = metadata.get("rejection_reason")
        d["provenance_resource"] = metadata.get("provenance_resource")
        d["write_result"] = metadata.get("write_result")
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
    """Run the augmentation pipeline against the patient's chart-resident notes.

    Pulls the existing PatientContext + DocumentReferences via `_load_source`
    (live FHIR if `fhir_client` is provided; local demo bundle otherwise),
    runs the doc guardrail and Stages 2 - 6 via `_execute_stages`, and
    persists proposals + run metadata.

    Returns a summary dict with `run_id`, `total`, `by_tier` counts, and
    cost / duration stats from `run_stats`. If pending proposals already
    exist for this patient, returns the cached run summary instead of
    re-running (the ~25s pipeline is expensive to repeat).
    """
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
            from services import run_snapshot
            if run_snapshot.read(row.run_id) is None:
                try:
                    pc, docs = await _load_source(effective_patient_id, fhir_client=fhir_client)
                    run_snapshot.write(row.run_id, pc, docs)
                except Exception as exc:
                    log.warning("snapshot backfill failed for run %s: %s", row.run_id, exc)
            new_fhir_meta = _fhir_meta_from_client(fhir_client)
            if new_fhir_meta:
                await _update_run_fhir_meta(session, row.run_id, new_fhir_meta)
            return {
                "run_id": row.run_id,
                "patient_id": effective_patient_id,
                "total": len(all_rows),
                "by_tier": by_tier,
                "cached": True,
                **(await run_stats(row.run_id, session)),
            }

    patient_context, documents = await _load_source(effective_patient_id, fhir_client=fhir_client)
    return await _run_with_documents(
        patient_context, documents, session,
        triggered_by="api", fhir_meta=_fhir_meta_from_client(fhir_client),
    )


async def run_pipeline_with_inline_notes(
    patient_id: str | None,
    raw_notes: list[str],
    session: AsyncSession,
    *,
    note_type: str = "External record",
    note_date: str | None = None,
    fhir_client=None,
) -> dict:
    """Augmentation pipeline against agent-supplied note text.

    Reconciles findings against the patient's existing FHIR chart, but does
    not pull DocumentReferences from the server — the supplied `raw_notes`
    are the only source documents for this run. The source documents are
    written to FHIR only when the clinician accepts a derived augmentation.
    """
    if not raw_notes:
        raise ValueError("raw_notes must contain at least one note")

    patient_context, _ = await _load_source(patient_id, fhir_client=fhir_client)
    documents = _documents_from_notes(raw_notes, note_type, note_date)
    return await _run_with_documents(
        patient_context, documents, session,
        triggered_by="api:inline", fhir_meta=_fhir_meta_from_client(fhir_client),
    )


async def _run_with_documents(
    patient_context,
    documents: list[Document],
    session: AsyncSession,
    *,
    triggered_by: str,
    fhir_meta: dict | None = None,
) -> dict:
    effective_patient_id = patient_context.patient["id"]
    name_parts = (patient_context.patient.get("name") or [{}])[0]
    given = " ".join(name_parts.get("given") or [])
    family = name_parts.get("family") or ""
    patient_name = f"{given} {family}".strip() or None

    from core import telemetry
    from services import run_snapshot

    run_id = short_id("run")
    meta: dict = {"doc_count": len(documents)}
    if fhir_meta:
        meta["fhir"] = fhir_meta
    await telemetry.start_run(
        run_id=run_id,
        patient_id=effective_patient_id,
        patient_name=patient_name,
        triggered_by=triggered_by,
        meta=meta,
    )
    run_snapshot.write(run_id, patient_context, documents)

    try:
        stage6 = await _execute_stages(patient_context, documents)
        for proposal in stage6.proposals:
            session.add(_proposal_to_record(proposal, run_id, effective_patient_id))
        await session.commit()
    except Exception as exc:
        await telemetry.finish_run("failed", error=str(exc))
        raise

    await telemetry.finish_run("completed")

    by_tier: dict[str, int] = {}
    for p in stage6.proposals:
        by_tier[p.confidence_tier] = by_tier.get(p.confidence_tier, 0) + 1

    log.info("pipeline run %s: %d proposals for %s", run_id, len(stage6.proposals), effective_patient_id)

    return {
        "run_id": run_id,
        "patient_id": effective_patient_id,
        "total": len(stage6.proposals),
        "by_tier": by_tier,
        "cached": False,
        **(await run_stats(run_id, session)),
    }


async def start_pipeline_background(
    patient_id: str | None,
    *,
    fhir_client=None,
    triggered_by: str = "mcp",
) -> dict:
    from fhir.local_bundle import load_demo_data
    import asyncio as _aio

    if fhir_client and patient_id:
        from fhir.read import read_documents, read_patient_context
        pc, docs = await _aio.gather(
            read_patient_context(fhir_client, patient_id),
            read_documents(fhir_client, patient_id),
        )
    else:
        pc, docs = load_demo_data()

    effective_patient_id = pc.patient["id"]
    name_parts = (pc.patient.get("name") or [{}])[0]
    given = " ".join(name_parts.get("given") or [])
    family = name_parts.get("family") or ""
    patient_name = f"{given} {family}".strip() or None

    from core import telemetry
    from services import run_snapshot

    fhir_meta = None
    if fhir_client is not None:
        fhir_meta = {"base_url": fhir_client.base_url, "token": fhir_client.token}

    run_id = short_id("run")
    meta: dict = {"doc_count": len(docs)}
    if fhir_meta:
        meta["fhir"] = fhir_meta
    await telemetry.start_run(
        run_id=run_id,
        patient_id=effective_patient_id,
        patient_name=patient_name,
        triggered_by=triggered_by,
        meta=meta,
    )
    run_snapshot.write(run_id, pc, docs)

    async def _background():
        from db import AsyncSessionLocal as _ASL
        try:
            stage6 = await _execute_stages(pc, docs)
            async with _ASL() as session:
                for proposal in stage6.proposals:
                    session.add(_proposal_to_record(proposal, run_id, effective_patient_id))
                await session.commit()
            await telemetry.finish_run("completed")
            log.info("background run %s: %d proposals", run_id, len(stage6.proposals))
        except Exception as exc:
            log.exception("background run %s failed", run_id)
            await telemetry.finish_run("failed", error=str(exc))

    import asyncio
    asyncio.create_task(_background())

    return {
        "run_id": run_id,
        "patient_id": effective_patient_id,
        "patient_name": patient_name,
    }


async def _update_progress(stage_name: str, detail: dict | None = None) -> None:
    from sqlalchemy import select, update
    from core import telemetry
    from db import AsyncSessionLocal, PipelineRun

    run = telemetry.current_run()
    if run is None:
        return
    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(PipelineRun).where(PipelineRun.id == run.run_id)
        )).scalar_one_or_none()
        if row is None:
            return
        try:
            meta = json.loads(row.meta_json) if row.meta_json else {}
        except json.JSONDecodeError:
            meta = {}
        progress = meta.get("progress", {"stages_completed": []})
        progress["current_stage"] = stage_name
        if detail:
            progress["stages_completed"].append({"name": stage_name, **detail})
        meta["progress"] = progress
        row.meta_json = json.dumps(meta, default=str)
        await session.commit()


async def _execute_stages(patient_context, documents: list[Document]):
    from openai import AsyncOpenAI

    from config import settings
    from core.augment import assemble_proposals
    from core.cache import JsonCache
    from core.code_candidates import code_candidates
    from core.doc_guardrails import RejectedDocument, screen_documents
    from core.extraction import extract_candidates_batch, merge_across_notes
    from core.preprocess import preprocess_documents
    from core.reconcile import reconcile

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    model = settings.openai_model_fast
    cache_dir = Path(__file__).resolve().parent.parent / ".cache"

    await _update_progress("guardrail")
    if settings.doc_guardrail_enabled and documents:
        guardrail_cache = JsonCache(cache_dir / "doc_guardrail")
        documents, rejected = await screen_documents(
            documents, client, model=settings.openai_model_nano, cache=guardrail_cache,
        )
        await _record_guardrail_outcome(documents, rejected)
    await _update_progress("guardrail", {"documents_accepted": len(documents)})

    await _update_progress("stage1_preprocess")
    notes = preprocess_documents(documents)
    total_sentences = sum(len(n.sentences) for n in notes)
    await _update_progress("stage1_preprocess", {"sentences": total_sentences})

    await _update_progress("stage2_extract")
    stage2_cache = JsonCache(cache_dir / "stage2_output")
    stage2 = await extract_candidates_batch(notes, client, model=model, cache=stage2_cache)
    total_candidates = sum(
        sum(len(v) for v in s.candidates.values()) for s in stage2
    )
    await _update_progress("stage2_extract", {"candidates": total_candidates})

    await _update_progress("stage3_merge")
    stage3_cache = JsonCache(cache_dir / "stage3")
    stage3 = await merge_across_notes(stage2, client, model=model, cache=stage3_cache)
    await _update_progress("stage3_merge", {"candidates": len(stage3.candidates)})

    await _update_progress("stage4_code")
    stage4 = await code_candidates(stage3, client, model=model)
    await _update_progress("stage4_code", {"coded": len(stage4.candidates)})

    await _update_progress("stage5_reconcile")
    stage5 = await reconcile(stage4, patient_context, client, model=model)
    verdicts: dict[str, int] = {}
    for r in stage5.results:
        verdicts[r.classification] = verdicts.get(r.classification, 0) + 1
    await _update_progress("stage5_reconcile", verdicts)

    await _update_progress("stage6_assemble")
    result = assemble_proposals(stage5, notes, patient_context)
    await _update_progress("stage6_assemble", {"proposals": len(result.proposals)})
    return result


async def _record_guardrail_outcome(accepted, rejected) -> None:
    """Persist guardrail outcome on the active run's meta_json."""
    from sqlalchemy import select

    from core import telemetry
    from db import AsyncSessionLocal, PipelineRun

    run = telemetry.current_run()
    if run is None:
        return

    async with AsyncSessionLocal() as session:
        row = (await session.execute(
            select(PipelineRun).where(PipelineRun.id == run.run_id)
        )).scalar_one_or_none()
        if row is None:
            return
        try:
            meta = json.loads(row.meta_json) if row.meta_json else {}
        except json.JSONDecodeError:
            meta = {}
        if not isinstance(meta, dict):
            meta = {}
        meta["guardrail"] = {
            "accepted": len(accepted),
            "rejected": [r.to_dict() for r in rejected],
        }
        row.meta_json = json.dumps(meta, default=str)
        await session.commit()

    if rejected:
        await telemetry.log_event("doc_guardrail_rejected", {
            "rejected": [r.to_dict() for r in rejected],
        })


async def list_proposals(
    session: AsyncSession,
    *,
    patient_id: str | None = None,
    run_id: str | None = None,
) -> list[dict]:
    """List proposals, sorted ATTENTION -> REVIEW -> CONFIDENT then by score.

    At least one of `patient_id` or `run_id` is required. Returns the
    summary (`_record_to_dict` non-full) form for each proposal.
    """
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
    """Fetch the full proposal detail (resource JSON, citations, metadata)."""
    record = await session.get(ProposalRecord, proposal_id)
    if not record:
        raise ValueError(f"proposal {proposal_id} not found")
    return _record_to_dict(record, full=True)


async def accept_proposal(
    proposal_id: str,
    session: AsyncSession,
    *,
    fhir_client=None,
    reviewer: ReviewerIdentity | None = None,
) -> dict:
    """Accept a pending proposal and write to FHIR if a client is available.

    Side effects:
      * Status `pending` -> `accepted` (only `pending` accepted; raises
        otherwise — e.g. you cannot re-accept an already-accepted proposal).
      * Records `reviewed_at` and `reviewed_by` (from the SHARP-aliased
        ReviewerIdentity).
      * If `fhir_client` is provided, calls `apply_augmentation` to write the
        FHIR resource + Provenance (and US Core DocumentReference for inline
        notes) as a single transaction Bundle. Stores the returned
        `WriteResult` references in the proposal's audit metadata.
      * If no `fhir_client`, the proposal is marked accepted but no chart
        write happens (offline / demo path).

    Returns the updated proposal dict (full form).
    """
    record = await session.get(ProposalRecord, proposal_id)
    if not record:
        raise ValueError(f"proposal {proposal_id} not found")
    if record.status != "pending":
        raise ValueError(f"proposal {proposal_id} is already {record.status}")

    record.status = "accepted"
    record.reviewed_at = datetime.now(timezone.utc)
    record.reviewed_by = reviewer.display if reviewer else None

    from fhir.write import Citation, build_provenance
    from services import run_snapshot

    raw_citations = json.loads(record.citations_json)
    snapshot = run_snapshot.read(record.run_id)
    snapshot_docs: dict[str, Document] = (
        {d.id: d for d in snapshot[1]} if snapshot else {}
    )
    citations: list[Citation] = []
    for c in raw_citations:
        doc_id = c["document_id"]
        inline_doc = (
            snapshot_docs.get(doc_id)
            if doc_id.startswith(INLINE_DOC_PREFIX) else None
        )
        citations.append(Citation(
            document_ref=f"DocumentReference/{doc_id}",
            start=c["char_start"],
            end=c["char_end"],
            text=c["text"],
            inline_document=inline_doc,
        ))

    metadata = json.loads(record.metadata_json)
    supersedes = metadata.get("supersedes", [])

    write_result = None
    if fhir_client:
        from fhir.write import AugmentationProposal as WriteProposal, apply_augmentation
        wp = WriteProposal(
            classification=record.classification,
            resource=json.loads(record.resource_json),
            citations=citations,
            supersedes_ref=supersedes[0] if supersedes else None,
        )
        result = await apply_augmentation(
            fhir_client, wp, attester=reviewer, patient_id=record.patient_id,
        )
        write_result = {
            "resource_ref": result.resource_ref,
            "provenance_ref": result.provenance_ref,
            "superseded_ref": result.superseded_ref,
        }
        target_urn = result.resource_ref or f"urn:local:{record.id}"
    else:
        target_urn = f"urn:local:{record.id}"

    activity_code = "UPDATE" if record.classification == "UPDATING" else "CREATE"
    provenance_resource = build_provenance(
        target_urn, citations, activity_code=activity_code, attester=reviewer,
    )
    metadata["provenance_resource"] = provenance_resource
    if write_result:
        metadata["write_result"] = write_result
    record.metadata_json = json.dumps(metadata)

    await session.commit()

    return {
        "id": record.id,
        "status": "accepted",
        "write_result": write_result,
        "provenance_resource": provenance_resource,
    }


async def reject_proposal(
    proposal_id: str,
    reason: str,
    session: AsyncSession,
    *,
    reviewer: ReviewerIdentity | None = None,
) -> dict:
    """Reject a pending proposal with a clinician-supplied reason.

    Status `pending` -> `rejected`. The reason is stored in the proposal's
    `metadata_json["rejection_reason"]`. No FHIR write occurs.
    """
    record = await session.get(ProposalRecord, proposal_id)
    if not record:
        raise ValueError(f"proposal {proposal_id} not found")
    if record.status != "pending":
        raise ValueError(f"proposal {proposal_id} is already {record.status}")

    record.status = "rejected"
    record.reviewed_at = datetime.now(timezone.utc)
    record.reviewed_by = reviewer.display if reviewer else None

    metadata = json.loads(record.metadata_json)
    metadata["rejection_reason"] = reason
    record.metadata_json = json.dumps(metadata)

    await session.commit()

    return {"id": record.id, "status": "rejected", "reason": reason}


async def reopen_proposal(proposal_id: str, session: AsyncSession) -> dict:
    """Return a previously rejected proposal to `pending` for re-review.

    Accepted proposals cannot be reopened — the FHIR write is permanent and
    a new proposal would be needed to express a reversal. The prior rejection
    (reason, reviewer, timestamp) is preserved in
    `metadata_json["decision_history"]` so the audit trail survives.
    """
    record = await session.get(ProposalRecord, proposal_id)
    if not record:
        raise ValueError(f"proposal {proposal_id} not found")
    if record.status == "accepted":
        raise ValueError("accepted proposals cannot be reopened — the FHIR write is permanent")
    if record.status != "rejected":
        raise ValueError(f"proposal {proposal_id} is already {record.status}")

    metadata = json.loads(record.metadata_json)
    history = metadata.setdefault("decision_history", [])
    history.append({
        "action": "rejected",
        "reason": metadata.get("rejection_reason"),
        "by": record.reviewed_by,
        "at": record.reviewed_at.replace(tzinfo=timezone.utc).isoformat() if record.reviewed_at else None,
    })
    metadata.pop("rejection_reason", None)
    record.metadata_json = json.dumps(metadata)

    record.status = "pending"
    record.reviewed_at = None
    record.reviewed_by = None

    await session.commit()

    return {"id": record.id, "status": "pending"}


async def edit_proposal(
    proposal_id: str,
    updated_resource: dict,
    session: AsyncSession,
) -> dict:
    """Replace a pending proposal's FHIR resource JSON.

    Only the resource body is mutable — citations, classification, chart
    matches, and confidence carry forward unchanged. The proposal must be in
    `pending` status; once accepted or rejected, edits are not allowed.
    """
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
