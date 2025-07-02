"""Fulfillment planning and partial fulfillment handling."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.context import WorkflowContext, get_correlation_id
from nexusops.core.exceptions import WorkflowError
from nexusops.core.logging import get_logger
from nexusops.core.types import OrderStatus
from nexusops.domain.fulfillment.routing import OrderRouter
from nexusops.domain.inventory.allocation import AllocationEngine, AllocationRequest
from nexusops.repositories.fulfillment import FulfillmentPlanRepository, OrderRepository

logger = get_logger(__name__)


@dataclass
class FulfillmentLinePlan:
    order_line_id: uuid.UUID
    sku_id: uuid.UUID
    quantity_planned: int
    warehouse_id: uuid.UUID
    reservation_id: uuid.UUID | None = None


@dataclass
class FulfillmentPlanResult:
    order_id: uuid.UUID
    status: str
    lines: list[FulfillmentLinePlan] = field(default_factory=list)
    is_partial: bool = False
    backorder_lines: list[uuid.UUID] = field(default_factory=list)
    planned_ship_date: datetime | None = None
    workflow_id: str = ""


class FulfillmentPlanner:
    """Orchestrates order fulfillment planning workflow."""

    WORKFLOW_STEPS = [
        "validate_order",
        "route_order",
        "allocate_inventory",
        "create_fulfillment_plan",
        "schedule_shipment",
    ]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_repo = OrderRepository(session)
        self.plan_repo = FulfillmentPlanRepository(session)
        self.router = OrderRouter(session)
        self.allocation_engine = AllocationEngine(session)

    async def plan_fulfillment(self, order_id: uuid.UUID) -> FulfillmentPlanResult:
        ctx = WorkflowContext(steps_pending=list(self.WORKFLOW_STEPS))
        ctx.metadata["order_id"] = str(order_id)
        ctx.metadata["correlation_id"] = str(get_correlation_id())

        try:
            order = await self._validate_order(order_id, ctx)
            routing = await self._route_order(order_id, order.routing_strategy, ctx)
            allocation_results = await self._allocate_inventory(order, routing, ctx)
            result = await self._build_plan(order_id, allocation_results, ctx)
            await self._update_order_status(order, result, ctx)
            result.workflow_id = ctx.workflow_id
            return result
        except Exception as exc:
            logger.error(
                "fulfillment_planning_failed",
                order_id=str(order_id),
                workflow_id=ctx.workflow_id,
                completed_steps=ctx.steps_completed,
                error=str(exc),
            )
            raise WorkflowError(
                f"Fulfillment planning failed at step {ctx.steps_pending[0] if ctx.steps_pending else 'unknown'}: {exc}",
                details={
                    "workflow_id": ctx.workflow_id,
                    "completed_steps": ctx.steps_completed,
                    "pending_steps": ctx.steps_pending,
                },
            ) from exc

    async def handle_partial_fulfillment(
        self, order_id: uuid.UUID, accept_partial: bool = True
    ) -> FulfillmentPlanResult:
        result = await self.plan_fulfillment(order_id)
        if result.is_partial and not accept_partial:
            await self.allocation_engine.release_reservations(order_id)
            order = await self.order_repo.get_by_id_or_raise(order_id)
            order.status = OrderStatus.BACKORDERED
            raise WorkflowError(
                f"Order {order_id} cannot be fully fulfilled and partial fulfillment rejected"
            )
        return result

    async def _validate_order(self, order_id: uuid.UUID, ctx: WorkflowContext):
        order = await self.order_repo.get_with_lines(order_id)
        if order is None:
            raise WorkflowError(f"Order {order_id} not found")
        if not order.lines:
            raise WorkflowError(f"Order {order_id} has no lines")
        if order.status in (OrderStatus.SHIPPED, OrderStatus.DELIVERED, OrderStatus.CANCELLED):
            raise WorkflowError(f"Order {order_id} in terminal state: {order.status}")
        order.status = OrderStatus.VALIDATING
        ctx.mark_step_complete("validate_order")
        return order

    async def _route_order(
        self, order_id: uuid.UUID, strategy: str, ctx: WorkflowContext
    ):
        decision = await self.router.route_order(order_id, strategy)
        ctx.mark_step_complete("route_order")
        return decision

    async def _allocate_inventory(self, order, routing, ctx: WorkflowContext):
        results = []
        for warehouse_id in routing.selected_warehouses:
            for line in order.lines:
                needed = line.quantity_ordered - line.quantity_allocated
                if needed <= 0:
                    continue
                request = AllocationRequest(
                    order_id=order.id,
                    order_line_id=line.id,
                    sku_id=line.sku_id,
                    quantity=needed,
                    preferred_warehouse_id=warehouse_id,
                    allow_split=order.allow_partial_fulfillment,
                )
                try:
                    result = await self.allocation_engine.allocate(request)
                    results.append(result)
                    line.quantity_allocated += result.total_allocated
                    line.backorder_quantity = result.backorder_quantity
                except Exception as exc:
                    logger.warning(
                        "line_allocation_failed",
                        order_line_id=str(line.id),
                        error=str(exc),
                    )
        ctx.mark_step_complete("allocate_inventory")
        return results

    async def _build_plan(
        self, order_id: uuid.UUID, allocation_results, ctx: WorkflowContext
    ) -> FulfillmentPlanResult:
        result = FulfillmentPlanResult(
            order_id=order_id,
            status=OrderStatus.FULFILLMENT_PLANNED,
            planned_ship_date=datetime.now(timezone.utc) + timedelta(days=2),
        )
        for alloc in allocation_results:
            for warehouse_id, qty in alloc.allocations:
                result.lines.append(
                    FulfillmentLinePlan(
                        order_line_id=alloc.order_line_id,
                        sku_id=uuid.UUID(int=0),
                        quantity_planned=qty,
                        warehouse_id=warehouse_id,
                        reservation_id=alloc.reservation_ids[0] if alloc.reservation_ids else None,
                    )
                )
            if alloc.backorder_quantity > 0:
                result.is_partial = True
                result.backorder_lines.append(alloc.order_line_id)

        ctx.mark_step_complete("create_fulfillment_plan")
        ctx.mark_step_complete("schedule_shipment")
        return result

    async def _update_order_status(
        self, order, result: FulfillmentPlanResult, ctx: WorkflowContext
    ) -> None:
        if result.is_partial:
            order.status = OrderStatus.PARTIALLY_ALLOCATED
        else:
            order.status = OrderStatus.FULFILLMENT_PLANNED
