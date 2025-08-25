"""Comprehensive routing engine tests."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from nexusops.core.exceptions import RoutingConflictError
from nexusops.core.types import OrderStatus
from nexusops.domain.fulfillment.routing import OrderRouter
from nexusops.models.fulfillment import Order, OrderLine
from nexusops.models.inventory import InventoryBalance
from nexusops.models.warehouse import Warehouse


@pytest.mark.asyncio
async def test_cost_optimized_routing(session, sample_sku):
    wh1 = Warehouse(warehouse_code="WH-COST-1", name="WH1", address={"city": "A"}, fulfillment_priority=5)
    wh2 = Warehouse(warehouse_code="WH-COST-2", name="WH2", address={"city": "B"}, fulfillment_priority=2)
    session.add_all([wh1, wh2])
    await session.flush()

    session.add_all([
        InventoryBalance(warehouse_id=wh1.id, sku_id=sample_sku.id, on_hand=100),
        InventoryBalance(warehouse_id=wh2.id, sku_id=sample_sku.id, on_hand=100),
    ])
    await session.flush()

    order = Order(
        external_order_id="ROUTE-COST-001",
        customer_id="C1",
        ship_to_address={"city": "X"},
        routing_strategy="cost_optimized",
    )
    session.add(order)
    await session.flush()
    session.add(OrderLine(order_id=order.id, sku_id=sample_sku.id, quantity_ordered=10, unit_price=Decimal("5")))
    await session.flush()

    router = OrderRouter(session)
    decision = await router.route_order(order.id, "cost_optimized")
    assert len(decision.selected_warehouses) >= 1
    assert decision.estimated_total_cost > 0


@pytest.mark.asyncio
async def test_speed_optimized_routing(session, sample_sku):
    wh = Warehouse(warehouse_code="WH-SPD", name="Fast WH", address={"city": "A"}, fulfillment_priority=1)
    session.add(wh)
    await session.flush()
    session.add(InventoryBalance(warehouse_id=wh.id, sku_id=sample_sku.id, on_hand=50))
    await session.flush()

    order = Order(
        external_order_id="ROUTE-SPD-001",
        customer_id="C1",
        ship_to_address={"city": "X"},
        routing_strategy="speed_optimized",
    )
    session.add(order)
    await session.flush()
    session.add(OrderLine(order_id=order.id, sku_id=sample_sku.id, quantity_ordered=5, unit_price=Decimal("5")))
    await session.flush()

    router = OrderRouter(session)
    decision = await router.route_order(order.id, "speed_optimized")
    assert decision.strategy == "speed_optimized"


@pytest.mark.asyncio
async def test_single_warehouse_strategy(session, sample_sku):
    wh1 = Warehouse(warehouse_code="WH-SNG-1", name="WH1", address={"city": "A"}, fulfillment_priority=3)
    wh2 = Warehouse(warehouse_code="WH-SNG-2", name="WH2", address={"city": "B"}, fulfillment_priority=3)
    session.add_all([wh1, wh2])
    await session.flush()
    session.add(InventoryBalance(warehouse_id=wh1.id, sku_id=sample_sku.id, on_hand=100))
    session.add(InventoryBalance(warehouse_id=wh2.id, sku_id=sample_sku.id, on_hand=10))
    await session.flush()

    order = Order(
        external_order_id="ROUTE-SNG-001",
        customer_id="C1",
        ship_to_address={"city": "X"},
        routing_strategy="single_warehouse",
        allow_partial_fulfillment=False,
    )
    session.add(order)
    await session.flush()
    session.add(OrderLine(order_id=order.id, sku_id=sample_sku.id, quantity_ordered=20, unit_price=Decimal("5")))
    await session.flush()

    router = OrderRouter(session)
    decision = await router.route_order(order.id, "single_warehouse")
    assert len(decision.selected_warehouses) == 1


@pytest.mark.asyncio
async def test_routing_creates_fulfillment_plans(session, sample_warehouse, sample_sku, stocked_balance):
    order = Order(
        external_order_id="ROUTE-PLAN-001",
        customer_id="C1",
        ship_to_address={"city": "X"},
    )
    session.add(order)
    await session.flush()
    session.add(OrderLine(order_id=order.id, sku_id=sample_sku.id, quantity_ordered=10, unit_price=Decimal("5")))
    await session.flush()

    router = OrderRouter(session)
    await router.route_order(order.id)
    plans = await router.plan_repo.get_plans_for_order(order.id)
    assert len(plans) >= 1


@pytest.mark.asyncio
async def test_routing_score_calculation(session, sample_warehouse, sample_sku, stocked_balance):
    order = Order(
        external_order_id="ROUTE-SCORE-001",
        customer_id="C1",
        ship_to_address={"city": "X"},
    )
    session.add(order)
    await session.flush()
    session.add(OrderLine(order_id=order.id, sku_id=sample_sku.id, quantity_ordered=5, unit_price=Decimal("5")))
    await session.flush()

    router = OrderRouter(session)
    decision = await router.route_order(order.id)
    assert decision.routing_score >= 0


@pytest.mark.asyncio
async def test_partial_coverage_marks_plan_partial(session, sample_warehouse, sample_sku):
    session.add(InventoryBalance(warehouse_id=sample_warehouse.id, sku_id=sample_sku.id, on_hand=5))
    await session.flush()

    order = Order(
        external_order_id="ROUTE-PARTIAL-001",
        customer_id="C1",
        ship_to_address={"city": "X"},
        allow_partial_fulfillment=True,
    )
    session.add(order)
    await session.flush()
    session.add(OrderLine(order_id=order.id, sku_id=sample_sku.id, quantity_ordered=20, unit_price=Decimal("5")))
    await session.flush()

    router = OrderRouter(session)
    decision = await router.route_order(order.id)
    assert decision.is_split_shipment or any(not c.can_fulfill_all for c in decision.candidates)
