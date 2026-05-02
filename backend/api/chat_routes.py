"""Chat streaming endpoint."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes import get_reviewer
from context.auth import ReviewerIdentity
from db import get_session
from services.chat import stream_chat

router = APIRouter(prefix="/api/chat")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    selected_proposal_id: str | None = None


@router.post("/{run_id}/stream")
async def chat_stream(
    run_id: str,
    body: ChatRequest,
    reviewer: ReviewerIdentity = Depends(get_reviewer),  # noqa: ARG001
    session: AsyncSession = Depends(get_session),
):
    msgs = [{"role": m.role, "content": m.content} for m in body.messages]
    gen = stream_chat(run_id, msgs, body.selected_proposal_id, session)
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
