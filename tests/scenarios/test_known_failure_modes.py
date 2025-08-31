"""Scenario tests mirroring production failure modes for regression coverage."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from nexusops.core.dependency_graph import DependencyGraph, DependencyNode, NodeType
from nexusops.core.exceptions import (
    EventOrderingError,
    InsufficientInventoryError,
    RoutingConflictError,
    ShipmentStateError,
)
from nexusops.domain.inventory.allocation import AllocationEngine, AllocationRequest
from nexusops.domain.inventory.reconciliation import InventoryReconciler
from nexusops.events.ordering import EventOrderingValidator
from nexusops.models.events import DomainEvent
from nexusops.models.fulfillment import FulfillmentPlan, Order, OrderLine
from nexusops.models.inventory import InventoryBalance, InventoryReservation
from nexusops.models.transportation import Shipment
from nexusops.models.warehouse import Warehouse


class TestAllocationInconsistencies:
    """Scenarios where allocation state diverges from inventory balances."""

    @pytest.mark.asyncio
    async def test_concurrent_allocation_exhausts_available(self, session, sample_warehouse, sample_sku):
        balance = InventoryBalance(
            warehouse_id=sample_warehouse.id, sku_id=sample_sku.id, on_hand=100
        )
        session.add(balance)
        await session.flush()

        engine = AllocationEngine(session)
        req1 = AllocationRequest(
            order_id=uuid.uuid4(), order_line_id=uuid.uuid4(),
            sku_id=sample_sku.id, quantity=60,
            preferred_warehouse_id=sample_warehouse.id,
        )
        req2 = AllocationRequest(
            order_id=uuid.uuid4(), order_line_id=uuid.uuid4(),
            sku_id=sample_sku.id, quantity=60,
            preferred_warehouse_id=sample_warehouse.id,
            allow_split=False,
        )
        r1 = await engine.allocate(req1)
        assert r1.total_allocated == 60

        with pytest.raises(InsufficientInventoryError):
            await engine.allocate(req2)

    @pytest.mark.asyncio
    async def test_reserved_exceeds_on_hand_detected_by_reconciler(
        self, session, sample_warehouse, sample_sku
    ):
        balance = InventoryBalance(
            warehouse_id=sample_warehouse.id, sku_id=sample_sku.id,
            on_hand=50, reserved=80,
        )
        session.add(balance)
        await session.flush()

        reconciler = InventoryReconciler(session)
        report = await reconciler.reconcile_warehouse(sample_warehouse.id)
        assert not report.is_balanced


class TestInventorySynchronizationFailures:
    """Cross-system inventory sync failure scenarios."""

    @pytest.mark.asyncio
    async def test_reservation_table_diverges_from_balance(
        self, session, sample_warehouse, sample_sku, stocked_balance
    ):
        stocked_balance.reserved = 75
        session.add(InventoryReservation(
            order_id=uuid.uuid4(), order_line_id=uuid.uuid4(),
            warehouse_id=sample_warehouse.id, sku_id=sample_sku.id,
            quantity=30, status="active",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        await session.flush()

        reconciler = InventoryReconciler(session)
        report = await reconciler.reconcile_warehouse(sample_warehouse.id)
        mismatches = [d for d in report.discrepancies if d.discrepancy_type == "reservation_mismatch"]
        assert len(mismatches) == 1
        assert mismatches[0].reserved_in_balance == 75
        assert mismatches[0].reserved_in_reservations == 30


class TestRoutingConflicts:
    """Order routing conflict scenarios."""

    @pytest.mark.asyncio
    async def test_no_inventory_anywhere_blocks_routing(self, session, sample_sku):
        wh = Warehouse(warehouse_code="WH-EMPTY", name="Empty WH", address={"city": "X"})
        session.add(wh)
        await session.flush()

        order = Order(
            external_order_id="ORD-NOINV",
            customer_id="C1",
            ship_to_address={"city": "Y"},
            status="received",
        )
        session.add(order)
        await session.flush()
        session.add(OrderLine(
            order_id=order.id, sku_id=sample_sku.id,
            quantity_ordered=10, unit_price=Decimal("1"),
        ))
        await session.flush()

        from nexusops.domain.fulfillment.routing import OrderRouter
        router = OrderRouter(session)
        with pytest.raises(RoutingConflictError):
            await router.route_order(order.id)


class TestShipmentStateCorruption:
    """Invalid shipment state transition scenarios."""

    @pytest.mark.asyncio
    async def test_skip_state_transition_rejected(self, session, sample_warehouse):
        shipment = Shipment(
            shipment_number="SHP-CORRUPT-001",
            warehouse_id=sample_warehouse.id,
            status="draft",
            origin_address={"city": "A"},
            destination_address={"city": "B"},
        )
        session.add(shipment)
        await session.flush()

        from nexusops.domain.fulfillment.shipment_generation import ShipmentGenerator
        gen = ShipmentGenerator(session)
        with pytest.raises(ShipmentStateError):
            await gen.transition_state(shipment.id, "in_transit")

    @pytest.mark.asyncio
    async def test_delivered_shipment_is_terminal(self, session, sample_warehouse):
        shipment = Shipment(
            shipment_number="SHP-CORRUPT-002",
            warehouse_id=sample_warehouse.id,
            status="delivered",
            origin_address={"city": "A"},
            destination_address={"city": "B"},
        )
        session.add(shipment)
        await session.flush()

        from nexusops.domain.fulfillment.shipment_generation import ShipmentGenerator
        gen = ShipmentGenerator(session)
        with pytest.raises(ShipmentStateError):
            await gen.transition_state(shipment.id, "in_transit")


class TestEventOrderingIssues:
    """Out-of-order event processing scenarios."""

    @pytest.mark.asyncio
    async def test_missing_sequence_number_in_stream(self, session):
        agg_id = uuid.uuid4()
        for seq in [1, 2, 5, 6]:
            session.add(DomainEvent(
                event_type="inventory.adjusted",
                aggregate_type="inventory", aggregate_id=agg_id,
                sequence_number=seq, correlation_id="c1",
                payload={}, occurred_at=datetime.now(timezone.utc),
            ))
        await session.flush()

        validator = EventOrderingValidator(session)
        violations = await validator.validate_aggregate("inventory", agg_id)
        assert len(violations) >= 1

    @pytest.mark.asyncio
    async def test_duplicate_sequence_detected(self, session):
        agg_id = uuid.uuid4()
        for _ in range(2):
            session.add(DomainEvent(
                event_type="test", aggregate_type="test", aggregate_id=agg_id,
                sequence_number=1, correlation_id="c", payload={},
                occurred_at=datetime.now(timezone.utc),
            ))
        await session.flush()

        validator = EventOrderingValidator(session)
        with pytest.raises(EventOrderingError):
            await validator.validate_and_raise("test", agg_id)


class TestDependencyGraphInconsistencies:
    """Workflow dependency graph failure scenarios."""

    def test_shipment_before_allocation_confirmed(self):
        graph = DependencyGraph()
        alloc_id, ship_id = uuid.uuid4(), uuid.uuid4()
        graph.add_node(DependencyNode(alloc_id, NodeType.ALLOCATION, "pending"))
        graph.add_node(DependencyNode(ship_id, NodeType.SHIPMENT, "planned"))
        graph.add_dependency(ship_id, alloc_id)

        issues = graph.validate_shipment_dependencies(ship_id)
        assert any("not confirmed" in i for i in issues)

    def test_circular_fulfillment_dependency(self):
        graph = DependencyGraph()
        nodes = [uuid.uuid4() for _ in range(3)]
        types = [NodeType.ORDER, NodeType.FULFILLMENT_PLAN, NodeType.SHIPMENT]
        for nid, nt in zip(nodes, types):
            graph.add_node(DependencyNode(nid, nt, "active"))
        graph.add_dependency(nodes[1], nodes[0])
        graph.add_dependency(nodes[2], nodes[1])
        graph.add_dependency(nodes[0], nodes[2])

        from nexusops.core.exceptions import DependencyGraphError
        with pytest.raises(DependencyGraphError):
            graph.validate_no_cycles()


class TestMultiStepWorkflowFailures:
    """Partial workflow completion scenarios."""

    @pytest.mark.asyncio
    async def test_fulfillment_plan_without_allocation(
        self, session, sample_warehouse, sample_sku
    ):
        order = Order(
            external_order_id="ORD-PARTIAL-WF",
            customer_id="C1",
            ship_to_address={"city": "Z"},
            status="received",
        )
        session.add(order)
        await session.flush()
        session.add(OrderLine(
            order_id=order.id, sku_id=sample_sku.id,
            quantity_ordered=50, unit_price=Decimal("10"),
        ))
        session.add(FulfillmentPlan(
            order_id=order.id, warehouse_id=sample_warehouse.id, status="planned",
        ))
        await session.flush()

        from nexusops.domain.fulfillment.routing import OrderRouter
        router = OrderRouter(session)
        with pytest.raises(RoutingConflictError):
            await router.route_order(order.id)


class TestCrossWarehouseReconciliation:
    """Multi-warehouse inventory reconciliation scenarios."""

    @pytest.mark.asyncio
    async def test_network_reconciliation_aggregates_all_warehouses(
        self, session, sample_sku
    ):
        wh_ids = []
        for i in range(3):
            wh = Warehouse(
                warehouse_code=f"WH-REC-{i}", name=f"WH {i}",
                address={"city": f"C{i}"},
            )
            session.add(wh)
            await session.flush()
            wh_ids.append(wh.id)
            session.add(InventoryBalance(
                warehouse_id=wh.id, sku_id=sample_sku.id,
                on_hand=100 * (i + 1), reserved=i * 10,
            ))
        await session.flush()

        reconciler = InventoryReconciler(session)
        report = await reconciler.reconcile_network(wh_ids)
        assert report.warehouses_checked == 3
        assert report.skus_checked == 3
