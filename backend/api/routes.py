"""REST API routes for the frontend review workspace."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import jwt
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import delete as sa_delete, func, select as sa_select

from context.auth import ReviewerIdentity, validate_review_token
from db import get_session
from db.models import LLMCall, PipelineRun, ProposalRecord
from services import proposals as proposal_svc

_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"

router = APIRouter(prefix="/api")


class RunPipelineRequest(BaseModel):
    patient_id: str | None = None


class RejectRequest(BaseModel):
    reason: str


class EditRequest(BaseModel):
    resource: dict


class DeleteRunsRequest(BaseModel):
    ids: list[str]


async def get_reviewer(
    authorization: str | None = Header(None),
    token: str | None = Query(None),
) -> ReviewerIdentity:
    raw = None
    if authorization and authorization.lower().startswith("bearer "):
        raw = authorization[7:]
    elif token:
        raw = token
    if not raw:
        raise HTTPException(401, "Review token required")
    try:
        return await validate_review_token(raw)
    except jwt.InvalidTokenError as e:
        raise HTTPException(401, f"Invalid review token: {e}") from e


@router.get("/auth/check")
async def check_auth(reviewer: ReviewerIdentity = Depends(get_reviewer)):
    return {"display": reviewer.display, "fhir_reference": reviewer.fhir_reference}


@router.get("/runs")
async def list_runs(session: AsyncSession = Depends(get_session)):
    runs = (await session.execute(
        sa_select(PipelineRun).order_by(PipelineRun.started_at.desc())
    )).scalars().all()
    if not runs:
        return []

    counts = (await session.execute(
        sa_select(
            ProposalRecord.run_id,
            func.count().label("total"),
            func.sum(func.iif(ProposalRecord.status == "pending", 1, 0)).label("pending"),
        ).group_by(ProposalRecord.run_id)
    )).all()
    count_map = {r.run_id: {"total": r.total, "pending": r.pending} for r in counts}

    tier_rows = (await session.execute(
        sa_select(
            ProposalRecord.run_id,
            ProposalRecord.confidence_tier,
            func.count().label("n"),
        )
        .where(ProposalRecord.status == "pending")
        .group_by(ProposalRecord.run_id, ProposalRecord.confidence_tier)
    )).all()
    tier_map: dict[str, dict[str, int]] = {}
    for row in tier_rows:
        tier_map.setdefault(row.run_id, {})[row.confidence_tier] = row.n

    cls_rows = (await session.execute(
        sa_select(
            ProposalRecord.run_id,
            ProposalRecord.classification,
            func.count().label("n"),
        )
        .where(ProposalRecord.status == "pending")
        .group_by(ProposalRecord.run_id, ProposalRecord.classification)
    )).all()
    cls_map: dict[str, dict[str, int]] = {}
    for row in cls_rows:
        cls_map.setdefault(row.run_id, {})[row.classification] = row.n

    usage_rows = (await session.execute(
        sa_select(
            LLMCall.run_id,
            func.sum(LLMCall.input_tokens + LLMCall.output_tokens).label("tokens"),
            func.sum(LLMCall.usd_cost).label("cost"),
        ).group_by(LLMCall.run_id)
    )).all()
    usage_map: dict[str, dict[str, float | int]] = {
        row.run_id: {"tokens": int(row.tokens or 0), "cost": float(row.cost or 0)}
        for row in usage_rows
    }

    doc_rows = (await session.execute(
        sa_select(
            LLMCall.run_id,
            func.count(func.distinct(LLMCall.document_id)).label("docs"),
        )
        .where(LLMCall.document_id.isnot(None))
        .group_by(LLMCall.run_id)
    )).all()
    doc_map: dict[str, int] = {row.run_id: int(row.docs or 0) for row in doc_rows}

    result = []
    for run in runs:
        c = count_map.get(run.id, {"total": 0, "pending": 0})
        total = c["total"]
        pending = c["pending"]
        if run.status == "running":
            status = "running"
        elif total == 0:
            status = "empty"
        elif pending == total:
            status = "pending"
        elif pending > 0:
            status = "in_review"
        else:
            status = "resolved"
        duration_ms = None
        if run.started_at and run.finished_at:
            duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
        usage = usage_map.get(run.id, {"tokens": 0, "cost": 0.0})
        result.append({
            "id": run.id,
            "patient_id": run.patient_id,
            "patient_name": run.patient_name,
            "status": status,
            "total_proposals": total,
            "pending_proposals": pending,
            "pending_by_tier": tier_map.get(run.id, {}),
            "pending_by_classification": cls_map.get(run.id, {}),
            "started_at": run.started_at.replace(tzinfo=timezone.utc).isoformat() if run.started_at else None,
            "duration_ms": duration_ms,
            "total_tokens": usage["tokens"],
            "total_cost_usd": usage["cost"],
            "total_documents": doc_map.get(run.id, 0),
        })
    return result


@router.get("/runs/{run_id}/progress")
async def get_run_progress(
    run_id: str,
    session: AsyncSession = Depends(get_session),
):
    run = (await session.execute(
        sa_select(PipelineRun).where(PipelineRun.id == run_id)
    )).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    meta = json.loads(run.meta_json or "{}") if run.meta_json else {}
    return {
        "status": run.status,
        "progress": meta.get("progress"),
        "started_at": run.started_at.replace(tzinfo=timezone.utc).isoformat() if run.started_at else None,
        "error": meta.get("error"),
    }


@router.get("/runs/{run_id}/documents")
async def get_run_documents(
    run_id: str,
    session: AsyncSession = Depends(get_session),
):
    source = await proposal_svc.load_run_source(run_id, session)
    if source is None:
        raise HTTPException(404, "run not found")
    _, documents = source
    return {"documents": [d.__dict__ for d in documents]}


@router.get("/runs/{run_id}/chart")
async def get_run_chart(
    run_id: str,
    session: AsyncSession = Depends(get_session),
):
    run = (await session.execute(
        sa_select(PipelineRun).where(PipelineRun.id == run_id)
    )).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")

    source = await proposal_svc.load_run_source(run_id, session)
    if source is None:
        raise HTTPException(404, "run not found")
    ctx, _ = source

    return _chart_response(run, ctx)


def _chart_response(run: PipelineRun, ctx) -> dict:
    from services import run_snapshot
    fhir_meta = proposal_svc.read_run_fhir_meta(run)
    has_snapshot = run_snapshot.read(run.id) is not None
    if fhir_meta:
        source_label = "FHIR server snapshot" if has_snapshot else "FHIR server"
    else:
        source_label = "Local bundle"

    token_expires_at = None
    if fhir_meta:
        expires = proposal_svc.fhir_token_expires_at(fhir_meta["token"])
        if expires is not None:
            token_expires_at = expires.isoformat()

    fetched_at = (
        run.started_at.replace(tzinfo=timezone.utc).isoformat()
        if run.started_at else datetime.now(timezone.utc).isoformat()
    )

    return {
        "patient": ctx.patient,
        "conditions": ctx.conditions,
        "medications": ctx.medications,
        "allergies": ctx.allergies,
        "observations": ctx.observations,
        "procedures": ctx.procedures,
        "family_history": ctx.family_history,
        "encounters": ctx.encounters,
        "practitioners": ctx.practitioners,
        "organizations": ctx.organizations,
        "documents": ctx.documents,
        "provenances": ctx.provenances,
        "source": source_label,
        "fetched_at": fetched_at,
        "live": fhir_meta is not None,
        "token_expires_at": token_expires_at,
    }


@router.post("/runs/{run_id}/chart/refresh")
async def refresh_run_chart(
    run_id: str,
    session: AsyncSession = Depends(get_session),
):
    run = (await session.execute(
        sa_select(PipelineRun).where(PipelineRun.id == run_id)
    )).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    try:
        result = await proposal_svc.refresh_run_chart(run_id, session)
    except PermissionError as exc:
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "run not found")
    ctx, _ = result
    response = _chart_response(run, ctx)
    response["fetched_at"] = datetime.now(timezone.utc).isoformat()
    return response


@router.post("/runs/delete")
async def delete_runs(
    body: DeleteRunsRequest,
    session: AsyncSession = Depends(get_session),
):
    if not body.ids:
        return {"deleted": 0}
    await session.execute(sa_delete(ProposalRecord).where(ProposalRecord.run_id.in_(body.ids)))
    await session.execute(sa_delete(LLMCall).where(LLMCall.run_id.in_(body.ids)))
    result = await session.execute(sa_delete(PipelineRun).where(PipelineRun.id.in_(body.ids)))
    await session.commit()
    from services import run_snapshot
    run_snapshot.delete_many(body.ids)
    return {"deleted": result.rowcount or 0}


@router.post("/proposals/run")
async def run_pipeline(
    body: RunPipelineRequest,
    session: AsyncSession = Depends(get_session),
):
    result = await proposal_svc.run_pipeline(body.patient_id, session)
    return result


@router.get("/proposals")
async def list_proposals(
    patient_id: str | None = None,
    run_id: str | None = None,
    session: AsyncSession = Depends(get_session),
):
    if not patient_id and not run_id:
        raise HTTPException(400, "patient_id or run_id query parameter required")
    return await proposal_svc.list_proposals(session, patient_id=patient_id, run_id=run_id)


@router.get("/proposals/{proposal_id}")
async def get_proposal(
    proposal_id: str,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await proposal_svc.get_proposal(proposal_id, session)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e


@router.post("/proposals/{proposal_id}/accept")
async def accept_proposal(
    proposal_id: str,
    reviewer: ReviewerIdentity = Depends(get_reviewer),
    session: AsyncSession = Depends(get_session),
):
    record = await session.get(ProposalRecord, proposal_id)
    if record is None:
        raise HTTPException(404, f"proposal {proposal_id} not found")
    run = (await session.execute(
        sa_select(PipelineRun).where(PipelineRun.id == record.run_id)
    )).scalar_one_or_none()

    fhir_client = None
    fhir_meta = proposal_svc.read_run_fhir_meta(run) if run else None
    if fhir_meta:
        expires = proposal_svc.fhir_token_expires_at(fhir_meta["token"])
        if expires is not None and expires <= datetime.now(timezone.utc):
            raise HTTPException(409, "FHIR access token has expired — re-run from the agent before accepting")
        from fhir.client import FhirClient
        fhir_client = FhirClient(fhir_meta["base_url"], fhir_meta["token"])

    try:
        return await proposal_svc.accept_proposal(
            proposal_id, session, fhir_client=fhir_client, reviewer=reviewer,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str,
    body: RejectRequest,
    reviewer: ReviewerIdentity = Depends(get_reviewer),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await proposal_svc.reject_proposal(
            proposal_id, body.reason, session, reviewer=reviewer,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/proposals/{proposal_id}/reopen")
async def reopen_proposal(
    proposal_id: str,
    _: ReviewerIdentity = Depends(get_reviewer),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await proposal_svc.reopen_proposal(proposal_id, session)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.put("/proposals/{proposal_id}")
async def edit_proposal(
    proposal_id: str,
    body: EditRequest,
    reviewer: ReviewerIdentity = Depends(get_reviewer),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await proposal_svc.edit_proposal(proposal_id, body.resource, session)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/reset")
async def reset(session: AsyncSession = Depends(get_session)):
    latest_run = (await session.execute(
        sa_select(PipelineRun).order_by(PipelineRun.started_at.desc()).limit(1)
    )).scalar_one_or_none()
    fhir_meta = proposal_svc.read_run_fhir_meta(latest_run) if latest_run else None

    await session.execute(text("DELETE FROM proposal"))
    await session.execute(text("DELETE FROM pipeline_run"))
    await session.commit()

    cleared = []
    for name in ("stage1", "stage2", "stage2_output", "stage3", "stage4", "stage5", "runs"):
        d = _CACHE_DIR / name
        if d.exists():
            shutil.rmtree(d)
            cleared.append(name)

    fhir_reset = None
    if fhir_meta:
        from fhir import bootstrap
        from fhir.client import FhirClient
        client = FhirClient(fhir_meta["base_url"], fhir_meta["token"])
        try:
            patient_id = await bootstrap.run(client)
            fhir_reset = {"patient_id": patient_id}
        except Exception as exc:
            fhir_reset = {"error": str(exc)}

    return {"status": "ok", "db": "cleared", "caches_cleared": cleared, "fhir_reset": fhir_reset}


_DEMO_FIXTURE_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "demo_fixture.json"


@router.post("/seed-demo")
async def seed_demo(session: AsyncSession = Depends(get_session)):
    existing = (await session.execute(
        sa_select(PipelineRun).limit(1)
    )).scalar_one_or_none()
    if existing:
        return {"run_id": existing.id}

    if not _DEMO_FIXTURE_PATH.exists():
        raise HTTPException(503, "Demo fixture not found. Run scripts.export_demo_fixture first.")

    fixture = json.loads(_DEMO_FIXTURE_PATH.read_text(encoding="utf-8"))

    await session.execute(text("DELETE FROM llm_call"))
    await session.execute(text("DELETE FROM proposal"))
    await session.execute(text("DELETE FROM pipeline_run"))
    await session.execute(text("DELETE FROM review_token"))
    await session.commit()

    for r in fixture["runs"]:
        session.add(PipelineRun(
            id=r["id"],
            patient_id=r["patient_id"],
            patient_name=r["patient_name"],
            triggered_by=r["triggered_by"],
            status=r["status"],
            started_at=datetime.fromisoformat(r["started_at"]),
            finished_at=datetime.fromisoformat(r["finished_at"]) if r["finished_at"] else None,
            meta_json=r["meta_json"],
        ))

    for p in fixture["proposals"]:
        session.add(ProposalRecord(
            id=p["id"],
            run_id=p["run_id"],
            patient_id=p["patient_id"],
            resource_type=p["resource_type"],
            classification=p["classification"],
            confidence_tier=p["confidence_tier"],
            confidence_score=Decimal(str(p["confidence_score"])),
            status=p["status"],
            resource_json=p["resource_json"],
            citations_json=p["citations_json"],
            metadata_json=p["metadata_json"],
            created_at=datetime.fromisoformat(p["created_at"]),
            reviewed_at=datetime.fromisoformat(p["reviewed_at"]) if p["reviewed_at"] else None,
            reviewed_by=p["reviewed_by"],
        ))

    for c in fixture["llm_calls"]:
        session.add(LLMCall(
            id=c["id"],
            run_id=c["run_id"],
            document_id=c["document_id"],
            stage=c["stage"],
            call_type=c["call_type"],
            model=c["model"],
            prompt_version=c["prompt_version"],
            input_tokens=c["input_tokens"],
            output_tokens=c["output_tokens"],
            reasoning_tokens=c["reasoning_tokens"],
            cached_tokens=c["cached_tokens"],
            latency_ms=c["latency_ms"],
            usd_cost=Decimal(str(c["usd_cost"])),
            status=c["status"],
            error=c["error"],
            started_at=datetime.fromisoformat(c["started_at"]),
            finished_at=datetime.fromisoformat(c["finished_at"]),
        ))

    await session.commit()

    from services import run_snapshot as snap
    snap.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    for run_id, snapshot_data in fixture.get("snapshots", {}).items():
        snap._path(run_id).write_text(
            json.dumps(snapshot_data, ensure_ascii=False), encoding="utf-8",
        )

    first_run_id = fixture["runs"][0]["id"] if fixture["runs"] else None
    return {"run_id": first_run_id}
