"""Fulfillment orchestration service."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.types import OrderStatus
from nexusops.domain.fulfillment.planning import FulfillmentPlanner, FulfillmentPlanResult
from nexusops.domain.fulfillment.routing import OrderRouter, RoutingDecision
from nexusops.domain.fulfillment.shipment_generation import ShipmentGenerator
from nexusops.models.fulfillment import Order
from nexusops.repositories.fulfillment import OrderRepository
from nexusops.services.audit_service import AuditService


class FulfillmentService:
    """Orchestrates order fulfillment from routing through shipment generation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_repo = OrderRepository(session)
        self.planner = FulfillmentPlanner(session)
        self.router = OrderRouter(session)
        self.shipment_generator = ShipmentGenerator(session)
        self.audit = AuditService(session)

    async def create_order(
        self,
        external_order_id: str,
        customer_id: str,
        ship_to_address: dict,
        lines: list[dict],
        priority: int = 5,
        allow_partial: bool = True,
        routing_strategy: str = "cost_optimized",
    ) -> Order:
        order = Order(
            external_order_id=external_order_id,
            customer_id=customer_id,
            ship_to_address=ship_to_address,
            priority=priority,
            allow_partial_fulfillment=allow_partial,
            routing_strategy=routing_strategy,
            status=OrderStatus.RECEIVED,
        )
        await self.order_repo.add(order)

        from nexusops.models.fulfillment import OrderLine
        from decimal import Decimal
        for line_data in lines:
            line = OrderLine(
                order_id=order.id,
                sku_id=uuid.UUID(str(line_data["sku_id"])),
                quantity_ordered=line_data["quantity"],
                unit_price=Decimal(str(line_data.get("unit_price", "0"))),
            )
            self.session.add(line)

        await self.audit.record(
            entity_type="order",
            entity_id=order.id,
            action="created",
            after_state={"external_order_id": external_order_id, "status": OrderStatus.RECEIVED},
        )
        return order

    async def process_order(self, order_id: uuid.UUID) -> FulfillmentPlanResult:
        result = await self.planner.plan_fulfillment(order_id)
        await self.audit.record(
            entity_type="order",
            entity_id=order_id,
            action="fulfillment_planned",
            after_state={"status": result.status, "is_partial": result.is_partial},
        )
        return result

    async def route_order(self, order_id: uuid.UUID, strategy: str | None = None) -> RoutingDecision:
        order = await self.order_repo.get_by_id_or_raise(order_id)
        return await self.router.route_order(order_id, strategy or order.routing_strategy)

    async def generate_shipments(self, order_id: uuid.UUID) -> list:
        shipments = await self.shipment_generator.generate_for_order(order_id)
        for shipment in shipments:
            await self.audit.record_shipment_transition(
                shipment.id, "none", shipment.status
            )
        return shipments
