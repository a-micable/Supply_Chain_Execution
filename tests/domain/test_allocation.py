"""Allocation engine tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nexusops.core.exceptions import InsufficientInventoryError
from nexusops.domain.inventory.allocation import AllocationEngine, AllocationRequest
from nexusops.models.fulfillment import Order, OrderLine
from nexusops.models.inventory import InventoryBalance, InventoryReservation
from nexusops.models.warehouse import Warehouse


@pytest.mark.asyncio
async def test_allocate_full_quantity(session, sample_warehouse, sample_sku, stocked_balance):
    engine = AllocationEngine(session)
    order_id = uuid.uuid4()
    line_id = uuid.uuid4()

    request = AllocationRequest(
        order_id=order_id,
        order_line_id=line_id,
        sku_id=sample_sku.id,
        quantity=100,
        preferred_warehouse_id=sample_warehouse.id,
    )
    result = await engine.allocate(request)

    assert result.total_allocated == 100
    assert result.is_fully_allocated
    assert len(result.allocations) == 1
    assert result.allocations[0] == (sample_warehouse.id, 100)


@pytest.mark.asyncio
async def test_allocate_insufficient_inventory_raises(session, sample_warehouse, sample_sku, stocked_balance):
    engine = AllocationEngine(session)
    request = AllocationRequest(
        order_id=uuid.uuid4(),
        order_line_id=uuid.uuid4(),
        sku_id=sample_sku.id,
        quantity=1000,
        preferred_warehouse_id=sample_warehouse.id,
        allow_split=False,
    )
    with pytest.raises(InsufficientInventoryError) as exc_info:
        await engine.allocate(request)
    assert exc_info.value.details["requested"] == 1000


@pytest.mark.asyncio
async def test_partial_allocation_with_split(session, sample_warehouse, sample_sku, stocked_balance):
    engine = AllocationEngine(session)
    request = AllocationRequest(
        order_id=uuid.uuid4(),
        order_line_id=uuid.uuid4(),
        sku_id=sample_sku.id,
        quantity=600,
        allow_split=True,
    )
    result = await engine.allocate(request)
    assert result.total_allocated == 500
    assert result.backorder_quantity == 100
    assert not result.is_fully_allocated


@pytest.mark.asyncio
async def test_release_reservations(session, sample_warehouse, sample_sku, stocked_balance):
    engine = AllocationEngine(session)
    order_id = uuid.uuid4()
    request = AllocationRequest(
        order_id=order_id,
        order_line_id=uuid.uuid4(),
        sku_id=sample_sku.id,
        quantity=50,
    )
    await engine.allocate(request)
    released = await engine.release_reservations(order_id)
    assert released == 50

    balance = await engine.balance_repo.get_balance(sample_warehouse.id, sample_sku.id)
    assert balance.reserved == 0


@pytest.mark.asyncio
async def test_multi_warehouse_ranking(session, sample_sku):
    wh1 = Warehouse(
        warehouse_code="WH-01",
        name="Warehouse 1",
        address={"city": "A"},
        fulfillment_priority=5,
    )
    wh2 = Warehouse(
        warehouse_code="WH-02",
        name="Warehouse 2",
        address={"city": "B"},
        fulfillment_priority=1,
    )
    session.add_all([wh1, wh2])
    await session.flush()

    session.add_all([
        InventoryBalance(warehouse_id=wh1.id, sku_id=sample_sku.id, on_hand=100),
        InventoryBalance(warehouse_id=wh2.id, sku_id=sample_sku.id, on_hand=200),
    ])
    await session.flush()

    engine = AllocationEngine(session)
    request = AllocationRequest(
        order_id=uuid.uuid4(),
        order_line_id=uuid.uuid4(),
        sku_id=sample_sku.id,
        quantity=50,
    )
    result = await engine.allocate(request)
    assert result.total_allocated == 50
