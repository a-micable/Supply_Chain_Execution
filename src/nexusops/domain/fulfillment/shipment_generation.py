"""Shipment generation from fulfillment plans."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.exceptions import ShipmentStateError
from nexusops.core.logging import get_logger
from nexusops.core.types import ShipmentStatus
from nexusops.models.transportation import Shipment, ShipmentStop
from nexusops.repositories.fulfillment import FulfillmentPlanRepository, OrderRepository
from nexusops.repositories.transportation import ShipmentRepository
from nexusops.repositories.warehouse import WarehouseRepository

logger = get_logger(__name__)

VALID_TRANSITIONS: dict[str, set[str]] = {
    ShipmentStatus.DRAFT: {ShipmentStatus.PLANNED, ShipmentStatus.CANCELLED},
    ShipmentStatus.PLANNED: {
        ShipmentStatus.CONSOLIDATED,
        ShipmentStatus.LABEL_GENERATED,
        ShipmentStatus.CANCELLED,
    },
    ShipmentStatus.CONSOLIDATED: {ShipmentStatus.LABEL_GENERATED, ShipmentStatus.CANCELLED},
    ShipmentStatus.LABEL_GENERATED: {ShipmentStatus.IN_TRANSIT, ShipmentStatus.CANCELLED},
    ShipmentStatus.IN_TRANSIT: {
        ShipmentStatus.OUT_FOR_DELIVERY,
        ShipmentStatus.EXCEPTION,
        ShipmentStatus.DELIVERED,
    },
    ShipmentStatus.OUT_FOR_DELIVERY: {ShipmentStatus.DELIVERED, ShipmentStatus.EXCEPTION},
    ShipmentStatus.EXCEPTION: {ShipmentStatus.IN_TRANSIT, ShipmentStatus.CANCELLED},
    ShipmentStatus.DELIVERED: set(),
    ShipmentStatus.CANCELLED: set(),
}


class ShipmentGenerator:
    """Creates shipments from fulfillment plans with state machine enforcement."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.shipment_repo = ShipmentRepository(session)
        self.plan_repo = FulfillmentPlanRepository(session)
        self.order_repo = OrderRepository(session)
        self.warehouse_repo = WarehouseRepository(session)

    async def generate_from_plan(
        self, fulfillment_plan_id: uuid.UUID
    ) -> Shipment:
        plan = await self.plan_repo.get_by_id_or_raise(fulfillment_plan_id)
        order = await self.order_repo.get_by_id_or_raise(plan.order_id)
        warehouse = await self.warehouse_repo.get_by_id_or_raise(plan.warehouse_id)

        shipment_number = f"SHP-{uuid.uuid4().hex[:12].upper()}"
        shipment = Shipment(
            shipment_number=shipment_number,
            order_id=order.id,
            warehouse_id=warehouse.id,
            status=ShipmentStatus.DRAFT,
            origin_address=warehouse.address,
            destination_address=order.ship_to_address,
            total_weight_kg=Decimal("0"),
            total_packages=1,
            state_history=[{
                "status": ShipmentStatus.DRAFT,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }],
        )
        await self.shipment_repo.add(shipment)

        origin_stop = ShipmentStop(
            shipment_id=shipment.id,
            sequence=1,
            stop_type="pickup",
            address=warehouse.address,
            status="pending",
        )
        dest_stop = ShipmentStop(
            shipment_id=shipment.id,
            sequence=2,
            stop_type="delivery",
            address=order.ship_to_address,
            status="pending",
        )
        self.session.add(origin_stop)
        self.session.add(dest_stop)

        plan.status = "executing"
        logger.info(
            "shipment_generated",
            shipment_number=shipment_number,
            order_id=str(order.id),
            warehouse_id=str(warehouse.id),
        )
        return shipment

    async def transition_state(
        self, shipment_id: uuid.UUID, new_status: str
    ) -> Shipment:
        shipment = await self.shipment_repo.get_by_id_or_raise(shipment_id)
        current = shipment.status

        allowed = VALID_TRANSITIONS.get(current, set())
        if new_status not in allowed:
            raise ShipmentStateError(shipment_id, current, new_status)

        history = list(shipment.state_history or [])
        history.append({
            "status": new_status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "previous": current,
        })
        shipment.status = new_status
        shipment.state_history = history
        shipment.version += 1

        if new_status == ShipmentStatus.DELIVERED:
            shipment.actual_delivery = datetime.now(timezone.utc)

        logger.info(
            "shipment_state_changed",
            shipment_id=str(shipment_id),
            from_status=current,
            to_status=new_status,
        )
        return shipment

    async def generate_for_order(self, order_id: uuid.UUID) -> list[Shipment]:
        plans = await self.plan_repo.get_plans_for_order(order_id)
        shipments = []
        for plan in plans:
            if plan.status in ("planned", "executing"):
                shipment = await self.generate_from_plan(plan.id)
                await self.transition_state(shipment.id, ShipmentStatus.PLANNED)
                shipments.append(shipment)
        return shipments
