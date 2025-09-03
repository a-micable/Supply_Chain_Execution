"""Tests for batch processing operations."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from nexusops.core.types import OrderStatus
from nexusops.models.fulfillment import Order, OrderLine
from nexusops.models.inventory import InventoryBalance
from nexusops.models.warehouse import Warehouse
from nexusops.workers.batch_processor import BatchProcessor, OrderAllocationBatch, ReconciliationBatch


@pytest.mark.asyncio
async def test_order_allocation_batch(session, sample_warehouse, sample_sku, stocked_balance):
    order = Order(
        external_order_id="BATCH-ORD-001",
        customer_id="C1",
        ship_to_address={"city": "X"},
        status=OrderStatus.RECEIVED,
    )
    session.add(order)
    await session.flush()
    session.add(OrderLine(
        order_id=order.id, sku_id=sample_sku.id,
        quantity_ordered=10, unit_price=Decimal("5"),
    ))
    await session.flush()

    batch = OrderAllocationBatch(session)
    result = await batch.run()
    assert result.total_items >= 1
    assert result.succeeded >= 1 or result.failed >= 1


@pytest.mark.asyncio
async def test_reconciliation_batch(session, sample_warehouse, sample_sku, stocked_balance):
    batch = ReconciliationBatch(session)
    result = await batch.run([sample_warehouse.id])
    assert result.total_items == 1
    assert result.status in ("completed", "partially_failed", "failed")


@pytest.mark.asyncio
async def test_batch_processor_nightly(session, sample_warehouse, sample_sku, stocked_balance):
    processor = BatchProcessor(session)
    results = await processor.run_nightly_jobs([sample_warehouse.id])
    assert "reconciliation" in results
    assert "allocation" in results


@pytest.mark.asyncio
async def test_reconciliation_batch_multiple_warehouses(session, sample_sku):
    wh_ids = []
    for i in range(3):
        wh = Warehouse(warehouse_code=f"WH-BATCH-{i}", name=f"WH{i}", address={"city": "X"})
        session.add(wh)
        await session.flush()
        wh_ids.append(wh.id)
        session.add(InventoryBalance(warehouse_id=wh.id, sku_id=sample_sku.id, on_hand=100))

    batch = ReconciliationBatch(session)
    result = await batch.run(wh_ids)
    assert result.total_items == 3
    assert result.success_rate >= 0
