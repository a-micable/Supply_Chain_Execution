"""Batch processing for high-volume order and inventory operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.logging import get_logger
from nexusops.domain.fulfillment.planning import FulfillmentPlanner
from nexusops.domain.inventory.allocation import AllocationEngine, AllocationRequest
from nexusops.domain.inventory.reconciliation import InventoryReconciler
from nexusops.repositories.fulfillment import OrderRepository

logger = get_logger(__name__)


class BatchStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIALLY_FAILED = "partially_failed"
    FAILED = "failed"


@dataclass
class BatchItemResult:
    item_id: uuid.UUID
    success: bool
    error: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class BatchResult:
    batch_id: uuid.UUID
    batch_type: str
    status: BatchStatus
    total_items: int
    succeeded: int = 0
    failed: int = 0
    results: list[BatchItemResult] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def success_rate(self) -> float:
        if self.total_items == 0:
            return 0.0
        return self.succeeded / self.total_items


class OrderAllocationBatch:
    """Processes bulk order allocation in controlled batches."""

    def __init__(self, session: AsyncSession, batch_size: int = 25) -> None:
        self.session = session
        self.batch_size = batch_size
        self.order_repo = OrderRepository(session)
        self.allocation_engine = AllocationEngine(session)
        self.planner = FulfillmentPlanner(session)

    async def run(self) -> BatchResult:
        batch_id = uuid.uuid4()
        result = BatchResult(
            batch_id=batch_id,
            batch_type="order_allocation",
            status=BatchStatus.RUNNING,
            total_items=0,
            started_at=datetime.now(timezone.utc),
        )

        pending = await self.order_repo.list_pending_allocation(limit=self.batch_size)
        result.total_items = len(pending)

        for order in pending:
            try:
                plan_result = await self.planner.plan_fulfillment(order.id)
                result.results.append(BatchItemResult(
                    item_id=order.id,
                    success=True,
                    metadata={"status": plan_result.status, "is_partial": plan_result.is_partial},
                ))
                result.succeeded += 1
            except Exception as exc:
                result.results.append(BatchItemResult(
                    item_id=order.id,
                    success=False,
                    error=str(exc),
                ))
                result.failed += 1

        result.completed_at = datetime.now(timezone.utc)
        if result.failed == 0:
            result.status = BatchStatus.COMPLETED
        elif result.succeeded == 0:
            result.status = BatchStatus.FAILED
        else:
            result.status = BatchStatus.PARTIALLY_FAILED

        logger.info(
            "allocation_batch_completed",
            batch_id=str(batch_id),
            succeeded=result.succeeded,
            failed=result.failed,
        )
        return result


class ReconciliationBatch:
    """Runs reconciliation across all active warehouses."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.reconciler = InventoryReconciler(session)

    async def run(self, warehouse_ids: list[uuid.UUID]) -> BatchResult:
        batch_id = uuid.uuid4()
        result = BatchResult(
            batch_id=batch_id,
            batch_type="reconciliation",
            status=BatchStatus.RUNNING,
            total_items=len(warehouse_ids),
            started_at=datetime.now(timezone.utc),
        )

        for wh_id in warehouse_ids:
            try:
                report = await self.reconciler.reconcile_warehouse(wh_id)
                result.results.append(BatchItemResult(
                    item_id=wh_id,
                    success=report.is_balanced,
                    metadata={
                        "discrepancies": len(report.discrepancies),
                        "skus_checked": report.skus_checked,
                    },
                ))
                if report.is_balanced:
                    result.succeeded += 1
                else:
                    result.failed += 1
            except Exception as exc:
                result.results.append(BatchItemResult(
                    item_id=wh_id, success=False, error=str(exc),
                ))
                result.failed += 1

        result.completed_at = datetime.now(timezone.utc)
        result.status = (
            BatchStatus.COMPLETED if result.failed == 0
            else BatchStatus.PARTIALLY_FAILED if result.succeeded > 0
            else BatchStatus.FAILED
        )
        return result


class BatchProcessor:
    """Coordinates batch job execution."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_batch = OrderAllocationBatch(session)
        self.reconciliation_batch = ReconciliationBatch(session)

    async def process_pending_orders(self) -> BatchResult:
        return await self.order_batch.run()

    async def reconcile_warehouses(self, warehouse_ids: list[uuid.UUID]) -> BatchResult:
        return await self.reconciliation_batch.run(warehouse_ids)

    async def run_nightly_jobs(self, warehouse_ids: list[uuid.UUID]) -> dict:
        results = {}
        results["reconciliation"] = await self.reconcile_warehouses(warehouse_ids)
        results["allocation"] = await self.process_pending_orders()
        return results
