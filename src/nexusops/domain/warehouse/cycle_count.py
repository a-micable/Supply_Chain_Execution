"""Cycle count and inventory adjustment workflows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.context import get_correlation_id, get_override_reason
from nexusops.core.logging import get_logger
from nexusops.core.types import EventType, WarehouseTaskType
from nexusops.events.bus import EventBus
from nexusops.events.schemas import DomainEventPayload
from nexusops.models.warehouse import WarehouseTask
from nexusops.repositories.inventory import InventoryBalanceRepository
from nexusops.repositories.warehouse import WarehouseLocationRepository, WarehouseTaskRepository
from nexusops.services.audit_service import AuditService

logger = get_logger(__name__)


class CycleCountStatus(StrEnum):
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    VARIANCE_REVIEW = "variance_review"
    ADJUSTED = "adjusted"
    CANCELLED = "cancelled"


@dataclass
class CycleCountLine:
    location_id: uuid.UUID
    sku_id: uuid.UUID
    expected_quantity: int
    counted_quantity: int | None = None

    @property
    def variance(self) -> int | None:
        if self.counted_quantity is None:
            return None
        return self.counted_quantity - self.expected_quantity

    @property
    def has_variance(self) -> bool:
        v = self.variance
        return v is not None and v != 0


@dataclass
class CycleCountSession:
    session_id: uuid.UUID
    warehouse_id: uuid.UUID
    status: CycleCountStatus
    lines: list[CycleCountLine] = field(default_factory=list)
    task_ids: list[uuid.UUID] = field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def total_variance(self) -> int:
        return sum(l.variance or 0 for l in self.lines if l.variance is not None)

    @property
    def lines_with_variance(self) -> list[CycleCountLine]:
        return [l for l in self.lines if l.has_variance]


class CycleCountService:
    """Manages cycle count operations and variance adjustments."""

    VARIANCE_THRESHOLD_AUTO_ADJUST = 5
    VARIANCE_THRESHOLD_REVIEW = 50

    def __init__(
        self,
        session: AsyncSession,
        event_bus: EventBus | None = None,
    ) -> None:
        self.session = session
        self.event_bus = event_bus
        self.balance_repo = InventoryBalanceRepository(session)
        self.location_repo = WarehouseLocationRepository(session)
        self.task_repo = WarehouseTaskRepository(session)
        self.audit = AuditService(session)

    async def schedule_count(
        self,
        warehouse_id: uuid.UUID,
        location_ids: list[uuid.UUID],
    ) -> CycleCountSession:
        cc_session = CycleCountSession(
            session_id=uuid.uuid4(),
            warehouse_id=warehouse_id,
            status=CycleCountStatus.SCHEDULED,
        )

        for loc_id in location_ids:
            location = await self.location_repo.get_by_id(loc_id)
            if location is None:
                continue

            balances = await self.balance_repo.list_by_warehouse(warehouse_id)
            loc_balances = [b for b in balances if b.location_id == loc_id]

            for balance in loc_balances:
                cc_session.lines.append(
                    CycleCountLine(
                        location_id=loc_id,
                        sku_id=balance.sku_id,
                        expected_quantity=balance.on_hand,
                    )
                )

                task = WarehouseTask(
                    warehouse_id=warehouse_id,
                    task_type=WarehouseTaskType.CYCLE_COUNT,
                    status="pending",
                    source_location_id=loc_id,
                    sku_id=balance.sku_id,
                    quantity=balance.on_hand,
                    reference_type="cycle_count",
                    reference_id=cc_session.session_id,
                    task_data={"expected": balance.on_hand},
                )
                created = await self.task_repo.add(task)
                cc_session.task_ids.append(created.id)

        logger.info(
            "cycle_count_scheduled",
            session_id=str(cc_session.session_id),
            lines=len(cc_session.lines),
        )
        return cc_session

    async def record_count(
        self,
        cc_session: CycleCountSession,
        location_id: uuid.UUID,
        sku_id: uuid.UUID,
        counted_quantity: int,
    ) -> CycleCountLine:
        line = next(
            (l for l in cc_session.lines if l.location_id == location_id and l.sku_id == sku_id),
            None,
        )
        if line is None:
            raise ValueError(f"No cycle count line for location {location_id}, sku {sku_id}")

        line.counted_quantity = counted_quantity
        cc_session.status = CycleCountStatus.IN_PROGRESS
        return line

    async def complete_session(
        self, cc_session: CycleCountSession, auto_adjust: bool = True
    ) -> CycleCountSession:
        uncounted = [l for l in cc_session.lines if l.counted_quantity is None]
        if uncounted:
            raise ValueError(f"{len(uncounted)} lines not yet counted")

        cc_session.completed_at = datetime.now(timezone.utc)
        variance_lines = cc_session.lines_with_variance

        if not variance_lines:
            cc_session.status = CycleCountStatus.COMPLETED
            return cc_session

        max_variance = max(abs(l.variance or 0) for l in variance_lines)
        if max_variance > self.VARIANCE_THRESHOLD_REVIEW:
            cc_session.status = CycleCountStatus.VARIANCE_REVIEW
            logger.warning(
                "cycle_count_variance_review_required",
                session_id=str(cc_session.session_id),
                max_variance=max_variance,
            )
            return cc_session

        if auto_adjust:
            await self.apply_adjustments(cc_session)
            cc_session.status = CycleCountStatus.ADJUSTED
        else:
            cc_session.status = CycleCountStatus.VARIANCE_REVIEW

        return cc_session

    async def apply_adjustments(self, cc_session: CycleCountSession) -> int:
        adjusted = 0
        override = get_override_reason()

        for line in cc_session.lines_with_variance:
            balance = await self.balance_repo.get_balance(
                cc_session.warehouse_id, line.sku_id, line.location_id
            )
            if balance is None:
                continue

            before = {"on_hand": balance.on_hand}
            balance.on_hand = line.counted_quantity or balance.on_hand
            balance.version += 1
            after = {"on_hand": balance.on_hand}

            await self.audit.record_inventory_change(
                cc_session.warehouse_id,
                line.sku_id,
                "cycle_count_adjustment",
                before,
                after,
            )

            if self.event_bus:
                await self.event_bus.publish(
                    DomainEventPayload(
                        event_type=EventType.INVENTORY_ADJUSTED,
                        aggregate_type="inventory",
                        aggregate_id=line.sku_id,
                        payload={
                            "warehouse_id": str(cc_session.warehouse_id),
                            "sku_id": str(line.sku_id),
                            "quantity_delta": line.variance,
                            "reason": "cycle_count",
                            "manual_override": override is not None,
                        },
                        correlation_id=str(get_correlation_id()),
                    )
                )
            adjusted += 1

        logger.info(
            "cycle_count_adjustments_applied",
            session_id=str(cc_session.session_id),
            adjusted=adjusted,
        )
        return adjusted

    async def generate_abc_count_schedule(
        self, warehouse_id: uuid.UUID, class_a_pct: float = 0.2
    ) -> list[uuid.UUID]:
        """Select locations for cycle counting based on ABC velocity classification."""
        locations = await self.location_repo.list_pickable(warehouse_id)
        if not locations:
            return []

        count_a = max(1, int(len(locations) * class_a_pct))
        zone_a = [l for l in locations if l.zone == "A"]
        if zone_a:
            return [l.id for l in zone_a[:count_a]]
        return [l.id for l in locations[:count_a]]
