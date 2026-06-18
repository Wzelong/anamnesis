"""Per-clinician registration + framework config.

Keyed on the PO token `sub`. The only persisted state in the app. No PHI:
clinician identity is not patient data; config is configuration.
"""
from __future__ import annotations

from datetime import datetime, timezone


async def register_session(
    user_key: str,
    *,
    display_name: str | None = None,
    workspace_id: str | None = None,
    role: str | None = None,
) -> dict:
    """Upsert the clinician on workspace-open. Returns recognition info + config.

    First visit inserts the row; a returning clinician (same `sub`) bumps
    `seen_count` + `last_seen_at`, proving same-user recognition across sessions.
    """
    from db import AppUser, AsyncSessionLocal

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        row = await session.get(AppUser, user_key)
        is_returning = row is not None
        if row is None:
            row = AppUser(
                user_key=user_key,
                display_name=display_name,
                workspace_id=workspace_id,
                role=role,
                config={},
                seen_count=1,
                created_at=now,
                updated_at=now,
                last_seen_at=now,
            )
            session.add(row)
        else:
            row.seen_count += 1
            row.last_seen_at = now
            if display_name:
                row.display_name = display_name
            if workspace_id:
                row.workspace_id = workspace_id
            if role:
                row.role = role
        await session.commit()
        return {
            "user_key": user_key,
            "display_name": row.display_name,
            "is_returning": is_returning,
            "seen_count": row.seen_count,
            "first_seen_at": row.created_at.isoformat(),
            "last_seen_at": row.last_seen_at.isoformat(),
            "config": row.config or {},
        }


async def get_config(user_key: str) -> dict:
    from db import AppUser, AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        row = await session.get(AppUser, user_key)
        return (row.config or {}) if row else {}


async def set_config(user_key: str, patch: dict) -> dict:
    """Deep-merge `patch` into the clinician's config; returns the stored config.

    Secret fields are sealed (encrypted) before storage. The returned config
    carries ciphertext markers, not plaintext — redact before sending to the
    iframe (see `core.byok`).
    """
    from core import byok
    from db import AppUser, AsyncSessionLocal

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as session:
        row = await session.get(AppUser, user_key)
        if row is None:
            raise ValueError("unknown user; open the workspace first")
        merged = byok.deep_merge(row.config or {}, byok.seal(patch or {}))
        row.config = merged
        row.updated_at = now
        await session.commit()
        return merged
