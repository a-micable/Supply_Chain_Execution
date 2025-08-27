"""Shipment state machine tests."""

from __future__ import annotations

import uuid

import pytest

from nexusops.core.exceptions import ShipmentStateError
from nexusops.core.types import ShipmentStatus
from nexusops.domain.fulfillment.shipment_generation import ShipmentGenerator, VALID_TRANSITIONS
from nexusops.models.fulfillment import FulfillmentPlan, Order
from nexusops.models.transportation import Shipment


@pytest.mark.asyncio
async def test_valid_state_transitions(session, sample_warehouse):
    order = Order(
        external_order_id="ORD-001",
        customer_id="CUST-001",
        ship_to_address={"city": "NYC"},
        status="fulfillment_planned",
    )
    session.add(order)
    await session.flush()

    plan = FulfillmentPlan(
        order_id=order.id,
        warehouse_id=sample_warehouse.id,
        status="planned",
    )
    session.add(plan)
    await session.flush()

    generator = ShipmentGenerator(session)
    shipment = await generator.generate_from_plan(plan.id)
    assert shipment.status == ShipmentStatus.DRAFT

    shipment = await generator.transition_state(shipment.id, ShipmentStatus.PLANNED)
    assert shipment.status == ShipmentStatus.PLANNED

    shipment = await generator.transition_state(shipment.id, ShipmentStatus.LABEL_GENERATED)
    shipment = await generator.transition_state(shipment.id, ShipmentStatus.IN_TRANSIT)
    assert shipment.status == ShipmentStatus.IN_TRANSIT
    assert len(shipment.state_history) >= 3


@pytest.mark.asyncio
async def test_invalid_state_transition_raises(session, sample_warehouse):
    shipment = Shipment(
        shipment_number="SHP-TEST-001",
        warehouse_id=sample_warehouse.id,
        status=ShipmentStatus.DRAFT,
        origin_address={"city": "A"},
        destination_address={"city": "B"},
    )
    session.add(shipment)
    await session.flush()

    generator = ShipmentGenerator(session)
    with pytest.raises(ShipmentStateError):
        await generator.transition_state(shipment.id, ShipmentStatus.DELIVERED)


@pytest.mark.asyncio
async def test_state_history_recorded(session, sample_warehouse):
    shipment = Shipment(
        shipment_number="SHP-TEST-002",
        warehouse_id=sample_warehouse.id,
        status=ShipmentStatus.PLANNED,
        origin_address={"city": "A"},
        destination_address={"city": "B"},
        state_history=[{"status": "planned", "timestamp": "2025-01-01T00:00:00Z"}],
    )
    session.add(shipment)
    await session.flush()

    generator = ShipmentGenerator(session)
    await generator.transition_state(shipment.id, ShipmentStatus.LABEL_GENERATED)
    updated = await generator.shipment_repo.get_by_id(shipment.id)
    assert len(updated.state_history) == 2
    assert updated.state_history[-1]["status"] == ShipmentStatus.LABEL_GENERATED
