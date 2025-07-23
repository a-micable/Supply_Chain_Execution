"""Event replay and projection rebuilding."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.exceptions import EventOrderingError
from nexusops.core.logging import get_logger
from nexusops.events.ordering import EventOrderingValidator
from nexusops.models.events import DomainEvent
from nexusops.repositories.events import DomainEventRepository

logger = get_logger(__name__)

ProjectionHandler = Callable[[DomainEvent], Awaitable[None]]


@dataclass
class ReplayResult:
    aggregate_type: str
    aggregate_id: uuid.UUID
    events_replayed: int
    errors: list[str] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class ReplayStats:
    total_aggregates: int = 0
    total_events: int = 0
    failed_aggregates: int = 0
    results: list[ReplayResult] = field(default_factory=list)


class EventReplayer:
    """Replays domain events to rebuild read models and projections."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.event_repo = DomainEventRepository(session)
        self.ordering_validator = EventOrderingValidator(session)
        self._projections: dict[str, ProjectionHandler] = {}

    def register_projection(self, event_type: str, handler: ProjectionHandler) -> None:
        self._projections[event_type] = handler

    async def replay_aggregate(
        self,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        from_sequence: int = 1,
    ) -> ReplayResult:
        from datetime import timezone
        result = ReplayResult(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            events_replayed=0,
            started_at=datetime.now(timezone.utc),
        )

        try:
            await self.ordering_validator.validate_and_raise(aggregate_type, aggregate_id)
        except EventOrderingError as exc:
            result.errors.append(str(exc))
            return result

        events = await self.event_repo.list_for_aggregate(aggregate_type, aggregate_id)
        filtered = [e for e in events if e.sequence_number >= from_sequence]

        for event in filtered:
            handler = self._projections.get(event.event_type)
            if handler is None:
                continue
            try:
                await handler(event)
                result.events_replayed += 1
            except Exception as exc:
                result.errors.append(
                    f"Event {event.id} seq {event.sequence_number}: {exc}"
                )

        result.completed_at = datetime.now(timezone.utc)
        logger.info(
            "aggregate_replayed",
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id),
            events=result.events_replayed,
            errors=len(result.errors),
        )
        return result

    async def replay_pending_events(self, limit: int = 100) -> ReplayStats:
        stats = ReplayStats()
        pending = await self.event_repo.list_pending(limit)

        aggregates: dict[tuple[str, uuid.UUID], list[DomainEvent]] = {}
        for event in pending:
            key = (event.aggregate_type, event.aggregate_id)
            aggregates.setdefault(key, []).append(event)

        stats.total_aggregates = len(aggregates)
        for (agg_type, agg_id), events in aggregates.items():
            result = await self.replay_aggregate(agg_type, agg_id)
            stats.results.append(result)
            stats.total_events += result.events_replayed
            if result.errors:
                stats.failed_aggregates += 1

        return stats

    async def rebuild_inventory_projection(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID
    ) -> dict[str, Any]:
        events = await self.event_repo.list_for_aggregate("inventory", sku_id)
        on_hand = 0
        reserved = 0
        allocated = 0

        for event in events:
            if event.event_type == "inventory.adjusted":
                on_hand += event.payload.get("quantity_delta", 0)
            elif event.event_type == "inventory.reserved":
                qty = event.payload.get("quantity", 0)
                wh = event.payload.get("warehouse_id")
                if wh == str(warehouse_id):
                    reserved += qty
            elif event.event_type == "allocation.created":
                qty = event.payload.get("quantity", 0)
                wh = event.payload.get("warehouse_id")
                if wh == str(warehouse_id):
                    allocated += qty

        return {
            "warehouse_id": str(warehouse_id),
            "sku_id": str(sku_id),
            "projected_on_hand": on_hand,
            "projected_reserved": reserved,
            "projected_allocated": allocated,
            "projected_available": max(0, on_hand - reserved - allocated),
            "events_processed": len(events),
        }
