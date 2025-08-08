"""Inventory synchronization service for cross-warehouse consistency."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.cache.redis_cache import RedisCache
from nexusops.core.exceptions import ReconciliationError
from nexusops.core.logging import get_logger
from nexusops.core.types import EventType
from nexusops.domain.inventory.reconciliation import InventoryReconciler
from nexusops.events.bus import EventBus
from nexusops.events.schemas import DomainEventPayload
from nexusops.repositories.inventory import InventoryBalanceRepository
from nexusops.repositories.warehouse import WarehouseRepository

logger = get_logger(__name__)


@dataclass
class SyncResult:
    warehouse_id: uuid.UUID
    skus_synced: int
    discrepancies_found: int
    discrepancies_repaired: int
    cache_invalidated: bool
    errors: list[str] = field(default_factory=list)


@dataclass
class NetworkSyncReport:
    started_at: datetime
    completed_at: datetime | None = None
    warehouse_results: list[SyncResult] = field(default_factory=list)
    total_discrepancies: int = 0
    total_repaired: int = 0

    @property
    def is_healthy(self) -> bool:
        return self.total_discrepancies == 0 or self.total_repaired == self.total_discrepancies


class InventorySyncService:
    """Synchronizes inventory state across warehouses with cache invalidation."""

    def __init__(
        self,
        session: AsyncSession,
        cache: RedisCache | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.session = session
        self.cache = cache
        self.event_bus = event_bus
        self.reconciler = InventoryReconciler(session)
        self.balance_repo = InventoryBalanceRepository(session)
        self.warehouse_repo = WarehouseRepository(session)

    async def sync_warehouse(
        self, warehouse_id: uuid.UUID, auto_repair: bool = True
    ) -> SyncResult:
        report = await self.reconciler.reconcile_warehouse(warehouse_id)
        repaired = 0
        errors: list[str] = []

        if auto_repair:
            for disc in report.discrepancies:
                if disc.discrepancy_type == "reservation_mismatch":
                    try:
                        success = await self.reconciler.auto_repair_reservation_mismatch(
                            warehouse_id, disc.sku_id
                        )
                        if success:
                            repaired += 1
                    except ReconciliationError as exc:
                        errors.append(str(exc))

        cache_invalidated = False
        if self.cache:
            count = await self.cache.invalidate_pattern(f"inv:{warehouse_id}:*")
            await self.cache.invalidate_pattern("netvis:*")
            cache_invalidated = count >= 0

        if self.event_bus and report.discrepancies:
            await self.event_bus.publish(
                DomainEventPayload(
                    event_type=EventType.INVENTORY_ADJUSTED,
                    aggregate_type="warehouse",
                    aggregate_id=warehouse_id,
                    payload={
                        "sync_type": "reconciliation",
                        "discrepancies": len(report.discrepancies),
                        "repaired": repaired,
                    },
                    correlation_id=str(uuid.uuid4()),
                )
            )

        return SyncResult(
            warehouse_id=warehouse_id,
            skus_synced=report.skus_checked,
            discrepancies_found=len(report.discrepancies),
            discrepancies_repaired=repaired,
            cache_invalidated=cache_invalidated,
            errors=errors,
        )

    async def sync_network(self, auto_repair: bool = True) -> NetworkSyncReport:
        report = NetworkSyncReport(started_at=datetime.now(timezone.utc))
        warehouses = await self.warehouse_repo.list_active()

        for wh in warehouses:
            result = await self.sync_warehouse(wh.id, auto_repair)
            report.warehouse_results.append(result)
            report.total_discrepancies += result.discrepancies_found
            report.total_repaired += result.discrepancies_repaired

        report.completed_at = datetime.now(timezone.utc)
        logger.info(
            "network_sync_completed",
            warehouses=len(warehouses),
            discrepancies=report.total_discrepancies,
            repaired=report.total_repaired,
        )
        return report

    async def verify_sku_across_network(self, sku_id: uuid.UUID) -> dict[str, Any]:
        visibility = await self.balance_repo.get_network_visibility(sku_id)
        total_on_hand = sum(v[1] for v in visibility)
        total_available = sum(v[3] for v in visibility)
        return {
            "sku_id": str(sku_id),
            "warehouses": len(visibility),
            "total_on_hand": total_on_hand,
            "total_available": total_available,
            "by_warehouse": [
                {"warehouse_id": str(v[0]), "on_hand": v[1], "available": v[3]}
                for v in visibility
            ],
        }
