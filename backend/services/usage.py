"""Per-run usage ledger (non-PHI): tokens, cost, duration per clinician `sub`.

Powers the BYOK "account & usage" view — this-run detail plus cumulative spend.
No patient id, no clinical content ever lands here (see db.models.UsageRun).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from core.ids import short_id


async def record_run(
    *,
    user_key: str,
    workspace_id: str | None,
    model: str | None,
    input_tokens: int,
    output_tokens: int,
    reasoning_tokens: int,
    cost_usd: Decimal,
    duration_ms: int | None,
    doc_count: int,
    status: str = "completed",
    triggered_by: str | None = None,
) -> str:
    """Insert one usage row. Returns its id."""
    from db import AsyncSessionLocal, UsageRun

    run_id = short_id("use")
    async with AsyncSessionLocal() as session:
        session.add(UsageRun(
            id=run_id,
            user_key=user_key,
            workspace_id=workspace_id,
            created_at=datetime.now(timezone.utc),
            model=model,
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            reasoning_tokens=int(reasoning_tokens),
            cost_usd=Decimal(str(cost_usd or 0)),
            duration_ms=duration_ms,
            doc_count=int(doc_count),
            status=status,
            triggered_by=triggered_by,
        ))
        await session.commit()
    return run_id


async def summary(user_key: str) -> dict:
    """Cumulative totals for one clinician."""
    from sqlalchemy import func, select

    from db import AsyncSessionLocal, UsageRun

    async with AsyncSessionLocal() as session:
        stmt = select(
            func.count(UsageRun.id),
            func.coalesce(func.sum(UsageRun.cost_usd), 0),
            func.coalesce(func.sum(UsageRun.input_tokens), 0),
            func.coalesce(func.sum(UsageRun.output_tokens), 0),
        ).where(UsageRun.user_key == user_key)
        runs, cost, inp, out = (await session.execute(stmt)).one()
    return {
        "runs": int(runs),
        "total_cost_usd": float(cost),
        "input_tokens": int(inp),
        "output_tokens": int(out),
    }


async def list_runs(user_key: str, limit: int = 50) -> list[dict]:
    """Most recent runs for one clinician, newest first."""
    from sqlalchemy import select

    from db import AsyncSessionLocal, UsageRun

    async with AsyncSessionLocal() as session:
        stmt = (
            select(UsageRun)
            .where(UsageRun.user_key == user_key)
            .order_by(UsageRun.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
        rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": r.id,
            "ts": r.created_at.isoformat(),
            "model": r.model,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost_usd": float(r.cost_usd),
            "duration_ms": r.duration_ms,
            "doc_count": r.doc_count,
            "status": r.status,
        }
        for r in rows
    ]
