from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    filename: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    cases: Mapped[list["LabelCase"]] = relationship(back_populates="batch")
    jobs: Mapped[list["VerificationJob"]] = relationship(back_populates="batch")


class LabelCase(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid4()))
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id"))
    source: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)
    application_fields: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    image_sha256: Mapped[str] = mapped_column(String, nullable=False, index=True)
    image_path: Mapped[str] = mapped_column(String, nullable=False)
    label_images: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    current_recommendation: Mapped[str | None] = mapped_column(String)
    final_decision: Mapped[str | None] = mapped_column(String)
    final_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    batch: Mapped[Batch | None] = relationship(back_populates="cases")
    tier_events: Mapped[list["TierEvent"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    field_results: Mapped[list["FieldResultRow"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    provider_usage: Mapped[list["ProviderUsage"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    human_decisions: Mapped[list["HumanDecision"]] = relationship(
        back_populates="case", cascade="all, delete-orphan"
    )
    audit_events: Mapped[list["AuditEvent"]] = relationship(back_populates="case")
    jobs: Mapped[list["VerificationJob"]] = relationship(back_populates="case")


class TierEvent(Base):
    __tablename__ = "tier_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), nullable=False, index=True)
    layer: Mapped[str] = mapped_column(String, nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    case: Mapped[LabelCase] = relationship(back_populates="tier_events")


class FieldResultRow(Base):
    __tablename__ = "field_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), nullable=False, index=True)
    field_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    expected_value: Mapped[str] = mapped_column(Text, nullable=False)
    extracted_value: Mapped[str | None] = mapped_column(Text)
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    source_layer: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    case: Mapped[LabelCase] = relationship(back_populates="field_results")


class ProviderUsage(Base):
    __tablename__ = "provider_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    base_url_label: Mapped[str | None] = mapped_column(String)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_input: Mapped[int | None] = mapped_column(Integer)
    tokens_output: Mapped[int | None] = mapped_column(Integer)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    case: Mapped[LabelCase] = relationship(back_populates="provider_usage")


class HumanDecision(Base):
    __tablename__ = "human_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reviewer_label: Mapped[str] = mapped_column(String, nullable=False, default="demo-agent")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    case: Mapped[LabelCase] = relationship(back_populates="human_decisions")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str | None] = mapped_column(ForeignKey("cases.id"), index=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id"), index=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    case: Mapped[LabelCase | None] = relationship(back_populates="audit_events")


class VerificationJob(Base):
    __tablename__ = "verification_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), nullable=False, index=True)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("batches.id"), index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    case: Mapped[LabelCase] = relationship(back_populates="jobs")
    batch: Mapped[Batch | None] = relationship(back_populates="jobs")
