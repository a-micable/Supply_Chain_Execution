"""Vendor performance tracking and scoring."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.logging import get_logger
from nexusops.repositories.procurement import PurchaseOrderRepository, SupplierRepository

logger = get_logger(__name__)


@dataclass
class VendorMetrics:
    supplier_id: uuid.UUID
    supplier_code: str
    on_time_delivery_rate: float
    quality_score: float
    avg_lead_time_days: float
    total_pos: int
    total_value: Decimal
    composite_score: float
    trend: str


@dataclass
class PerformanceReport:
    suppliers: list[VendorMetrics]
    period_start: datetime
    period_end: datetime
    top_performers: list[uuid.UUID]
    underperformers: list[uuid.UUID]


class VendorPerformanceTracker:
    """Tracks and scores supplier performance over rolling periods."""

    ON_TIME_THRESHOLD = 0.90
    QUALITY_THRESHOLD = 0.85

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.supplier_repo = SupplierRepository(session)
        self.po_repo = PurchaseOrderRepository(session)

    async def generate_report(
        self, period_days: int = 90
    ) -> PerformanceReport:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=period_days)
        suppliers = await self.supplier_repo.list_by_performance_threshold(0.0)
        metrics: list[VendorMetrics] = []

        for supplier in suppliers:
            m = await self._compute_metrics(supplier, start, end)
            metrics.append(m)

        metrics.sort(key=lambda m: m.composite_score, reverse=True)
        top = [m.supplier_id for m in metrics[:5]]
        under = [
            m.supplier_id
            for m in metrics
            if m.on_time_delivery_rate < self.ON_TIME_THRESHOLD
            or m.quality_score < self.QUALITY_THRESHOLD
        ]

        return PerformanceReport(
            suppliers=metrics,
            period_start=start,
            period_end=end,
            top_performers=top,
            underperformers=under,
        )

    async def _compute_metrics(self, supplier, start: datetime, end: datetime) -> VendorMetrics:
        on_time = float(supplier.on_time_delivery_rate or 0.80)
        quality = float(supplier.quality_score or 0.80)
        lead_time = float(supplier.lead_time_days)

        composite = on_time * 0.5 + quality * 0.3 + (1.0 / max(lead_time, 1)) * 0.2
        stored_metrics = supplier.performance_metrics or {}
        prev_score = stored_metrics.get("composite_score", composite)
        trend = "stable"
        if composite > prev_score + 0.05:
            trend = "improving"
        elif composite < prev_score - 0.05:
            trend = "declining"

        supplier.performance_metrics = {
            **stored_metrics,
            "composite_score": composite,
            "last_evaluated": end.isoformat(),
            "trend": trend,
        }

        return VendorMetrics(
            supplier_id=supplier.id,
            supplier_code=supplier.supplier_code,
            on_time_delivery_rate=on_time,
            quality_score=quality,
            avg_lead_time_days=lead_time,
            total_pos=stored_metrics.get("total_pos", 0),
            total_value=Decimal(str(stored_metrics.get("total_value", 0))),
            composite_score=composite,
            trend=trend,
        )

    async def update_supplier_scores(self) -> int:
        report = await self.generate_report()
        updated = 0
        for m in report.suppliers:
            supplier = await self.supplier_repo.get_by_id(m.supplier_id)
            if supplier:
                supplier.on_time_delivery_rate = Decimal(str(round(m.on_time_delivery_rate, 4)))
                supplier.quality_score = Decimal(str(round(m.quality_score, 4)))
                updated += 1
        return updated
