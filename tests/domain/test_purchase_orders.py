"""Extended tests for procurement purchase order lifecycle."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from nexusops.core.exceptions import ValidationError, WorkflowError
from nexusops.core.types import PurchaseOrderStatus
from nexusops.domain.procurement.purchase_orders import PurchaseOrderManager
from nexusops.models.procurement import PurchaseOrder, PurchaseOrderLine, Supplier
from nexusops.models.warehouse import Warehouse


@pytest.fixture
async def po_setup(session):
    wh = Warehouse(warehouse_code="WH-PO", name="PO WH", address={"city": "X"})
    supplier = Supplier(
        supplier_code="SUP-PO", name="PO Supplier", is_active=True,
        on_time_delivery_rate=Decimal("0.90"),
    )
    session.add_all([wh, supplier])
    await session.flush()

    po = PurchaseOrder(
        po_number="PO-TEST-001",
        supplier_id=supplier.id,
        warehouse_id=wh.id,
        status=PurchaseOrderStatus.DRAFT,
        order_date=datetime.now(timezone.utc),
        total_amount=Decimal("1000"),
    )
    session.add(po)
    await session.flush()

    sku_id = uuid.uuid4()
    line = PurchaseOrderLine(
        purchase_order_id=po.id,
        sku_id=sku_id,
        quantity_ordered=100,
        unit_cost=Decimal("10.00"),
    )
    session.add(line)
    await session.flush()
    return po, line, supplier, wh


@pytest.mark.asyncio
async def test_submit_po(session, po_setup):
    po, _, _, _ = po_setup
    manager = PurchaseOrderManager(session)
    submitted = await manager.submit(po.id)
    assert submitted.status == PurchaseOrderStatus.SUBMITTED


@pytest.mark.asyncio
async def test_submit_empty_po_fails(session, po_setup):
    po, line, _, _ = po_setup
    await session.delete(line)
    await session.flush()
    manager = PurchaseOrderManager(session)
    with pytest.raises(ValidationError):
        await manager.submit(po.id)


@pytest.mark.asyncio
async def test_acknowledge_po(session, po_setup):
    po, _, _, _ = po_setup
    manager = PurchaseOrderManager(session)
    await manager.submit(po.id)
    expected = datetime.now(timezone.utc) + timedelta(days=14)
    acked = await manager.acknowledge(po.id, expected)
    assert acked.status == PurchaseOrderStatus.ACKNOWLEDGED
    assert acked.expected_delivery == expected


@pytest.mark.asyncio
async def test_partial_receipt(session, po_setup):
    po, line, _, _ = po_setup
    manager = PurchaseOrderManager(session)
    await manager.submit(po.id)
    await manager.acknowledge(po.id)
    updated = await manager.record_receipt(po.id, {line.id: 50})
    assert updated.status == PurchaseOrderStatus.PARTIALLY_RECEIVED
    assert line.quantity_received == 50


@pytest.mark.asyncio
async def test_full_receipt_closes_lines(session, po_setup):
    po, line, _, _ = po_setup
    manager = PurchaseOrderManager(session)
    await manager.submit(po.id)
    await manager.acknowledge(po.id)
    updated = await manager.record_receipt(po.id, {line.id: 100})
    assert updated.status == PurchaseOrderStatus.RECEIVED
    assert line.line_status == "closed"


@pytest.mark.asyncio
async def test_over_receipt_rejected(session, po_setup):
    po, line, _, _ = po_setup
    manager = PurchaseOrderManager(session)
    await manager.submit(po.id)
    await manager.acknowledge(po.id)
    with pytest.raises(ValidationError):
        await manager.record_receipt(po.id, {line.id: 150})


@pytest.mark.asyncio
async def test_invalid_transition_rejected(session, po_setup):
    po, _, _, _ = po_setup
    manager = PurchaseOrderManager(session)
    with pytest.raises(WorkflowError):
        await manager.acknowledge(po.id)


@pytest.mark.asyncio
async def test_cancel_draft_po(session, po_setup):
    po, _, _, _ = po_setup
    manager = PurchaseOrderManager(session)
    cancelled = await manager.cancel(po.id, "no longer needed")
    assert cancelled.status == PurchaseOrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_calculate_open_po_value(session, po_setup):
    po, line, _, wh = po_setup
    manager = PurchaseOrderManager(session)
    await manager.submit(po.id)
    await manager.acknowledge(po.id)
    value = await manager.calculate_open_po_value(wh.id)
    assert value == Decimal("1000")
