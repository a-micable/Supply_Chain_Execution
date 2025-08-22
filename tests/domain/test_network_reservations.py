"""Tests for reservation manager and network coordinator."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nexusops.domain.inventory.allocation import AllocationEngine, AllocationRequest
from nexusops.domain.inventory.network_coordinator import NetworkCoordinator
from nexusops.domain.inventory.reservation_manager import ReservationManager
from nexusops.models.inventory import InventoryBalance, InventoryReservation


@pytest.mark.asyncio
async def test_reservation_summary(session, sample_warehouse, sample_sku, stocked_balance):
    engine = AllocationEngine(session)
    order_id = uuid.uuid4()
    await engine.allocate(AllocationRequest(
        order_id=order_id, order_line_id=uuid.uuid4(),
        sku_id=sample_sku.id, quantity=20,
        preferred_warehouse_id=sample_warehouse.id,
    ))

    manager = ReservationManager(session)
    summaries = await manager.get_order_reservations(order_id)
    assert len(summaries) == 1
    assert summaries[0].quantity == 20
    assert not summaries[0].is_expired


@pytest.mark.asyncio
async def test_extend_reservation(session, sample_warehouse, sample_sku, stocked_balance):
    engine = AllocationEngine(session)
    order_id = uuid.uuid4()
    result = await engine.allocate(AllocationRequest(
        order_id=order_id, order_line_id=uuid.uuid4(),
        sku_id=sample_sku.id, quantity=10,
        preferred_warehouse_id=sample_warehouse.id,
    ))

    manager = ReservationManager(session)
    extended = await manager.extend_reservation(result.reservation_ids[0], 30)
    assert extended.seconds_remaining > 0


@pytest.mark.asyncio
async def test_process_expired_reservations(session, sample_warehouse, sample_sku, stocked_balance):
    reservation = InventoryReservation(
        order_id=uuid.uuid4(),
        order_line_id=uuid.uuid4(),
        warehouse_id=sample_warehouse.id,
        sku_id=sample_sku.id,
        quantity=15,
        status="active",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )
    session.add(reservation)
    stocked_balance.reserved = 15
    await session.flush()

    manager = ReservationManager(session)
    result = await manager.process_expired()
    assert result.processed >= 1


@pytest.mark.asyncio
async def test_network_snapshot(session, sample_warehouse, sample_sku, stocked_balance):
    coordinator = NetworkCoordinator(session)
    snapshot = await coordinator.capture_snapshot()
    assert snapshot.warehouse_count >= 1
    assert snapshot.total_on_hand >= 500


@pytest.mark.asyncio
async def test_network_health_check(session, sample_warehouse, sample_sku, stocked_balance):
    coordinator = NetworkCoordinator(session)
    health = await coordinator.health_check()
    assert health.overall_health in ("healthy", "degraded", "critical")
    assert health.snapshot.warehouse_count >= 1


@pytest.mark.asyncio
async def test_fulfill_from_network(session, sample_warehouse, sample_sku, stocked_balance):
    coordinator = NetworkCoordinator(session)
    result = await coordinator.fulfill_from_network(
        uuid.uuid4(), uuid.uuid4(), sample_sku.id, 30
    )
    assert result["total_allocated"] == 30
