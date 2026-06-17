"""SQLAlchemy ORM models."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PipelineRun(Base):
    __tablename__ = "pipeline_run"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    patient_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    patient_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    triggered_by: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column()
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    calls: Mapped[list["LLMCall"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class LLMCall(Base):
    __tablename__ = "llm_call"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("pipeline_run.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stage: Mapped[str] = mapped_column(String(32))
    call_type: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    reasoning_tokens: Mapped[int] = mapped_column(default=0)
    cached_tokens: Mapped[int] = mapped_column(default=0)
    latency_ms: Mapped[int] = mapped_column(default=0)
    usd_cost: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal("0"))
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column()
    finished_at: Mapped[datetime] = mapped_column()

    run: Mapped[PipelineRun] = relationship(back_populates="calls")

    __table_args__ = (
        Index("ix_llm_call_run_stage", "run_id", "stage"),
        Index("ix_llm_call_run_call_type", "run_id", "call_type"),
    )


class ProposalRecord(Base):
    __tablename__ = "proposal"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("pipeline_run.id", ondelete="CASCADE"), index=True
    )
    patient_id: Mapped[str] = mapped_column(String(128), index=True)
    resource_type: Mapped[str] = mapped_column(String(32))
    classification: Mapped[str] = mapped_column(String(16))
    confidence_tier: Mapped[str] = mapped_column(String(16))
    confidence_score: Mapped[Decimal] = mapped_column(Numeric(4, 3))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    resource_json: Mapped[str] = mapped_column(Text)
    citations_json: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column()
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    conflict_group_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    __table_args__ = (
        Index("ix_proposal_patient_status", "patient_id", "status"),
    )


class ReviewToken(Base):
    __tablename__ = "review_token"

    token: Mapped[str] = mapped_column(String(32), primary_key=True)
    display: Mapped[str] = mapped_column(String(256))
    fhir_reference: Mapped[str | None] = mapped_column(String(256), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column()


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
    at: Mapped[datetime] = mapped_column()
