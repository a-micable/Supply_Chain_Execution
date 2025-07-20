"""Event bus for publishing and subscribing to domain events."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.config.settings import get_settings
from nexusops.core.logging import get_logger
from nexusops.events.schemas import DomainEventPayload
from nexusops.models.events import DomainEvent
from nexusops.repositories.events import DomainEventRepository

logger = get_logger(__name__)

EventHandler = Callable[[DomainEventPayload], Awaitable[None]]


class EventBus:
    """Publishes events to PostgreSQL event store and Redis stream."""

    def __init__(self, session: AsyncSession, redis_client: aioredis.Redis | None = None) -> None:
        self.session = session
        self.event_repo = DomainEventRepository(session)
        self.settings = get_settings()
        self._redis = redis_client
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: DomainEventPayload) -> DomainEvent:
        seq = await self.event_repo.get_next_sequence(
            event.aggregate_type, event.aggregate_id
        )

        stored = DomainEvent(
            event_type=event.event_type.value,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            sequence_number=seq,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            payload=event.payload,
            metadata_=event.metadata,
            occurred_at=event.occurred_at,
            processing_status="pending",
        )
        await self.event_repo.add(stored)

        if self._redis:
            await self._publish_to_stream(event)

        logger.info(
            "event_published",
            event_type=event.event_type.value,
            aggregate_id=str(event.aggregate_id),
            sequence=seq,
        )
        return stored

    async def _publish_to_stream(self, event: DomainEventPayload) -> None:
        if self._redis is None:
            return
        await self._redis.xadd(
            self.settings.event_stream_key,
            {"data": json.dumps(event.to_dict())},
            maxlen=100000,
        )

    async def dispatch(self, stored_event: DomainEvent) -> None:
        payload = DomainEventPayload(
            event_type=stored_event.event_type,  # type: ignore[arg-type]
            aggregate_type=stored_event.aggregate_type,
            aggregate_id=stored_event.aggregate_id,
            payload=stored_event.payload,
            correlation_id=stored_event.correlation_id,
            causation_id=stored_event.causation_id,
            metadata=stored_event.metadata_ or {},
            occurred_at=stored_event.occurred_at,
        )

        handlers = self._handlers.get(stored_event.event_type, [])
        handlers.extend(self._handlers.get("*", []))

        try:
            for handler in handlers:
                await handler(payload)
            await self.event_repo.mark_processed(stored_event.id)
        except Exception as exc:
            await self.event_repo.mark_failed(stored_event.id, str(exc))
            logger.error(
                "event_dispatch_failed",
                event_id=str(stored_event.id),
                error=str(exc),
            )
            raise

    async def process_pending(self, limit: int = 50) -> int:
        pending = await self.event_repo.list_pending(limit)
        processed = 0
        for event in pending:
            try:
                await self.dispatch(event)
                processed += 1
            except Exception:
                continue
        return processed
