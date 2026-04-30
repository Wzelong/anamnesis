"""REST API routes for the frontend review workspace."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_session
from services import proposals as proposal_svc

router = APIRouter(prefix="/api")


class RunPipelineRequest(BaseModel):
    patient_id: str | None = None


class RejectRequest(BaseModel):
    reason: str
    reviewer: str | None = None


class AcceptRequest(BaseModel):
    reviewer: str | None = None


class EditRequest(BaseModel):
    resource: dict


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
    body: AcceptRequest = AcceptRequest(),
    session: AsyncSession = Depends(get_session),
):
    try:
        return await proposal_svc.accept_proposal(
            proposal_id, session, reviewer=body.reviewer,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/proposals/{proposal_id}/reject")
async def reject_proposal(
    proposal_id: str,
    body: RejectRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await proposal_svc.reject_proposal(
            proposal_id, body.reason, session, reviewer=body.reviewer,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.put("/proposals/{proposal_id}")
async def edit_proposal(
    proposal_id: str,
    body: EditRequest,
    session: AsyncSession = Depends(get_session),
):
    try:
        return await proposal_svc.edit_proposal(proposal_id, body.resource, session)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
