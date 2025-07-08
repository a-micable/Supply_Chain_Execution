"""Safety stock calculation using service level targets."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.config.settings import get_settings
from nexusops.core.logging import get_logger
from nexusops.models.inventory import SafetyStockPolicy
from nexusops.repositories.inventory import (
    InventoryBalanceRepository,
    InventoryForecastRepository,
    SafetyStockPolicyRepository,
)

logger = get_logger(__name__)

Z_SCORES = {
    0.90: 1.282,
    0.95: 1.645,
    0.97: 1.881,
    0.99: 2.326,
}


@dataclass
class SafetyStockResult:
    warehouse_id: uuid.UUID
    sku_id: uuid.UUID
    safety_stock_qty: int
    reorder_point: int
    avg_daily_demand: float
    demand_std_dev: float
    lead_time_days: int
    service_level: float


class SafetyStockCalculator:
    """Computes safety stock levels based on demand variability and lead time."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.policy_repo = SafetyStockPolicyRepository(session)
        self.forecast_repo = InventoryForecastRepository(session)
        self.balance_repo = InventoryBalanceRepository(session)
        self.settings = get_settings()

    async def calculate(
        self,
        warehouse_id: uuid.UUID,
        sku_id: uuid.UUID,
        service_level: float | None = None,
        lead_time_days: int | None = None,
    ) -> SafetyStockResult:
        sl = service_level or self.settings.safety_stock_service_level
        policy = await self.policy_repo.get_policy(warehouse_id, sku_id)

        lt = lead_time_days or (policy.lead_time_days if policy else 7)
        demand_stats = await self._compute_demand_statistics(warehouse_id, sku_id)

        z = self._z_score(sl)
        safety_stock = math.ceil(
            z * demand_stats.std_dev * math.sqrt(lt)
        )
        reorder_point = math.ceil(demand_stats.mean * lt + safety_stock)

        result = SafetyStockResult(
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            safety_stock_qty=safety_stock,
            reorder_point=reorder_point,
            avg_daily_demand=demand_stats.mean,
            demand_std_dev=demand_stats.std_dev,
            lead_time_days=lt,
            service_level=sl,
        )

        await self._persist_policy(result, policy)
        logger.info(
            "safety_stock_calculated",
            warehouse_id=str(warehouse_id),
            sku_id=str(sku_id),
            safety_stock=safety_stock,
            reorder_point=reorder_point,
        )
        return result

    async def recalculate_all(self) -> list[SafetyStockResult]:
        below_reorder = await self.policy_repo.list_below_reorder_point()
        results = []
        for policy, _ in below_reorder:
            result = await self.calculate(policy.warehouse_id, policy.sku_id)
            results.append(result)
        return results

    async def _compute_demand_statistics(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID
    ) -> "_DemandStats":
        from datetime import datetime, timedelta, timezone

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=90)
        forecasts = await self.forecast_repo.get_forecast_series(
            warehouse_id, sku_id, start, end
        )

        if not forecasts:
            return _DemandStats(mean=1.0, std_dev=0.5)

        demands = [f.predicted_demand for f in forecasts]
        n = len(demands)
        mean = sum(demands) / n
        variance = sum((d - mean) ** 2 for d in demands) / max(n - 1, 1)
        return _DemandStats(mean=mean, std_dev=math.sqrt(variance))

    def _z_score(self, service_level: float) -> float:
        closest = min(Z_SCORES.keys(), key=lambda k: abs(k - service_level))
        return Z_SCORES[closest]

    async def _persist_policy(
        self, result: SafetyStockResult, existing: SafetyStockPolicy | None
    ) -> None:
        if existing:
            existing.safety_stock_qty = result.safety_stock_qty
            existing.reorder_point = result.reorder_point
            existing.service_level = Decimal(str(result.service_level))
            existing.demand_std_dev = Decimal(str(result.demand_std_dev))
            existing.lead_time_days = result.lead_time_days
        else:
            policy = SafetyStockPolicy(
                warehouse_id=result.warehouse_id,
                sku_id=result.sku_id,
                safety_stock_qty=result.safety_stock_qty,
                reorder_point=result.reorder_point,
                service_level=Decimal(str(result.service_level)),
                demand_std_dev=Decimal(str(result.demand_std_dev)),
                lead_time_days=result.lead_time_days,
            )
            await self.policy_repo.add(policy)


@dataclass
class _DemandStats:
    mean: float
    std_dev: float
