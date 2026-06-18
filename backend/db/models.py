"""SQLAlchemy ORM models."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class PipelineRun(Base):
    __tablename__ = "pipeline_run"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    patient_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    patient_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class DecisionAudit(Base):
    """Non-PHI audit of stateless-path decisions. The durable clinical audit is
    the FHIR Provenance; this is a fast local trail (no patient id, no content)."""
    __tablename__ = "decision_audit"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(16))
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reviewer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    resource_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
