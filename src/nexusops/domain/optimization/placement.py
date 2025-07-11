"""Network-wide inventory placement optimization."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.logging import get_logger
from nexusops.repositories.inventory import (
    InventoryBalanceRepository,
    InventoryForecastRepository,
    SafetyStockPolicyRepository,
)
from nexusops.repositories.warehouse import WarehouseRepository

logger = get_logger(__name__)


@dataclass
class PlacementRecommendation:
    sku_id: uuid.UUID
    source_warehouse_id: uuid.UUID | None
    target_warehouse_id: uuid.UUID
    quantity: int
    reason: str
    estimated_cost_savings: Decimal
    fill_rate_improvement: float


@dataclass
class PlacementPlan:
    plan_id: uuid.UUID
    recommendations: list[PlacementRecommendation] = field(default_factory=list)
    total_units_moved: int = 0
    total_savings: Decimal = Decimal("0")
    execution_priority: int = 5


class InventoryPlacementOptimizer:
    """Optimizes SKU placement across the warehouse network."""

    TRANSFER_COST_PER_UNIT = Decimal("0.50")
    STOCKOUT_PENALTY = Decimal("25.00")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.warehouse_repo = WarehouseRepository(session)
        self.balance_repo = InventoryBalanceRepository(session)
        self.forecast_repo = InventoryForecastRepository(session)
        self.policy_repo = SafetyStockPolicyRepository(session)

    async def analyze_network(self, sku_id: uuid.UUID) -> PlacementPlan:
        plan = PlacementPlan(plan_id=uuid.uuid4())
        visibility = await self.balance_repo.get_network_visibility(sku_id)
        if len(visibility) < 2:
            return plan

        warehouses = await self.warehouse_repo.list_active()
        wh_map = {w.id: w for w in warehouses}

        surplus: list[tuple[uuid.UUID, int]] = []
        deficit: list[tuple[uuid.UUID, int]] = []

        for wh_id, on_hand, reserved, available in visibility:
            policy = await self.policy_repo.get_policy(wh_id, sku_id)
            reorder = policy.reorder_point if policy else 50
            safety = policy.safety_stock_qty if policy else 25

            if available > reorder + safety * 2:
                surplus.append((wh_id, available - reorder - safety))
            elif available < reorder:
                deficit.append((wh_id, reorder - available))

        for def_wh, def_qty in deficit:
            for sur_wh, sur_qty in surplus:
                if sur_qty <= 0:
                    continue
                transfer_qty = min(def_qty, sur_qty)
                if transfer_qty <= 0:
                    continue

                cost = self.TRANSFER_COST_PER_UNIT * transfer_qty
                savings = self.STOCKOUT_PENALTY - cost

                plan.recommendations.append(
                    PlacementRecommendation(
                        sku_id=sku_id,
                        source_warehouse_id=sur_wh,
                        target_warehouse_id=def_wh,
                        quantity=transfer_qty,
                        reason="rebalance_to_reorder_point",
                        estimated_cost_savings=savings,
                        fill_rate_improvement=0.05,
                    )
                )
                plan.total_units_moved += transfer_qty
                plan.total_savings += savings
                def_qty -= transfer_qty
                surplus = [
                    (w, q - transfer_qty if w == sur_wh else q) for w, q in surplus
                ]

        if plan.total_units_moved > 100:
            plan.execution_priority = 2
        elif plan.total_units_moved > 0:
            plan.execution_priority = 4

        logger.info(
            "placement_plan_generated",
            sku_id=str(sku_id),
            recommendations=len(plan.recommendations),
            units=plan.total_units_moved,
        )
        return plan

    async def analyze_all_skus(self, limit: int = 50) -> list[PlacementPlan]:
        from sqlalchemy import select, distinct
        from nexusops.models.inventory import InventoryBalance

        stmt = select(distinct(InventoryBalance.sku_id)).limit(limit)
        result = await self.session.execute(stmt)
        sku_ids = [row[0] for row in result.all()]

        plans = []
        for sku_id in sku_ids:
            plan = await self.analyze_network(sku_id)
            if plan.recommendations:
                plans.append(plan)
        return sorted(plans, key=lambda p: p.execution_priority)

    async def estimate_fill_rate_impact(
        self, sku_id: uuid.UUID, warehouse_id: uuid.UUID, additional_units: int
    ) -> float:
        available = await self.balance_repo.get_aggregated_available(warehouse_id, sku_id)
        policy = await self.policy_repo.get_policy(warehouse_id, sku_id)
        reorder = policy.reorder_point if policy else 50

        before = min(1.0, available / max(reorder, 1))
        after = min(1.0, (available + additional_units) / max(reorder, 1))
        return after - before
