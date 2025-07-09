"""Capacity planning across warehouse and transportation networks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.logging import get_logger
from nexusops.repositories.fulfillment import OrderRepository
from nexusops.repositories.inventory import InventoryBalanceRepository
from nexusops.repositories.transportation import ShipmentRepository
from nexusops.repositories.warehouse import WarehouseRepository

logger = get_logger(__name__)


@dataclass
class WarehouseCapacity:
    warehouse_id: uuid.UUID
    warehouse_code: str
    total_capacity: int
    used_capacity: int
    inbound_scheduled: int
    outbound_scheduled: int

    @property
    def utilization_pct(self) -> float:
        if self.total_capacity == 0:
            return 0.0
        return (self.used_capacity / self.total_capacity) * 100

    @property
    def available_capacity(self) -> int:
        return max(0, self.total_capacity - self.used_capacity)


@dataclass
class NetworkCapacitySnapshot:
    timestamp: datetime
    warehouses: list[WarehouseCapacity] = field(default_factory=list)
    total_utilization_pct: float = 0.0
    bottlenecks: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class CapacityForecast:
    warehouse_id: uuid.UUID
    forecast_date: datetime
    projected_utilization_pct: float
    projected_inbound: int
    projected_outbound: int
    overflow_risk: bool


class CapacityPlanner:
    """Plans and forecasts capacity utilization across the logistics network."""

    OVERFLOW_THRESHOLD_PCT = 90.0
    UNITS_PER_SKU_AVG = 1

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.warehouse_repo = WarehouseRepository(session)
        self.balance_repo = InventoryBalanceRepository(session)
        self.shipment_repo = ShipmentRepository(session)
        self.order_repo = OrderRepository(session)

    async def snapshot(self) -> NetworkCapacitySnapshot:
        warehouses = await self.warehouse_repo.list_active()
        capacities: list[WarehouseCapacity] = []

        for wh in warehouses:
            balances = await self.balance_repo.list_by_warehouse(wh.id)
            used = sum(b.on_hand + b.in_transit for b in balances)
            total = wh.capacity_units or 10000

            planned_shipments = await self.shipment_repo.list_by_status("planned")
            outbound = sum(1 for s in planned_shipments if s.warehouse_id == wh.id)

            pending_orders = await self.order_repo.list_pending_allocation()
            inbound = sum(1 for _ in pending_orders)

            cap = WarehouseCapacity(
                warehouse_id=wh.id,
                warehouse_code=wh.warehouse_code,
                total_capacity=total,
                used_capacity=used,
                inbound_scheduled=inbound,
                outbound_scheduled=outbound,
            )
            capacities.append(cap)

        total_cap = sum(c.total_capacity for c in capacities)
        total_used = sum(c.used_capacity for c in capacities)
        avg_util = (total_used / total_cap * 100) if total_cap > 0 else 0

        bottlenecks = [
            c.warehouse_code for c in capacities if c.utilization_pct > self.OVERFLOW_THRESHOLD_PCT
        ]
        recommendations = self._generate_recommendations(capacities, bottlenecks)

        return NetworkCapacitySnapshot(
            timestamp=datetime.now(timezone.utc),
            warehouses=capacities,
            total_utilization_pct=avg_util,
            bottlenecks=bottlenecks,
            recommendations=recommendations,
        )

    async def forecast(
        self, warehouse_id: uuid.UUID, horizon_days: int = 14
    ) -> list[CapacityForecast]:
        wh = await self.warehouse_repo.get_by_id_or_raise(warehouse_id)
        balances = await self.balance_repo.list_by_warehouse(warehouse_id)
        current_used = sum(b.on_hand for b in balances)
        total = wh.capacity_units or 10000

        forecasts: list[CapacityForecast] = []
        now = datetime.now(timezone.utc)

        for day in range(1, horizon_days + 1):
            date = now + timedelta(days=day)
            daily_inbound = 50 + (day * 5)
            daily_outbound = 45 + (day * 3)
            projected = current_used + (daily_inbound - daily_outbound) * day
            util_pct = (projected / total) * 100 if total > 0 else 0

            forecasts.append(
                CapacityForecast(
                    warehouse_id=warehouse_id,
                    forecast_date=date,
                    projected_utilization_pct=min(util_pct, 150.0),
                    projected_inbound=daily_inbound,
                    projected_outbound=daily_outbound,
                    overflow_risk=util_pct > self.OVERFLOW_THRESHOLD_PCT,
                )
            )

        return forecasts

    def _generate_recommendations(
        self, capacities: list[WarehouseCapacity], bottlenecks: list[str]
    ) -> list[str]:
        recs: list[str] = []
        for cap in capacities:
            if cap.warehouse_code in bottlenecks:
                recs.append(
                    f"Transfer excess inventory from {cap.warehouse_code} to lower-utilization warehouses"
                )
            if cap.outbound_scheduled > cap.inbound_scheduled * 2:
                recs.append(
                    f"Increase inbound receiving capacity at {cap.warehouse_code}"
                )
        if not recs:
            recs.append("Network capacity within normal operating parameters")
        return recs

    async def find_transfer_candidates(
        self, source_warehouse_id: uuid.UUID, target_utilization: float = 70.0
    ) -> list[dict]:
        snapshot = await self.snapshot()
        source = next(
            (c for c in snapshot.warehouses if c.warehouse_id == source_warehouse_id), None
        )
        if source is None:
            return []

        candidates = []
        for cap in snapshot.warehouses:
            if cap.warehouse_id == source_warehouse_id:
                continue
            if cap.utilization_pct < target_utilization and source.utilization_pct > 85:
                excess = source.used_capacity - int(source.total_capacity * 0.8)
                candidates.append({
                    "source": source.warehouse_code,
                    "destination": cap.warehouse_code,
                    "suggested_transfer_units": max(0, excess),
                    "destination_utilization": cap.utilization_pct,
                })
        return candidates
