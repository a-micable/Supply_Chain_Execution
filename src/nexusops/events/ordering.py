"""Event ordering validation and replay."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.exceptions import EventOrderingError
from nexusops.core.logging import get_logger
from nexusops.repositories.events import DomainEventRepository

logger = get_logger(__name__)


@dataclass
class OrderingViolation:
    aggregate_type: str
    aggregate_id: uuid.UUID
    expected_sequence: int
    actual_sequence: int
    event_id: uuid.UUID


class EventOrderingValidator:
    """Validates event sequence integrity for aggregates."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.event_repo = DomainEventRepository(session)

    async def validate_aggregate(
        self, aggregate_type: str, aggregate_id: uuid.UUID
    ) -> list[OrderingViolation]:
        events = await self.event_repo.list_for_aggregate(aggregate_type, aggregate_id)
        violations: list[OrderingViolation] = []

        expected = 1
        for event in events:
            if event.sequence_number != expected:
                violations.append(
                    OrderingViolation(
                        aggregate_type=aggregate_type,
                        aggregate_id=aggregate_id,
                        expected_sequence=expected,
                        actual_sequence=event.sequence_number,
                        event_id=event.id,
                    )
                )
            expected = event.sequence_number + 1

        if violations:
            logger.warning(
                "event_ordering_violations",
                aggregate_type=aggregate_type,
                aggregate_id=str(aggregate_id),
                count=len(violations),
            )
        return violations

    async def validate_and_raise(
        self, aggregate_type: str, aggregate_id: uuid.UUID
    ) -> None:
        violations = await self.validate_aggregate(aggregate_type, aggregate_id)
        if violations:
            v = violations[0]
            raise EventOrderingError(
                f"Event ordering violation for {aggregate_type}/{aggregate_id}: "
                f"expected seq {v.expected_sequence}, got {v.actual_sequence}",
                details={
                    "aggregate_type": aggregate_type,
                    "aggregate_id": str(aggregate_id),
                    "violations": len(violations),
                },
            )

    async def get_expected_next_sequence(
        self, aggregate_type: str, aggregate_id: uuid.UUID
    ) -> int:
        events = await self.event_repo.list_for_aggregate(aggregate_type, aggregate_id)
        if not events:
            return 1
        return events[-1].sequence_number + 1
