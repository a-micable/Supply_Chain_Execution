"""Domain event repository layer."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select, update

from nexusops.models.events import DomainEvent
from nexusops.repositories.base import BaseRepository


class DomainEventRepository(BaseRepository[DomainEvent]):
    model = DomainEvent

    async def get_next_sequence(self, aggregate_type: str, aggregate_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.max(DomainEvent.sequence_number), 0)).where(
            DomainEvent.aggregate_type == aggregate_type,
            DomainEvent.aggregate_id == aggregate_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one() + 1

    async def list_pending(self, limit: int = 50) -> list[DomainEvent]:
        stmt = (
            select(DomainEvent)
            .where(DomainEvent.processing_status == "pending")
            .order_by(DomainEvent.occurred_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_aggregate(
        self, aggregate_type: str, aggregate_id: uuid.UUID
    ) -> list[DomainEvent]:
        stmt = (
            select(DomainEvent)
            .where(
                DomainEvent.aggregate_type == aggregate_type,
                DomainEvent.aggregate_id == aggregate_id,
            )
            .order_by(DomainEvent.sequence_number.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_processed(self, event_id: uuid.UUID) -> None:
        stmt = (
            update(DomainEvent)
            .where(DomainEvent.id == event_id)
            .values(
                processing_status="processed",
                processed_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)

    async def mark_failed(self, event_id: uuid.UUID, error: str) -> None:
        stmt = (
            update(DomainEvent)
            .where(DomainEvent.id == event_id)
            .values(
                processing_status="failed",
                retry_count=DomainEvent.retry_count + 1,
                error_message=error[:2000],
            )
        )
        await self.session.execute(stmt)

    async def count_unprocessed_by_type(self) -> list[tuple[str, int]]:
        stmt = (
            select(DomainEvent.event_type, func.count())
            .where(DomainEvent.processing_status == "pending")
            .group_by(DomainEvent.event_type)
        )
        result = await self.session.execute(stmt)
        return list(result.all())
