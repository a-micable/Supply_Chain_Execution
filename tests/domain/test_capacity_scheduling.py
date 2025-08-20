"""Tests for capacity planning and delivery scheduling."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from nexusops.domain.optimization.capacity import CapacityPlanner
from nexusops.domain.transportation.scheduling import DeliveryScheduler, DeliveryWindow
from nexusops.domain.warehouse.putaway import PutawayOptimizer
from nexusops.models.inventory import InventoryBalance
from nexusops.models.warehouse import Warehouse, WarehouseLocation


@pytest.mark.asyncio
async def test_capacity_snapshot(session):
    wh = Warehouse(
        warehouse_code="WH-CAP", name="Capacity WH",
        address={"city": "X"}, capacity_units=1000,
    )
    session.add(wh)
    await session.flush()

    sku_id = uuid.uuid4()
    session.add(InventoryBalance(warehouse_id=wh.id, sku_id=sku_id, on_hand=800))
    await session.flush()

    planner = CapacityPlanner(session)
    snapshot = await planner.snapshot()
    assert len(snapshot.warehouses) >= 1
    wh_cap = next(c for c in snapshot.warehouses if c.warehouse_id == wh.id)
    assert wh_cap.utilization_pct == 80.0


@pytest.mark.asyncio
async def test_capacity_forecast_overflow_detection(session, sample_warehouse):
    planner = CapacityPlanner(session)
    forecasts = await planner.forecast(sample_warehouse.id, horizon_days=7)
    assert len(forecasts) == 7
    assert all(f.projected_utilization_pct >= 0 for f in forecasts)


@pytest.mark.asyncio
async def test_delivery_slot_generation(session, sample_warehouse):
    scheduler = DeliveryScheduler(session)
    start = datetime(2025, 6, 16, 8, 0, 0, tzinfo=timezone.utc)
    slots = await scheduler.generate_slots(sample_warehouse.id, start, days=5)
    assert len(slots) > 0
    assert all(s.capacity > 0 for s in slots)


@pytest.mark.asyncio
async def test_putaway_planning(session, sample_warehouse, sample_sku):
    for i, zone in enumerate(["A", "B", "C"]):
        loc = WarehouseLocation(
            warehouse_id=sample_warehouse.id,
            location_code=f"LOC-{zone}-01",
            zone=zone,
            capacity_units=200,
            is_pickable=True,
        )
        session.add(loc)
    await session.flush()

    optimizer = PutawayOptimizer(session)
    plan = await optimizer.plan_putaway(
        sample_warehouse.id, sample_sku.id, quantity=150, velocity_class="high"
    )
    assert len(plan.recommendations) >= 1
    assert len(plan.task_ids) >= 1
    assert plan.recommendations[0].target_zone == "A"
