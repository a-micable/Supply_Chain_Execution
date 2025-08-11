"""Scheduled job definitions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Awaitable

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.logging import get_logger
from nexusops.domain.inventory.reconciliation import InventoryReconciler
from nexusops.domain.procurement.replenishment import ReplenishmentPlanner
from nexusops.repositories.warehouse import WarehouseRepository

logger = get_logger(__name__)


@dataclass
class ScheduledJob:
    name: str
    cron_hour: int | None
    cron_minute: int | None
    handler: Callable[[AsyncSession], Awaitable[None]]
    last_run: datetime | None = None


async def nightly_reconciliation(session: AsyncSession) -> None:
    warehouse_repo = WarehouseRepository(session)
    reconciler = InventoryReconciler(session)
    warehouses = await warehouse_repo.list_active()
    for wh in warehouses:
        report = await reconciler.reconcile_warehouse(wh.id)
        if not report.is_balanced:
            logger.warning(
                "reconciliation_discrepancies",
                warehouse_id=str(wh.id),
                count=len(report.discrepancies),
            )


async def hourly_replenishment_check(session: AsyncSession) -> None:
    warehouse_repo = WarehouseRepository(session)
    planner = ReplenishmentPlanner(session)
    warehouses = await warehouse_repo.list_active()
    for wh in warehouses:
        plan = await planner.generate_plan(wh.id)
        if plan.lines:
            await planner.create_purchase_orders(plan)
            logger.info(
                "replenishment_pos_created",
                warehouse_id=str(wh.id),
                lines=len(plan.lines),
            )


JOBS: list[ScheduledJob] = [
    ScheduledJob("nightly_reconciliation", 2, 0, nightly_reconciliation),
    ScheduledJob("hourly_replenishment", None, 0, hourly_replenishment_check),
]
