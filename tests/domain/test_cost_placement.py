"""Tests for cost and placement optimization."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from nexusops.domain.optimization.cost import CostOptimizer
from nexusops.domain.optimization.placement import InventoryPlacementOptimizer
from nexusops.models.fulfillment import Order, OrderLine
from nexusops.models.inventory import InventoryBalance, SafetyStockPolicy
from nexusops.models.transportation import Carrier, Shipment
from nexusops.models.warehouse import Warehouse


@pytest.mark.asyncio
async def test_order_cost_breakdown(session, sample_sku):
    order = Order(
        external_order_id="COST-ORD-001",
        customer_id="C1",
        ship_to_address={"city": "X"},
    )
    session.add(order)
    await session.flush()
    session.add(OrderLine(
        order_id=order.id, sku_id=sample_sku.id,
        quantity_ordered=10, unit_price=Decimal("25.00"),
    ))
    await session.flush()

    optimizer = CostOptimizer(session)
    breakdown = await optimizer.analyze_order_cost(order.id)
    assert breakdown.total > 0
    categories = {c.category for c in breakdown.components}
    assert "picking" in categories
    assert "shipping" in categories


@pytest.mark.asyncio
async def test_cost_optimization_recommendations(session, sample_sku):
    order = Order(
        external_order_id="COST-OPT-001",
        customer_id="C1",
        ship_to_address={"city": "X"},
    )
    session.add(order)
    await session.flush()
    for i in range(5):
        session.add(OrderLine(
            order_id=order.id, sku_id=sample_sku.id,
            quantity_ordered=2, unit_price=Decimal("10.00"),
        ))
    await session.flush()

    optimizer = CostOptimizer(session)
    result = await optimizer.optimize_order_fulfillment_cost(order.id)
    assert result.original_cost > 0
    assert len(result.recommendations) >= 1


@pytest.mark.asyncio
async def test_carrier_cost_comparison(session, sample_warehouse):
    c1 = Carrier(carrier_code="C1", name="Carrier 1", cost_per_kg=Decimal("2.00"))
    c2 = Carrier(carrier_code="C2", name="Carrier 2", cost_per_kg=Decimal("1.50"))
    session.add_all([c1, c2])
    await session.flush()

    shipment = Shipment(
        shipment_number="SHP-COST-001",
        warehouse_id=sample_warehouse.id,
        status="planned",
        origin_address={"city": "A"},
        destination_address={"city": "B"},
        total_weight_kg=Decimal("20"),
        carrier_id=c1.id,
    )
    session.add(shipment)
    await session.flush()

    optimizer = CostOptimizer(session)
    costs = await optimizer.compare_carrier_costs(shipment.id)
    assert len(costs) == 2
    assert costs[0][1] <= costs[1][1]


@pytest.mark.asyncio
async def test_placement_rebalance_recommendation(session, sample_sku):
    wh1 = Warehouse(warehouse_code="WH-PL-1", name="WH1", address={"city": "A"})
    wh2 = Warehouse(warehouse_code="WH-PL-2", name="WH2", address={"city": "B"})
    session.add_all([wh1, wh2])
    await session.flush()

    session.add(InventoryBalance(warehouse_id=wh1.id, sku_id=sample_sku.id, on_hand=500))
    session.add(InventoryBalance(warehouse_id=wh2.id, sku_id=sample_sku.id, on_hand=5))
    session.add(SafetyStockPolicy(
        warehouse_id=wh2.id, sku_id=sample_sku.id,
        reorder_point=100, safety_stock_qty=50,
    ))
    await session.flush()

    optimizer = InventoryPlacementOptimizer(session)
    plan = await optimizer.analyze_network(sample_sku.id)
    assert len(plan.recommendations) >= 1
    assert plan.total_units_moved > 0


@pytest.mark.asyncio
async def test_fill_rate_impact_estimation(session, sample_warehouse, sample_sku, stocked_balance):
    session.add(SafetyStockPolicy(
        warehouse_id=sample_warehouse.id, sku_id=sample_sku.id,
        reorder_point=600, safety_stock_qty=100,
    ))
    await session.flush()

    optimizer = InventoryPlacementOptimizer(session)
    impact = await optimizer.estimate_fill_rate_impact(
        sample_sku.id, sample_warehouse.id, 200
    )
    assert impact >= 0
