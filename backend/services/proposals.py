"""Stateless service layer for the in-host review app.

No PHI is persisted. The pipeline runs in memory; proposals + source notes are
returned to the caller and held briefly in an in-process TTL cache
(`services.session_cache`). The durable store is FHIR (resource + Provenance).
No DB rows persist: telemetry is JSONL-only and decisions are logged (not stored).

Entry points:
  * `run_extraction_ephemeral` — run the pipeline, return proposals + notes.
  * `accept_augmentation` — write an accepted proposal to FHIR with Provenance.
  * `record_decision` — emit a non-PHI structured log line.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from core.ids import short_id
from core.schemas import RESOURCE_TYPES
from fhir.models import Document

if TYPE_CHECKING:
    from context.auth import ReviewerIdentity

log = logging.getLogger(__name__)

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


# ---------------------------------------------------------------------------
# Display helpers — FHIR resource dict -> human-readable label for the UI.
# ---------------------------------------------------------------------------

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


def _proposal_to_dict(proposal, run_id: str) -> dict:
    """Shape a stage-6 proposal into the review-app's full proposal dict."""
    return {
        "id": proposal.id,
        "run_id": run_id,
        "resource_type": proposal.resource_type,
        "classification": proposal.classification,
        "confidence_tier": proposal.confidence_tier,
        "confidence_score": round(float(proposal.confidence_score), 3),
        "status": "pending",
        "display_label": _display_label(proposal.resource),
        "flags": proposal.flags,
        "conflict_group_id": proposal.conflict_group_id,
        "resource": proposal.resource,
        "citations": [c.model_dump(mode="json") for c in proposal.citations],
        "classification_reasoning": proposal.classification_reasoning,
        "extraction_reasoning": proposal.extraction_reasoning,
        "merge_reasoning": proposal.merge_reasoning,
        "confidence_breakdown": (
            proposal.confidence_breakdown.model_dump(mode="json")
            if proposal.confidence_breakdown else None
        ),
        "chart_matches": [m.model_dump(mode="json") for m in proposal.chart_matches],
        "supersedes": proposal.supersedes,
        "conformance": proposal.conformance,
        "reviewed_at": None,
        "reviewed_by": None,
        "rejection_reason": None,
        "provenance_resource": None,
        "write_result": None,
    }


def _filter_disabled_types(stage2: list, effective) -> list:
    """Drop stage-2 candidates for resource types the active preset disabled.
    No-op when every type is enabled (the unconfigured default), so the stage-2
    cache key stays preset-independent."""
    enabled = {rt for rt in RESOURCE_TYPES if effective.rule(rt).enabled}
    if len(enabled) == len(RESOURCE_TYPES):
        return stage2
    for s in stage2:
        s.candidates = {t: v for t, v in s.candidates.items() if t in enabled}
    return stage2


async def _run_with_heartbeat(emit, stage: str, coro, *, interval: float = 15.0):
    """Await `coro` while emitting a `stage` progress ping every `interval`s.

    Stage 2 (extract) and Stage 4 (code) can run tens of seconds with no natural
    progress event; the MCP client resets its request timeout on each progress
    notification, so a heartbeat keeps a long stage from tripping the 60s cap."""
    async def beat():
        while True:
            await asyncio.sleep(interval)
            await emit(stage)

    hb = asyncio.create_task(beat())
    try:
        return await coro
    finally:
        hb.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await hb


async def _execute_stages(
    patient_context,
    documents: list[Document],
    *,
    progress_cb=None,
    use_cache: bool = False,
    gemini_api_key: str | None = None,
    effective=None,
):
    """Run Stages (guardrail → assemble) and return the assembled proposals.

    Pure computation: persists nothing. `progress_cb(stage, detail)` receives
    stage progress (routed to the MCP request). When `use_cache` is False, no
    extracted clinical data touches disk (no-PHI-at-rest contract).
    """
    from config import settings
    from core.augment import assemble_proposals
    from core.cache import JsonCache
    from core.code_candidates import code_candidates
    from core.doc_guardrails import screen_documents
    from core.extraction import extract_candidates_batch, merge_across_notes
    from core.llm import build_client
    from core.preprocess import preprocess_documents
    from core.reconcile import reconcile

    async def emit(stage: str, detail: dict | None = None) -> None:
        if progress_cb is not None:
            await progress_cb(stage, detail)

    client = build_client(gemini_api_key)
    model = settings.gemini_model_fast
    cache_dir = Path(__file__).resolve().parent.parent / ".cache"

    def _cache(name: str) -> "JsonCache | None":
        return JsonCache(cache_dir / name) if use_cache else None

    await emit("guardrail")
    if settings.doc_guardrail_enabled and documents:
        documents, _rejected = await screen_documents(
            documents, client, model=settings.gemini_model_nano, cache=_cache("doc_guardrail"),
        )
    await emit("guardrail", {"documents_accepted": len(documents)})

    await emit("stage1_preprocess")
    notes = preprocess_documents(documents)
    total_sentences = sum(len(n.sentences) for n in notes)
    await emit("stage1_preprocess", {"sentences": total_sentences})

    await emit("stage2_extract")
    stage2 = await _run_with_heartbeat(emit, "stage2_extract", extract_candidates_batch(
        notes, client, model=model, cache=_cache("stage2_output"), effective=effective))
    stage2 = _filter_disabled_types(stage2, effective)
    total_candidates = sum(
        sum(len(v) for v in s.candidates.values()) for s in stage2
    )
    await emit("stage2_extract", {"candidates": total_candidates})

    await emit("stage3_merge")
    stage3 = await merge_across_notes(stage2, client, model=model, cache=_cache("stage3"), effective=effective)
    await emit("stage3_merge", {"candidates": len(stage3.candidates)})

    await emit("stage4_code")
    stage4 = await _run_with_heartbeat(emit, "stage4_code", code_candidates(
        stage3, client, model=model, effective=effective))
    await emit("stage4_code", {"coded": len(stage4.candidates)})

    await emit("stage5_reconcile")
    stage5 = await reconcile(stage4, patient_context, client, model=model)
    verdicts: dict[str, int] = {}
    for r in stage5.results:
        verdicts[r.classification] = verdicts.get(r.classification, 0) + 1
    await emit("stage5_reconcile", verdicts)

    await emit("stage6_assemble")
    result = assemble_proposals(stage5, notes, patient_context, effective=effective)
    await emit("stage6_assemble", {"proposals": len(result.proposals)})
    return result


async def run_extraction_ephemeral(
    patient_id: str | None,
    *,
    fhir_client=None,
    inline_notes: list[str] | None = None,
    note_type: str = "External record",
    note_date: str | None = None,
    tenant_key: str | None = None,
    triggered_by: str = "mcp:app",
    progress_cb=None,
    gemini_api_key: str | None = None,
    user_key: str | None = None,
    workspace_id: str | None = None,
    effective=None,
) -> dict:
    from core import telemetry
    from core.effective_profile import resolve_effective_profile
    from services import session_cache

    if effective is None:
        effective = resolve_effective_profile(None)

    patient_context, chart_docs = await _load_source(patient_id, fhir_client=fhir_client)
    documents = (
        _documents_from_notes(inline_notes, note_type, note_date)
        if inline_notes else chart_docs
    )
    effective_patient_id = patient_context.patient["id"]

    run_id = short_id("run")
    await telemetry.start_run(
        run_id=run_id,
        patient_id=None,
        patient_name=None,
        triggered_by=triggered_by,
        meta={"tenant": tenant_key, "doc_count": len(documents)},
    )
    try:
        stage6 = await _execute_stages(
            patient_context, documents, progress_cb=progress_cb, use_cache=False,
            gemini_api_key=gemini_api_key, effective=effective,
        )
    except Exception as exc:
        await telemetry.finish_run("failed", error=str(exc))
        raise
    run_ctx = telemetry.current_run()
    agg = _run_aggregate(run_ctx, len(documents))
    await telemetry.finish_run("completed")

    if user_key:
        from config import settings
        from services import usage
        try:
            await usage.record_run(
                user_key=user_key, workspace_id=workspace_id,
                model=settings.gemini_model_fast, triggered_by=triggered_by,
                input_tokens=agg["input_tokens"], output_tokens=agg["output_tokens"],
                reasoning_tokens=agg["reasoning_tokens"], cost_usd=agg["cost_usd"],
                duration_ms=agg["duration_ms"], doc_count=agg["doc_count"],
            )
        except Exception as exc:  # ledger is best-effort; never fail a run on it
            log.warning("usage ledger write failed: %s", exc)

    stats = {
        "duration_ms": agg["duration_ms"],
        "total_documents": agg["doc_count"],
        "total_cost_usd": round(float(agg["cost_usd"]), 4),
        "input_tokens": agg["input_tokens"],
        "output_tokens": agg["output_tokens"],
    }

    proposals = [_proposal_to_dict(p, run_id) for p in stage6.proposals]
    session_cache.put(run_id, {
        "patient_id": effective_patient_id,
        "documents": {d.id: d for d in documents},
        "proposals": {p["id"]: p for p in proposals},
    })

    return {
        "run_id": run_id,
        "patient_id": effective_patient_id,
        "documents": [d.__dict__ for d in documents],
        "proposals": proposals,
        "stats": stats,
    }


def _run_aggregate(run_ctx, doc_count: int) -> dict:
    """Token / cost / duration totals for a run, from the telemetry buffer."""
    from decimal import Decimal

    inp = out = rea = 0
    cost = Decimal("0")
    duration_ms: int | None = None
    if run_ctx is not None:
        for c in run_ctx.call_buffer:
            inp += int(c.get("input_tokens") or 0)
            out += int(c.get("output_tokens") or 0)
            rea += int(c.get("reasoning_tokens") or 0)
            try:
                cost += Decimal(str(c.get("usd_cost") or 0))
            except (TypeError, ValueError, ArithmeticError):
                pass
        finished = max(
            (c.get("finished_at") for c in run_ctx.call_buffer if c.get("finished_at")),
            default=None,
        )
        if finished and run_ctx.started_at:
            duration_ms = int((finished - run_ctx.started_at).total_seconds() * 1000)
    return {
        "input_tokens": inp, "output_tokens": out, "reasoning_tokens": rea,
        "cost_usd": cost, "duration_ms": duration_ms, "doc_count": doc_count,
    }


async def accept_augmentation(
    *,
    fhir_client,
    reviewer: ReviewerIdentity | None,
    patient_id: str | None,
    run_id: str | None = None,
    proposal_id: str | None = None,
    resource: dict | None = None,
    citations: list[dict] | None = None,
    classification: str = "NEW",
    supersedes: list[str] | None = None,
    effective=None,
) -> dict:
    """Write an accepted augmentation to FHIR with Provenance. Stores no PHI.

    Resolves the proposal from the in-process cache (run_id + proposal_id) when
    available, else from the supplied payload. Logs a non-PHI decision line.
    """
    from fhir.write import (
        AugmentationProposal as WriteProposal,
        Citation,
        apply_augmentation,
        build_provenance,
    )
    from services import session_cache

    inline_docs: dict[str, Document] = {}
    if run_id and proposal_id:
        cached = session_cache.get(run_id)
        if cached and proposal_id in cached["proposals"]:
            p = cached["proposals"][proposal_id]
            resource = resource or p["resource"]
            citations = citations or p["citations"]
            classification = p.get("classification", classification)
            supersedes = supersedes if supersedes is not None else p.get("supersedes", [])
            inline_docs = cached.get("documents", {})

    if resource is None:
        raise ValueError("resource not found in cache and not supplied")
    citations = citations or []
    supersedes = supersedes or []

    built: list[Citation] = []
    for c in citations:
        doc_id = c["document_id"]
        inline_doc = inline_docs.get(doc_id) if doc_id.startswith(INLINE_DOC_PREFIX) else None
        built.append(Citation(
            document_ref=f"DocumentReference/{doc_id}",
            start=c["char_start"],
            end=c["char_end"],
            text=c["text"],
            inline_document=inline_doc,
        ))

    conformance = None
    if fhir_client:
        from config import settings
        from fhir.conformance import assess_conformance, validator_client
        rt = resource.get("resourceType")
        rule = effective.rule(rt) if effective is not None else None
        allowed_systems = rule.coding_systems if rule is not None else None
        pinned = rule.pinned if rule is not None else None
        fixed = rule.fixed if rule is not None else None
        profiles = (resource.get("meta") or {}).get("profile") or []
        conformance = await assess_conformance(
            resource,
            profiles=profiles,
            allowed_systems=allowed_systems,
            pinned=pinned,
            fixed=fixed,
            target_client=fhir_client,
            validator=validator_client(),
        )
        if settings.validate_before_write and conformance["valid"] is False:
            raise ValueError(f"conformance gate failed ({conformance['level']}): {conformance['issues'][:3]}")

    write_result = None
    local_id = proposal_id or short_id("aug")
    if fhir_client:
        wp = WriteProposal(
            classification=classification,
            resource=resource,
            citations=built,
            supersedes_ref=supersedes[0] if supersedes else None,
        )
        result = await apply_augmentation(
            fhir_client, wp, attester=reviewer, patient_id=patient_id,
        )
        write_result = {
            "resource_ref": result.resource_ref,
            "provenance_ref": result.provenance_ref,
            "superseded_ref": result.superseded_ref,
        }
        target_urn = result.resource_ref or f"urn:local:{local_id}"
    else:
        target_urn = f"urn:local:{local_id}"

    activity_code = "UPDATE" if classification == "UPDATING" else "CREATE"
    provenance_resource = build_provenance(
        target_urn, built, activity_code=activity_code, attester=reviewer,
    )

    await record_decision(
        action="accept",
        run_id=run_id,
        resource_type=resource.get("resourceType"),
        reviewer=reviewer.display if reviewer else None,
        resource_ref=write_result["resource_ref"] if write_result else None,
    )

    return {
        "id": local_id,
        "status": "accepted",
        "write_result": write_result,
        "provenance_resource": provenance_resource,
        "conformance": conformance,
    }


async def record_decision(
    *,
    action: str,
    run_id: str | None,
    resource_type: str | None = None,
    reviewer: str | None = None,
    resource_ref: str | None = None,
    reason: str | None = None,
) -> None:
    # Non-PHI structured log only (no DB). The durable clinical record is the
    # FHIR Provenance written on accept. `reason` is clinician free-text
    # (potential PHI) and is intentionally not logged.
    _ = reason
    log.info(
        "decision action=%s run=%s resource_type=%s reviewer=%s ref=%s",
        action, run_id, resource_type, reviewer, resource_ref,
    )
