"""Network-level inventory coordination service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.logging import get_logger
from nexusops.domain.inventory.allocation import AllocationEngine, AllocationRequest
from nexusops.domain.inventory.forecasting import ForecastEngine
from nexusops.domain.inventory.reconciliation import InventoryReconciler
from nexusops.domain.inventory.safety_stock import SafetyStockCalculator
from nexusops.domain.optimization.placement import InventoryPlacementOptimizer
from nexusops.repositories.inventory import InventoryBalanceRepository
from nexusops.repositories.warehouse import WarehouseRepository

logger = get_logger(__name__)


@dataclass
class NetworkSnapshot:
    timestamp: datetime
    warehouse_count: int
    sku_count: int
    total_on_hand: int
    total_available: int
    total_reserved: int
    warehouses: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)


@dataclass
class NetworkHealthReport:
    snapshot: NetworkSnapshot
    reconciliation_issues: int
    placement_recommendations: int
    forecast_drift_count: int
    overall_health: str


class NetworkCoordinator:
    """Coordinates inventory operations across the entire warehouse network."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.warehouse_repo = WarehouseRepository(session)
        self.balance_repo = InventoryBalanceRepository(session)
        self.reconciler = InventoryReconciler(session)
        self.safety_calc = SafetyStockCalculator(session)
        self.forecast_engine = ForecastEngine(session)
        self.placement_optimizer = InventoryPlacementOptimizer(session)
        self.allocation_engine = AllocationEngine(session)

    async def capture_snapshot(self) -> NetworkSnapshot:
        warehouses = await self.warehouse_repo.list_active()
        wh_data: list[dict[str, Any]] = []
        total_on_hand = 0
        total_available = 0
        total_reserved = 0
        sku_ids: set[uuid.UUID] = set()
        alerts: list[str] = []

        for wh in warehouses:
            balances = await self.balance_repo.list_by_warehouse(wh.id)
            wh_on_hand = sum(b.on_hand for b in balances)
            wh_available = sum(b.available for b in balances)
            wh_reserved = sum(b.reserved for b in balances)

            for b in balances:
                sku_ids.add(b.sku_id)

            total_on_hand += wh_on_hand
            total_available += wh_available
            total_reserved += wh_reserved

            util_pct = (wh_on_hand / wh.capacity_units * 100) if wh.capacity_units else 0
            if util_pct > 90:
                alerts.append(f"{wh.warehouse_code} near capacity ({util_pct:.0f}%)")

            wh_data.append({
                "warehouse_id": str(wh.id),
                "code": wh.warehouse_code,
                "on_hand": wh_on_hand,
                "available": wh_available,
                "reserved": wh_reserved,
                "utilization_pct": round(util_pct, 1),
            })

        return NetworkSnapshot(
            timestamp=datetime.now(timezone.utc),
            warehouse_count=len(warehouses),
            sku_count=len(sku_ids),
            total_on_hand=total_on_hand,
            total_available=total_available,
            total_reserved=total_reserved,
            warehouses=wh_data,
            alerts=alerts,
        )

    async def health_check(self) -> NetworkHealthReport:
        snapshot = await self.capture_snapshot()
        reconciliation_issues = 0
        placement_recommendations = 0
        drift_count = 0

        for wh_data in snapshot.warehouses:
            wh_id = uuid.UUID(wh_data["warehouse_id"])
            report = await self.reconciler.reconcile_warehouse(wh_id)
            reconciliation_issues += len(report.discrepancies)

        from sqlalchemy import select, distinct
        from nexusops.models.inventory import InventoryBalance
        stmt = select(distinct(InventoryBalance.sku_id)).limit(10)
        result = await self.session.execute(stmt)
        for (sku_id,) in result.all():
            plan = await self.placement_optimizer.analyze_network(sku_id)
            placement_recommendations += len(plan.recommendations)

        overall = "healthy"
        if reconciliation_issues > 0:
            overall = "degraded"
        if reconciliation_issues > 10 or len(snapshot.alerts) > 3:
            overall = "critical"

        return NetworkHealthReport(
            snapshot=snapshot,
            reconciliation_issues=reconciliation_issues,
            placement_recommendations=placement_recommendations,
            forecast_drift_count=drift_count,
            overall_health=overall,
        )

    async def fulfill_from_network(
        self,
        order_id: uuid.UUID,
        order_line_id: uuid.UUID,
        sku_id: uuid.UUID,
        quantity: int,
    ) -> dict[str, Any]:
        request = AllocationRequest(
            order_id=order_id,
            order_line_id=order_line_id,
            sku_id=sku_id,
            quantity=quantity,
            allow_split=True,
        )
        result = await self.allocation_engine.allocate(request)
        return {
            "total_allocated": result.total_allocated,
            "backorder": result.backorder_quantity,
            "warehouses": [
                {"warehouse_id": str(w), "quantity": q}
                for w, q in result.allocations
            ],
        }

    async def refresh_safety_stock_all(self) -> int:
        from sqlalchemy import select, distinct
        from nexusops.models.inventory import SafetyStockPolicy

        stmt = select(SafetyStockPolicy.warehouse_id, SafetyStockPolicy.sku_id)
        result = await self.session.execute(stmt)
        count = 0
        for wh_id, sku_id in result.all():
            await self.safety_calc.calculate(wh_id, sku_id)
            count += 1
        return count
