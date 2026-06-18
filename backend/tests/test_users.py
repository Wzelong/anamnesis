"""Per-clinician registration: same token `sub` is recognized across sessions.

Each test uses a fresh random `sub` so it is independent of existing DB rows.
"""
import asyncio
import uuid

from db import init_db
from services import users


def _sub() -> str:
    return f"sub-{uuid.uuid4().hex}"


def test_same_sub_recognized_across_sessions():
    sub = _sub()

    async def run():
        await init_db()
        first = await users.register_session(sub, display_name="Dr. A", workspace_id="ws-1", role="User")
        second = await users.register_session(sub, display_name="Dr. A", workspace_id="ws-1", role="User")
        return first, second

    first, second = asyncio.run(run())
    assert first["is_returning"] is False and first["seen_count"] == 1
    # seen_count -> 2 (not reset to 1) proves the 2nd session resolved the SAME
    # row by sub, i.e. recognized as the same clinician.
    assert second["is_returning"] is True and second["seen_count"] == 2
    assert first["user_key"] == second["user_key"] == sub


def test_distinct_subs_are_distinct_users():
    a_sub, b_sub = _sub(), _sub()

    async def run():
        await init_db()
        return await users.register_session(a_sub), await users.register_session(b_sub)

    a, b = asyncio.run(run())
    assert a["user_key"] == a_sub and b["user_key"] == b_sub
    assert a["is_returning"] is False and b["is_returning"] is False


def test_config_persists_and_merges():
    sub = _sub()

    async def run():
        await init_db()
        await users.register_session(sub)
        await users.set_config(sub, {"fhir_ig": "mcode"})
        await users.set_config(sub, {"coding_subset": ["snomed"]})
        return await users.get_config(sub)

    cfg = asyncio.run(run())
    assert cfg["fhir_ig"] == "mcode"
    assert cfg["coding_subset"] == ["snomed"]
