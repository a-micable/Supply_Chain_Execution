"""Event ordering validation tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from nexusops.core.exceptions import EventOrderingError
from nexusops.events.ordering import EventOrderingValidator
from nexusops.models.events import DomainEvent


@pytest.mark.asyncio
async def test_valid_sequence_passes(session):
    agg_id = uuid.uuid4()
    for seq in range(1, 4):
        event = DomainEvent(
            event_type="inventory.adjusted",
            aggregate_type="inventory",
            aggregate_id=agg_id,
            sequence_number=seq,
            correlation_id="corr-1",
            payload={"seq": seq},
            occurred_at=datetime.now(timezone.utc),
        )
        session.add(event)
    await session.flush()

    validator = EventOrderingValidator(session)
    violations = await validator.validate_aggregate("inventory", agg_id)
    assert len(violations) == 0


@pytest.mark.asyncio
async def test_sequence_gap_detected(session):
    agg_id = uuid.uuid4()
    for seq in [1, 2, 4]:
        event = DomainEvent(
            event_type="inventory.adjusted",
            aggregate_type="inventory",
            aggregate_id=agg_id,
            sequence_number=seq,
            correlation_id="corr-1",
            payload={},
            occurred_at=datetime.now(timezone.utc),
        )
        session.add(event)
    await session.flush()

    validator = EventOrderingValidator(session)
    violations = await validator.validate_aggregate("inventory", agg_id)
    assert len(violations) == 1
    assert violations[0].expected_sequence == 3
    assert violations[0].actual_sequence == 4


@pytest.mark.asyncio
async def test_validate_and_raise(session):
    agg_id = uuid.uuid4()
    event = DomainEvent(
        event_type="test",
        aggregate_type="test",
        aggregate_id=agg_id,
        sequence_number=5,
        correlation_id="c",
        payload={},
        occurred_at=datetime.now(timezone.utc),
    )
    session.add(event)
    await session.flush()

    validator = EventOrderingValidator(session)
    with pytest.raises(EventOrderingError):
        await validator.validate_and_raise("test", agg_id)
