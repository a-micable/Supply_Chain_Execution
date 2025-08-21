"""Tests for event replay and cycle count operations."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from nexusops.domain.warehouse.cycle_count import CycleCountService, CycleCountStatus
from nexusops.events.replay import EventReplayer
from nexusops.models.events import DomainEvent
from nexusops.models.inventory import InventoryBalance
from nexusops.models.warehouse import WarehouseLocation


@pytest.mark.asyncio
async def test_event_replay_aggregate(session):
    agg_id = uuid.uuid4()
    for seq in range(1, 4):
        session.add(DomainEvent(
            event_type="inventory.adjusted",
            aggregate_type="inventory",
            aggregate_id=agg_id,
            sequence_number=seq,
            correlation_id="c1",
            payload={"quantity_delta": 10},
            occurred_at=datetime.now(timezone.utc),
        ))
    await session.flush()

    replayer = EventReplayer(session)
    processed = []

    async def handler(event: DomainEvent) -> None:
        processed.append(event.sequence_number)

    replayer.register_projection("inventory.adjusted", handler)
    result = await replayer.replay_aggregate("inventory", agg_id)
    assert result.events_replayed == 3
    assert processed == [1, 2, 3]


@pytest.mark.asyncio
async def test_rebuild_inventory_projection(session, sample_warehouse, sample_sku):
    session.add(DomainEvent(
        event_type="inventory.adjusted",
        aggregate_type="inventory",
        aggregate_id=sample_sku.id,
        sequence_number=1,
        correlation_id="c1",
        payload={"quantity_delta": 100, "warehouse_id": str(sample_warehouse.id)},
        occurred_at=datetime.now(timezone.utc),
    ))
    session.add(DomainEvent(
        event_type="inventory.reserved",
        aggregate_type="inventory",
        aggregate_id=sample_sku.id,
        sequence_number=2,
        correlation_id="c1",
        payload={"quantity": 20, "warehouse_id": str(sample_warehouse.id)},
        occurred_at=datetime.now(timezone.utc),
    ))
    await session.flush()

    replayer = EventReplayer(session)
    projection = await replayer.rebuild_inventory_projection(
        sample_warehouse.id, sample_sku.id
    )
    assert projection["projected_on_hand"] == 100
    assert projection["projected_reserved"] == 20
    assert projection["projected_available"] == 80


@pytest.mark.asyncio
async def test_cycle_count_schedule(session, sample_warehouse, sample_sku):
    loc = WarehouseLocation(
        warehouse_id=sample_warehouse.id,
        location_code="A-01-01",
        zone="A",
        is_pickable=True,
    )
    session.add(loc)
    await session.flush()

    session.add(InventoryBalance(
        warehouse_id=sample_warehouse.id,
        sku_id=sample_sku.id,
        location_id=loc.id,
        on_hand=50,
    ))
    await session.flush()

    service = CycleCountService(session)
    cc = await service.schedule_count(sample_warehouse.id, [loc.id])
    assert len(cc.lines) == 1
    assert len(cc.task_ids) == 1
    assert cc.lines[0].expected_quantity == 50


@pytest.mark.asyncio
async def test_cycle_count_variance_adjustment(session, sample_warehouse, sample_sku):
    loc = WarehouseLocation(
        warehouse_id=sample_warehouse.id,
        location_code="B-01-01",
        zone="B",
    )
    session.add(loc)
    await session.flush()

    session.add(InventoryBalance(
        warehouse_id=sample_warehouse.id,
        sku_id=sample_sku.id,
        location_id=loc.id,
        on_hand=100,
    ))
    await session.flush()

    service = CycleCountService(session)
    cc = await service.schedule_count(sample_warehouse.id, [loc.id])
    await service.record_count(cc, loc.id, sample_sku.id, 95)
    completed = await service.complete_session(cc, auto_adjust=True)

    assert completed.status == CycleCountStatus.ADJUSTED
    balance = await service.balance_repo.get_balance(
        sample_warehouse.id, sample_sku.id, loc.id
    )
    assert balance.on_hand == 95


@pytest.mark.asyncio
async def test_large_variance_requires_review(session, sample_warehouse, sample_sku):
    loc = WarehouseLocation(
        warehouse_id=sample_warehouse.id,
        location_code="C-01-01",
        zone="C",
    )
    session.add(loc)
    await session.flush()

    session.add(InventoryBalance(
        warehouse_id=sample_warehouse.id,
        sku_id=sample_sku.id,
        location_id=loc.id,
        on_hand=100,
    ))
    await session.flush()

    service = CycleCountService(session)
    cc = await service.schedule_count(sample_warehouse.id, [loc.id])
    await service.record_count(cc, loc.id, sample_sku.id, 30)
    completed = await service.complete_session(cc)

    assert completed.status == CycleCountStatus.VARIANCE_REVIEW
