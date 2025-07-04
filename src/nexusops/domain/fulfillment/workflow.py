"""End-to-end order fulfillment workflow orchestration."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.context import WorkflowContext, get_correlation_id
from nexusops.core.dependency_graph import DependencyGraph, DependencyNode, NodeType
from nexusops.core.exceptions import WorkflowError
from nexusops.core.logging import get_logger
from nexusops.core.types import EventType, OrderStatus
from nexusops.core.workflow import WorkflowOrchestrator
from nexusops.domain.fulfillment.planning import FulfillmentPlanner
from nexusops.domain.fulfillment.shipment_generation import ShipmentGenerator
from nexusops.domain.inventory.allocation import AllocationEngine
from nexusops.domain.transportation.carrier_assignment import CarrierAssigner
from nexusops.domain.transportation.routing import RoutePlanner
from nexusops.events.bus import EventBus
from nexusops.events.schemas import DomainEventPayload
from nexusops.repositories.fulfillment import OrderRepository

logger = get_logger(__name__)


class OrderFulfillmentWorkflow:
    """Multi-step saga for complete order fulfillment."""

    def __init__(
        self,
        session: AsyncSession,
        event_bus: EventBus | None = None,
    ) -> None:
        self.session = session
        self.event_bus = event_bus
        self.order_repo = OrderRepository(session)
        self.planner = FulfillmentPlanner(session)
        self.allocation_engine = AllocationEngine(session)
        self.shipment_generator = ShipmentGenerator(session)
        self.route_planner = RoutePlanner(session)
        self.carrier_assigner = CarrierAssigner(session)
        self.dependency_graph = DependencyGraph()

    async def execute(self, order_id: uuid.UUID) -> dict[str, Any]:
        ctx = WorkflowContext(
            steps_pending=[
                "validate",
                "plan",
                "allocate",
                "generate_shipments",
                "plan_routes",
                "assign_carriers",
                "finalize",
            ]
        )
        ctx.metadata["order_id"] = str(order_id)
        results: dict[str, Any] = {"order_id": str(order_id), "workflow_id": ctx.workflow_id}

        try:
            order = await self._step_validate(order_id, ctx)
            plan_result = await self._step_plan(order_id, ctx)
            results["plan"] = {"status": plan_result.status, "is_partial": plan_result.is_partial}

            await self._step_allocate(order_id, ctx)
            shipments = await self._step_generate_shipments(order_id, ctx)
            results["shipments"] = [str(s.id) for s in shipments]

            for shipment in shipments:
                self.dependency_graph.add_node(
                    DependencyNode(shipment.id, NodeType.SHIPMENT, shipment.status)
                )
                await self._step_plan_routes(shipment.id, ctx)
                await self._step_assign_carrier(shipment.id, ctx)

            self.dependency_graph.validate_no_cycles()
            await self._step_finalize(order, ctx)
            results["status"] = order.status
            return results

        except Exception as exc:
            logger.error("fulfillment_workflow_failed", order_id=str(order_id), error=str(exc))
            await self._compensate(order_id, ctx)
            raise WorkflowError(
                f"Fulfillment workflow failed for order {order_id}: {exc}",
                details={"workflow_id": ctx.workflow_id, "completed": ctx.steps_completed},
            ) from exc

    async def _step_validate(self, order_id: uuid.UUID, ctx: WorkflowContext):
        order = await self.order_repo.get_with_lines(order_id)
        if not order:
            raise WorkflowError(f"Order {order_id} not found")
        if order.status in (OrderStatus.CANCELLED, OrderStatus.DELIVERED):
            raise WorkflowError(f"Order {order_id} in terminal state")
        self.dependency_graph.add_node(DependencyNode(order.id, NodeType.ORDER, order.status))
        ctx.mark_step_complete("validate")
        return order

    async def _step_plan(self, order_id: uuid.UUID, ctx: WorkflowContext):
        result = await self.planner.plan_fulfillment(order_id)
        ctx.mark_step_complete("plan")
        if self.event_bus:
            await self.event_bus.publish(
                DomainEventPayload(
                    event_type=EventType.FULFILLMENT_PLANNED,
                    aggregate_type="order",
                    aggregate_id=order_id,
                    payload={"status": result.status, "is_partial": result.is_partial},
                    correlation_id=str(get_correlation_id()),
                )
            )
        return result

    async def _step_allocate(self, order_id: uuid.UUID, ctx: WorkflowContext) -> None:
        ctx.mark_step_complete("allocate")

    async def _step_generate_shipments(self, order_id: uuid.UUID, ctx: WorkflowContext) -> list:
        shipments = await self.shipment_generator.generate_for_order(order_id)
        ctx.mark_step_complete("generate_shipments")
        for s in shipments:
            if self.event_bus:
                await self.event_bus.publish(
                    DomainEventPayload(
                        event_type=EventType.SHIPMENT_CREATED,
                        aggregate_type="shipment",
                        aggregate_id=s.id,
                        payload={"shipment_number": s.shipment_number, "order_id": str(order_id)},
                        correlation_id=str(get_correlation_id()),
                    )
                )
        return shipments

    async def _step_plan_routes(self, shipment_id: uuid.UUID, ctx: WorkflowContext) -> None:
        await self.route_planner.plan_routes(shipment_id)

    async def _step_assign_carrier(self, shipment_id: uuid.UUID, ctx: WorkflowContext) -> None:
        await self.carrier_assigner.assign_carrier(shipment_id)

    async def _step_finalize(self, order, ctx: WorkflowContext) -> None:
        order.status = OrderStatus.FULFILLMENT_PLANNED
        ctx.mark_step_complete("plan_routes")
        ctx.mark_step_complete("assign_carriers")
        ctx.mark_step_complete("finalize")

    async def _compensate(self, order_id: uuid.UUID, ctx: WorkflowContext) -> None:
        if "allocate" in ctx.steps_completed:
            await self.allocation_engine.release_reservations(order_id)
            logger.info("compensation_released_reservations", order_id=str(order_id))
