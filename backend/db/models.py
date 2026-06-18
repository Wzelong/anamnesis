"""SQLAlchemy ORM models.

Persisted state is non-PHI only: per-clinician framework config (`app_user`) and
a per-run usage ledger (`usage_run`), both keyed on the Prompt Opinion token `sub`.
No patient data: clinician identity is not PHI, config is configuration, and the
ledger holds billing metadata (tokens / cost / duration) — never clinical content.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, JSON, Numeric, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AppUser(Base):
    __tablename__ = "app_user"

    user_key: Mapped[str] = mapped_column(String(128), primary_key=True)  # token sub
    display_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    seen_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class UsageRun(Base):
    """One row per pipeline run. Non-PHI: tokens / cost / duration / doc count,
    keyed on the clinician `sub`. No patient id, no clinical content. Powers the
    BYOK "account & usage" view (per-run detail + cumulative spend)."""
    __tablename__ = "usage_run"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_key: Mapped[str] = mapped_column(String(128), index=True)  # token sub
    workspace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    reasoning_tokens: Mapped[int] = mapped_column(default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    duration_ms: Mapped[int | None] = mapped_column(nullable=True)
    doc_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(16), default="completed")
    triggered_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
