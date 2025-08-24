"""Inventory reconciliation tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nexusops.domain.inventory.reconciliation import InventoryReconciler
from nexusops.models.inventory import InventoryBalance, InventoryReservation


@pytest.mark.asyncio
async def test_balanced_inventory_passes(session, sample_warehouse, sample_sku, stocked_balance):
    reconciler = InventoryReconciler(session)
    report = await reconciler.reconcile_warehouse(sample_warehouse.id)
    assert report.is_balanced
    assert len(report.discrepancies) == 0


@pytest.mark.asyncio
async def test_reservation_mismatch_detected(session, sample_warehouse, sample_sku, stocked_balance):
    stocked_balance.reserved = 50
    reservation = InventoryReservation(
        order_id=uuid.uuid4(),
        order_line_id=uuid.uuid4(),
        warehouse_id=sample_warehouse.id,
        sku_id=sample_sku.id,
        quantity=30,
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    session.add(reservation)
    await session.flush()

    reconciler = InventoryReconciler(session)
    report = await reconciler.reconcile_warehouse(sample_warehouse.id)
    assert not report.is_balanced
    assert any(d.discrepancy_type == "reservation_mismatch" for d in report.discrepancies)


@pytest.mark.asyncio
async def test_negative_available_detected(session, sample_warehouse, sample_sku):
    balance = InventoryBalance(
        warehouse_id=sample_warehouse.id,
        sku_id=sample_sku.id,
        on_hand=10,
        reserved=20,
    )
    session.add(balance)
    await session.flush()

    reconciler = InventoryReconciler(session)
    report = await reconciler.reconcile_warehouse(sample_warehouse.id)
    assert not report.is_balanced
    assert any(d.discrepancy_type == "negative_available" for d in report.discrepancies)


@pytest.mark.asyncio
async def test_auto_repair_reservation_mismatch(session, sample_warehouse, sample_sku, stocked_balance):
    stocked_balance.reserved = 100
    reservation = InventoryReservation(
        order_id=uuid.uuid4(),
        order_line_id=uuid.uuid4(),
        warehouse_id=sample_warehouse.id,
        sku_id=sample_sku.id,
        quantity=40,
        status="active",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    session.add(reservation)
    await session.flush()

    reconciler = InventoryReconciler(session)
    repaired = await reconciler.auto_repair_reservation_mismatch(
        sample_warehouse.id, sample_sku.id
    )
    assert repaired
    balance = await reconciler.balance_repo.get_balance(sample_warehouse.id, sample_sku.id)
    assert balance.reserved == 40
