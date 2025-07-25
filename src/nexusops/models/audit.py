"""Audit and compliance ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nexusops.db.base import Base, TimestampMixin, UUIDMixin


class AuditEntry(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "audit_entries"
    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_correlation", "correlation_id"),
        Index("ix_audit_timestamp", "event_timestamp"),
    )

    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    before_state: Mapped[dict | None] = mapped_column(JSONB)
    after_state: Mapped[dict | None] = mapped_column(JSONB)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    is_manual_override: Mapped[bool] = mapped_column(default=False)
    override_reason: Mapped[str | None] = mapped_column(Text)


class PlanningDecision(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "planning_decisions"
    __table_args__ = (Index("ix_planning_decision_type", "decision_type"),)

    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_type: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), default="1.0")
    input_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    output_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    score: Mapped[float | None] = mapped_column()
    alternatives_considered: Mapped[int] = mapped_column(default=0)
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    execution_time_ms: Mapped[int | None] = mapped_column()
