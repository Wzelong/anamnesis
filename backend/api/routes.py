"""REST API routes for the frontend review workspace."""
from __future__ import annotations

import shutil
from pathlib import Path

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query
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
        return validate_review_token(raw)
    except jwt.InvalidTokenError as e:
        raise HTTPException(401, f"Invalid review token: {e}") from e


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

    result = []
    for run in runs:
        c = count_map.get(run.id, {"total": 0, "pending": 0})
        total = c["total"]
        pending = c["pending"]
        if total == 0:
            status = "empty"
        elif pending == total:
            status = "pending"
        elif pending > 0:
            status = "in_review"
        else:
            status = "resolved"
        result.append({
            "id": run.id,
            "patient_id": run.patient_id,
            "patient_name": run.patient_name,
            "status": status,
            "total_proposals": total,
            "pending_proposals": pending,
            "pending_by_tier": tier_map.get(run.id, {}),
            "pending_by_classification": cls_map.get(run.id, {}),
            "started_at": run.started_at.isoformat() if run.started_at else None,
        })
    return result


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
    try:
        return await proposal_svc.accept_proposal(
            proposal_id, session, reviewer=reviewer,
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
    await session.execute(text("DELETE FROM proposal"))
    await session.execute(text("DELETE FROM pipeline_run"))
    await session.commit()

    cleared = []
    for name in ("stage1", "stage2", "stage2_output", "stage3", "stage4", "stage5"):
        d = _CACHE_DIR / name
        if d.exists():
            shutil.rmtree(d)
            cleared.append(name)

    return {"status": "ok", "db": "cleared", "caches_cleared": cleared}
