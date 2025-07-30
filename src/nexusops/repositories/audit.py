"""Audit and compliance repository layer."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select

from nexusops.models.audit import AuditEntry, PlanningDecision
from nexusops.repositories.base import BaseRepository


class AuditRepository(BaseRepository[AuditEntry]):
    model = AuditEntry

    async def list_for_entity(
        self, entity_type: str, entity_id: uuid.UUID, limit: int = 100
    ) -> list[AuditEntry]:
        stmt = (
            select(AuditEntry)
            .where(
                AuditEntry.entity_type == entity_type,
                AuditEntry.entity_id == entity_id,
            )
            .order_by(AuditEntry.event_timestamp.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_correlation(self, correlation_id: str) -> list[AuditEntry]:
        stmt = (
            select(AuditEntry)
            .where(AuditEntry.correlation_id == correlation_id)
            .order_by(AuditEntry.event_timestamp.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_manual_overrides(
        self, start: datetime, end: datetime, limit: int = 100
    ) -> list[AuditEntry]:
        stmt = (
            select(AuditEntry)
            .where(
                AuditEntry.is_manual_override.is_(True),
                AuditEntry.event_timestamp >= start,
                AuditEntry.event_timestamp <= end,
            )
            .order_by(AuditEntry.event_timestamp.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class PlanningDecisionRepository(BaseRepository[PlanningDecision]):
    model = PlanningDecision

    async def list_for_reference(
        self, reference_type: str, reference_id: uuid.UUID
    ) -> list[PlanningDecision]:
        stmt = (
            select(PlanningDecision)
            .where(
                PlanningDecision.reference_type == reference_type,
                PlanningDecision.reference_id == reference_id,
            )
            .order_by(PlanningDecision.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_for_reference(
        self, reference_type: str, reference_id: uuid.UUID, decision_type: str
    ) -> PlanningDecision | None:
        stmt = (
            select(PlanningDecision)
            .where(
                PlanningDecision.reference_type == reference_type,
                PlanningDecision.reference_id == reference_id,
                PlanningDecision.decision_type == decision_type,
            )
            .order_by(PlanningDecision.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
