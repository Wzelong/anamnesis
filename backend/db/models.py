"""SQLAlchemy ORM models.

The only persisted state is per-clinician framework config (`app_user`), keyed
on the Prompt Opinion token `sub` (the clinician's stable OIDC subject). No PHI:
clinician identity is not patient data; config is configuration, not chart data.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, String
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
