"""Usage ledger: per-run rows aggregate into a per-clinician summary."""
import asyncio
import uuid
from decimal import Decimal

from db import init_db
from services import usage


def _sub() -> str:
    return f"sub-{uuid.uuid4().hex}"


def test_record_summary_and_list():
    sub = _sub()

    async def run():
        await init_db()
        await usage.record_run(
            user_key=sub, workspace_id="ws-1", model="gemini-3.5-flash",
            input_tokens=1000, output_tokens=200, reasoning_tokens=50,
            cost_usd=Decimal("0.0123"), duration_ms=5000, doc_count=4,
        )
        await usage.record_run(
            user_key=sub, workspace_id="ws-1", model="gemini-3.5-flash",
            input_tokens=500, output_tokens=100, reasoning_tokens=0,
            cost_usd=Decimal("0.0050"), duration_ms=3000, doc_count=2,
        )
        return await usage.summary(sub), await usage.list_runs(sub)

    summ, runs = asyncio.run(run())
    assert summ["runs"] == 2
    assert summ["input_tokens"] == 1500
    assert summ["output_tokens"] == 300
    assert abs(summ["total_cost_usd"] - 0.0173) < 1e-6
    assert len(runs) == 2 and runs[0]["model"] == "gemini-3.5-flash"
    assert runs[0]["cost_usd"] > 0 and runs[0]["doc_count"] in (2, 4)


def test_summary_is_isolated_per_user():
    a, b = _sub(), _sub()

    async def run():
        await init_db()
        await usage.record_run(
            user_key=a, workspace_id=None, model="m",
            input_tokens=10, output_tokens=1, reasoning_tokens=0,
            cost_usd=Decimal("0.001"), duration_ms=1, doc_count=1,
        )
        return await usage.summary(a), await usage.summary(b)

    sa, sb = asyncio.run(run())
    assert sa["runs"] == 1
    assert sb["runs"] == 0 and sb["total_cost_usd"] == 0.0
