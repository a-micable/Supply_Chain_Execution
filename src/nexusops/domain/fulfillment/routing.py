"""Order routing engine for multi-warehouse fulfillment."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.exceptions import RoutingConflictError
from nexusops.core.logging import get_logger
from nexusops.models.fulfillment import FulfillmentPlan
from nexusops.repositories.fulfillment import FulfillmentPlanRepository, OrderRepository
from nexusops.repositories.inventory import InventoryBalanceRepository
from nexusops.repositories.warehouse import WarehouseRepository

logger = get_logger(__name__)


@dataclass
class RoutingCandidate:
    warehouse_id: uuid.UUID
    warehouse_code: str
    total_available: int
    fulfillment_cost: Decimal
    transit_days: int
    priority: int
    can_fulfill_all: bool
    line_coverage: dict[uuid.UUID, int] = field(default_factory=dict)


@dataclass
class RoutingDecision:
    order_id: uuid.UUID
    strategy: str
    candidates: list[RoutingCandidate]
    selected_warehouses: list[uuid.UUID]
    is_split_shipment: bool
    estimated_total_cost: Decimal
    routing_score: float


class OrderRouter:
    """Routes orders to optimal fulfillment warehouses."""

    STRATEGIES = ("cost_optimized", "speed_optimized", "single_warehouse", "balanced")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_repo = OrderRepository(session)
        self.warehouse_repo = WarehouseRepository(session)
        self.balance_repo = InventoryBalanceRepository(session)
        self.plan_repo = FulfillmentPlanRepository(session)

    async def route_order(
        self, order_id: uuid.UUID, strategy: str = "cost_optimized"
    ) -> RoutingDecision:
        order = await self.order_repo.get_with_lines(order_id)
        if order is None:
            raise RoutingConflictError(f"Order {order_id} not found")

        if strategy not in self.STRATEGIES:
            strategy = "cost_optimized"

        candidates = await self._evaluate_candidates(order)
        if not candidates:
            raise RoutingConflictError(
                f"No fulfillment candidates for order {order_id}",
                details={"order_id": str(order_id)},
            )

        selected = self._select_warehouses(candidates, strategy, order.allow_partial_fulfillment)
        if not selected:
            raise RoutingConflictError(
                f"Unable to route order {order_id} with strategy {strategy}"
            )

        total_cost = sum(c.fulfillment_cost for c in selected)
        is_split = len(selected) > 1
        score = self._compute_routing_score(selected, strategy)

        decision = RoutingDecision(
            order_id=order_id,
            strategy=strategy,
            candidates=candidates,
            selected_warehouses=[c.warehouse_id for c in selected],
            is_split_shipment=is_split,
            estimated_total_cost=total_cost,
            routing_score=score,
        )

        await self._create_fulfillment_plans(order_id, selected, decision)
        logger.info(
            "order_routed",
            order_id=str(order_id),
            warehouses=len(selected),
            strategy=strategy,
            score=score,
        )
        return decision

    async def _evaluate_candidates(self, order) -> list[RoutingCandidate]:
        warehouses = await self.warehouse_repo.list_active()
        candidates: list[RoutingCandidate] = []

        for warehouse in warehouses:
            line_coverage: dict[uuid.UUID, int] = {}
            total_available = 0
            can_fulfill_all = True

            for line in order.lines:
                available = await self.balance_repo.get_aggregated_available(
                    warehouse.id, line.sku_id
                )
                needed = line.quantity_ordered - line.quantity_allocated
                covered = min(available, needed)
                line_coverage[line.id] = covered
                total_available += covered
                if covered < needed:
                    can_fulfill_all = False

            if total_available == 0:
                continue

            cost = Decimal(str(warehouse.fulfillment_priority * 10 + 50))
            candidates.append(
                RoutingCandidate(
                    warehouse_id=warehouse.id,
                    warehouse_code=warehouse.warehouse_code,
                    total_available=total_available,
                    fulfillment_cost=cost,
                    transit_days=warehouse.fulfillment_priority + 2,
                    priority=warehouse.fulfillment_priority,
                    can_fulfill_all=can_fulfill_all,
                    line_coverage=line_coverage,
                )
            )

        return candidates

    def _select_warehouses(
        self,
        candidates: list[RoutingCandidate],
        strategy: str,
        allow_partial: bool,
    ) -> list[RoutingCandidate]:
        if strategy == "single_warehouse":
            full = [c for c in candidates if c.can_fulfill_all]
            if full:
                return [min(full, key=lambda c: c.fulfillment_cost)]
            if allow_partial:
                return [max(candidates, key=lambda c: c.total_available)]
            return []

        if strategy == "speed_optimized":
            return sorted(candidates, key=lambda c: c.transit_days)[:2]

        if strategy == "cost_optimized":
            return sorted(candidates, key=lambda c: c.fulfillment_cost)[:2]

        return sorted(
            candidates,
            key=lambda c: c.routing_score if hasattr(c, "routing_score") else -c.total_available,
        )[:2]

    def _compute_routing_score(
        self, selected: list[RoutingCandidate], strategy: str
    ) -> float:
        if not selected:
            return 0.0
        coverage = sum(c.total_available for c in selected)
        cost_factor = 1.0 / (1.0 + float(sum(c.fulfillment_cost for c in selected)))
        speed_factor = 1.0 / (1.0 + sum(c.transit_days for c in selected) / len(selected))
        if strategy == "speed_optimized":
            return coverage * 0.3 + speed_factor * 0.7
        return coverage * 0.5 + cost_factor * 0.5

    async def _create_fulfillment_plans(
        self,
        order_id: uuid.UUID,
        selected: list[RoutingCandidate],
        decision: RoutingDecision,
    ) -> None:
        for candidate in selected:
            existing = await self.plan_repo.get_active_plan(order_id, candidate.warehouse_id)
            if existing:
                continue
            plan = FulfillmentPlan(
                order_id=order_id,
                warehouse_id=candidate.warehouse_id,
                status="planned",
                estimated_cost=candidate.fulfillment_cost,
                routing_score=Decimal(str(round(decision.routing_score, 4))),
                plan_details={
                    "line_coverage": {str(k): v for k, v in candidate.line_coverage.items()},
                    "strategy": decision.strategy,
                },
                is_partial=not candidate.can_fulfill_all,
            )
            await self.plan_repo.add(plan)
