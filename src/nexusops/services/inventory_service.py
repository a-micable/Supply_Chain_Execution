"""Inventory network service orchestrating allocation, forecasting, and reconciliation."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.cache.redis_cache import RedisCache
from nexusops.core.context import get_correlation_id
from nexusops.core.types import EventType
from nexusops.domain.inventory.allocation import AllocationEngine, AllocationRequest, AllocationResult
from nexusops.domain.inventory.forecasting import ForecastEngine
from nexusops.domain.inventory.reconciliation import InventoryReconciler, ReconciliationReport
from nexusops.domain.inventory.safety_stock import SafetyStockCalculator, SafetyStockResult
from nexusops.events.bus import EventBus
from nexusops.events.schemas import DomainEventPayload
from nexusops.repositories.inventory import InventoryBalanceRepository
from nexusops.services.audit_service import AuditService


class InventoryService:
    """High-level inventory operations with caching and event publishing."""

    def __init__(
        self,
        session: AsyncSession,
        cache: RedisCache | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.session = session
        self.cache = cache
        self.event_bus = event_bus
        self.allocation_engine = AllocationEngine(session)
        self.safety_stock_calc = SafetyStockCalculator(session)
        self.forecast_engine = ForecastEngine(session)
        self.reconciler = InventoryReconciler(session)
        self.balance_repo = InventoryBalanceRepository(session)
        self.audit = AuditService(session)

    async def allocate_for_order_line(
        self, request: AllocationRequest
    ) -> AllocationResult:
        result = await self.allocation_engine.allocate(request)
        if self.cache:
            for warehouse_id, _ in result.allocations:
                await self.cache.invalidate_inventory(
                    str(warehouse_id), str(request.sku_id)
                )
        if self.event_bus:
            for warehouse_id, qty in result.allocations:
                await self.event_bus.publish(
                    DomainEventPayload(
                        event_type=EventType.ALLOCATION_CREATED,
                        aggregate_type="order",
                        aggregate_id=request.order_id,
                        payload={
                            "order_line_id": str(request.order_line_id),
                            "warehouse_id": str(warehouse_id),
                            "quantity": qty,
                        },
                        correlation_id=str(get_correlation_id()),
                    )
                )
        return result

    async def get_network_visibility(
        self, sku_id: uuid.UUID, use_cache: bool = True
    ) -> list[dict[str, Any]]:
        if self.cache and use_cache:
            cached = await self.cache.get(f"netvis:{sku_id}")
            if cached is not None:
                return cached

        visibility = await self.balance_repo.get_network_visibility(sku_id)
        result = [
            {
                "warehouse_id": str(v[0]),
                "on_hand": v[1],
                "reserved": v[2],
                "available": v[3],
            }
            for v in visibility
        ]

        if self.cache:
            await self.cache.set(f"netvis:{sku_id}", result, 60)
        return result

    async def calculate_safety_stock(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID
    ) -> SafetyStockResult:
        return await self.safety_stock_calc.calculate(warehouse_id, sku_id)

    async def generate_forecast(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID
    ) -> Any:
        series = await self.forecast_engine.generate_forecast(warehouse_id, sku_id)
        if self.cache:
            await self.cache.invalidate_forecast(str(warehouse_id), str(sku_id))
        return series

    async def reconcile(self, warehouse_id: uuid.UUID) -> ReconciliationReport:
        return await self.reconciler.reconcile_warehouse(warehouse_id)

    async def adjust_inventory(
        self,
        warehouse_id: uuid.UUID,
        sku_id: uuid.UUID,
        quantity_delta: int,
        reason: str,
    ) -> None:
        balance = await self.balance_repo.get_balance(warehouse_id, sku_id)
        before = {"on_hand": balance.on_hand if balance else 0}
        if balance:
            balance.on_hand += quantity_delta
            balance.version += 1
            after = {"on_hand": balance.on_hand}
        else:
            from nexusops.models.inventory import InventoryBalance
            balance = InventoryBalance(
                warehouse_id=warehouse_id,
                sku_id=sku_id,
                on_hand=max(0, quantity_delta),
            )
            await self.balance_repo.add(balance)
            after = {"on_hand": balance.on_hand}

        await self.audit.record_inventory_change(
            warehouse_id, sku_id, "adjustment", before, after
        )
        if self.cache:
            await self.cache.invalidate_inventory(str(warehouse_id), str(sku_id))
