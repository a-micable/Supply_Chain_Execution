"""Integration tests for cross-domain workflows."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from nexusops.core.types import OrderStatus, ShipmentStatus
from nexusops.domain.fulfillment.planning import FulfillmentPlanner
from nexusops.domain.fulfillment.routing import OrderRouter
from nexusops.domain.fulfillment.shipment_generation import ShipmentGenerator
from nexusops.domain.inventory.allocation import AllocationEngine, AllocationRequest
from nexusops.domain.procurement.replenishment import ReplenishmentPlanner
from nexusops.domain.transportation.carrier_assignment import CarrierAssigner
from nexusops.domain.warehouse.receiving import ReceivingLine, ReceivingService
from nexusops.domain.warehouse.transfers import TransferRequest, TransferService
from nexusops.models.fulfillment import Order, OrderLine
from nexusops.models.inventory import InventoryBalance, SafetyStockPolicy
from nexusops.models.procurement import PurchaseOrder, PurchaseOrderLine, Supplier
from nexusops.models.transportation import Carrier
from nexusops.models.warehouse import Warehouse


@pytest.mark.asyncio
async def test_order_to_shipment_flow(session, sample_warehouse, sample_sku, stocked_balance):
    order = Order(
        external_order_id="INT-ORD-001",
        customer_id="CUST-100",
        ship_to_address={"city": "Boston", "state": "MA", "postal_code": "02101"},
        status=OrderStatus.RECEIVED,
        routing_strategy="cost_optimized",
    )
    session.add(order)
    await session.flush()

    line = OrderLine(
        order_id=order.id,
        sku_id=sample_sku.id,
        quantity_ordered=25,
        unit_price=Decimal("19.99"),
    )
    session.add(line)
    await session.flush()

    router = OrderRouter(session)
    decision = await router.route_order(order.id)
    assert len(decision.selected_warehouses) >= 1

    engine = AllocationEngine(session)
    result = await engine.allocate(
        AllocationRequest(
            order_id=order.id,
            order_line_id=line.id,
            sku_id=sample_sku.id,
            quantity=25,
            preferred_warehouse_id=sample_warehouse.id,
        )
    )
    assert result.total_allocated == 25

    generator = ShipmentGenerator(session)
    plans = await generator.plan_repo.get_plans_for_order(order.id)
    assert len(plans) >= 1

    shipment = await generator.generate_from_plan(plans[0].id)
    assert shipment.status == ShipmentStatus.DRAFT


@pytest.mark.asyncio
async def test_receiving_updates_inventory(session, sample_warehouse, sample_sku):
    supplier = Supplier(
        supplier_code="SUP-001",
        name="Acme Supplies",
        lead_time_days=10,
        on_time_delivery_rate=Decimal("0.92"),
    )
    session.add(supplier)
    await session.flush()

    po = PurchaseOrder(
        po_number="PO-INT-001",
        supplier_id=supplier.id,
        warehouse_id=sample_warehouse.id,
        status="acknowledged",
        order_date=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        total_amount=Decimal("500"),
    )
    session.add(po)
    await session.flush()

    po_line = PurchaseOrderLine(
        purchase_order_id=po.id,
        sku_id=sample_sku.id,
        quantity_ordered=100,
        unit_cost=Decimal("5.00"),
    )
    session.add(po_line)
    await session.flush()

    receiving = ReceivingService(session)
    result = await receiving.receive_against_po(
        po.id,
        sample_warehouse.id,
        [ReceivingLine(sku_id=sample_sku.id, quantity_expected=100, quantity_received=95, damage_quantity=2)],
    )
    assert result.total_received == 95
    assert len(result.tasks_created) == 1

    balance = await receiving.balance_repo.get_balance(sample_warehouse.id, sample_sku.id)
    assert balance.on_hand == 93


@pytest.mark.asyncio
async def test_inter_warehouse_transfer(session, sample_sku):
    wh1 = Warehouse(warehouse_code="WH-SRC", name="Source", address={"city": "A"}, fulfillment_priority=3)
    wh2 = Warehouse(warehouse_code="WH-DST", name="Dest", address={"city": "B"}, fulfillment_priority=3)
    session.add_all([wh1, wh2])
    await session.flush()

    session.add(InventoryBalance(warehouse_id=wh1.id, sku_id=sample_sku.id, on_hand=200))
    await session.flush()

    transfer_svc = TransferService(session)
    transfer = await transfer_svc.initiate_transfer(
        TransferRequest(
            source_warehouse_id=wh1.id,
            destination_warehouse_id=wh2.id,
            sku_id=sample_sku.id,
            quantity=50,
        )
    )
    assert transfer.status == "pending"

    await transfer_svc.ship_transfer(transfer.id)
    received = await transfer_svc.receive_transfer(transfer.id)
    assert received.status == "received"
    assert received.quantity_received == 50

    dest_balance = await transfer_svc.balance_repo.get_balance(wh2.id, sample_sku.id)
    assert dest_balance.on_hand == 50


@pytest.mark.asyncio
async def test_replenishment_triggers_on_low_stock(session, sample_warehouse, sample_sku):
    session.add(InventoryBalance(warehouse_id=sample_warehouse.id, sku_id=sample_sku.id, on_hand=5))
    session.add(
        SafetyStockPolicy(
            warehouse_id=sample_warehouse.id,
            sku_id=sample_sku.id,
            safety_stock_qty=50,
            reorder_point=100,
            service_level=Decimal("0.95"),
        )
    )
    supplier = Supplier(supplier_code="SUP-REPL", name="Repl Supplier", is_preferred=True)
    session.add(supplier)
    await session.flush()

    planner = ReplenishmentPlanner(session)
    plan = await planner.generate_plan(sample_warehouse.id)
    assert len(plan.lines) >= 1
    assert plan.lines[0].suggested_order_qty > 0


@pytest.mark.asyncio
async def test_carrier_assignment(session, sample_warehouse):
    carrier = Carrier(
        carrier_code="FEDX",
        name="FedEx Express",
        on_time_rate=Decimal("0.94"),
        cost_per_kg=Decimal("2.50"),
        max_weight_kg=Decimal("1000"),
    )
    session.add(carrier)
    await session.flush()

    from nexusops.models.transportation import Shipment
    shipment = Shipment(
        shipment_number="SHP-CARR-001",
        warehouse_id=sample_warehouse.id,
        status="planned",
        origin_address={"city": "A"},
        destination_address={"city": "B"},
        total_weight_kg=Decimal("15.5"),
    )
    session.add(shipment)
    await session.flush()

    assigner = CarrierAssigner(session)
    assignment = await assigner.assign_carrier(shipment.id)
    assert assignment.carrier_code == "FEDX"
    assert assignment.score > 0
