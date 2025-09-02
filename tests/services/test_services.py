"""Service layer unit tests."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from nexusops.domain.inventory.allocation import AllocationRequest
from nexusops.models.inventory import InventoryBalance
from nexusops.services.audit_service import AuditService
from nexusops.services.fulfillment_service import FulfillmentService
from nexusops.services.inventory_service import InventoryService


@pytest.mark.asyncio
async def test_inventory_service_allocate(session, sample_warehouse, sample_sku, stocked_balance):
    service = InventoryService(session)
    result = await service.allocate_for_order_line(
        AllocationRequest(
            order_id=uuid.uuid4(),
            order_line_id=uuid.uuid4(),
            sku_id=sample_sku.id,
            quantity=25,
            preferred_warehouse_id=sample_warehouse.id,
        )
    )
    assert result.total_allocated == 25


@pytest.mark.asyncio
async def test_inventory_service_network_visibility(session, sample_warehouse, sample_sku, stocked_balance):
    service = InventoryService(session)
    visibility = await service.get_network_visibility(sample_sku.id, use_cache=False)
    assert len(visibility) >= 1
    assert visibility[0]["available"] == 500


@pytest.mark.asyncio
async def test_fulfillment_service_create_order(session, sample_sku):
    service = FulfillmentService(session)
    order = await service.create_order(
        external_order_id="SVC-ORD-001",
        customer_id="CUST-SVC",
        ship_to_address={"city": "Chicago", "state": "IL", "postal_code": "60601"},
        lines=[{"sku_id": str(sample_sku.id), "quantity": 5, "unit_price": "29.99"}],
    )
    assert order.external_order_id == "SVC-ORD-001"
    assert order.status == "received"


@pytest.mark.asyncio
async def test_audit_service_records_entry(session, sample_warehouse):
    audit = AuditService(session)
    entry = await audit.record(
        entity_type="warehouse",
        entity_id=sample_warehouse.id,
        action="test_action",
        before_state={"status": "old"},
        after_state={"status": "new"},
    )
    assert entry.action == "test_action"
    history = await audit.get_entity_history("warehouse", sample_warehouse.id)
    assert len(history) == 1


@pytest.mark.asyncio
async def test_inventory_adjustment(session, sample_warehouse, sample_sku):
    service = InventoryService(session)
    await service.adjust_inventory(sample_warehouse.id, sample_sku.id, 100, "cycle_count")
    balance = await service.balance_repo.get_balance(sample_warehouse.id, sample_sku.id)
    assert balance.on_hand == 100
