"""Delivery scheduling and appointment management."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.logging import get_logger
from nexusops.repositories.transportation import ShipmentRepository
from nexusops.repositories.warehouse import WarehouseRepository

logger = get_logger(__name__)


class DeliveryWindow(StrEnum):
    MORNING = "08:00-12:00"
    AFTERNOON = "12:00-17:00"
    EVENING = "17:00-21:00"


@dataclass
class DeliverySlot:
    slot_id: uuid.UUID
    warehouse_id: uuid.UUID
    window: DeliveryWindow
    date: datetime
    capacity: int
    booked: int = 0

    @property
    def available(self) -> int:
        return max(0, self.capacity - self.booked)

    @property
    def is_full(self) -> bool:
        return self.booked >= self.capacity


@dataclass
class DeliverySchedule:
    shipment_id: uuid.UUID
    slot: DeliverySlot
    estimated_arrival: datetime
    estimated_departure: datetime
    dock_door: str | None = None
    notes: str = ""


@dataclass
class SchedulingResult:
    scheduled: list[DeliverySchedule] = field(default_factory=list)
    unscheduled: list[uuid.UUID] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


class DeliveryScheduler:
    """Schedules shipment deliveries into warehouse dock windows."""

    DEFAULT_DOCK_CAPACITY = 8
    SLOT_DURATION_HOURS = 4

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.shipment_repo = ShipmentRepository(session)
        self.warehouse_repo = WarehouseRepository(session)
        self._slots: dict[uuid.UUID, list[DeliverySlot]] = {}

    async def generate_slots(
        self, warehouse_id: uuid.UUID, start_date: datetime, days: int = 7
    ) -> list[DeliverySlot]:
        slots: list[DeliverySlot] = []
        for day_offset in range(days):
            date = start_date + timedelta(days=day_offset)
            if date.weekday() >= 5:
                continue
            for window in DeliveryWindow:
                slot = DeliverySlot(
                    slot_id=uuid.uuid4(),
                    warehouse_id=warehouse_id,
                    window=window,
                    date=date.replace(hour=8, minute=0, second=0, microsecond=0),
                    capacity=self.DEFAULT_DOCK_CAPACITY,
                )
                slots.append(slot)
        self._slots[warehouse_id] = slots
        return slots

    async def schedule_shipments(
        self, warehouse_id: uuid.UUID, shipment_ids: list[uuid.UUID]
    ) -> SchedulingResult:
        result = SchedulingResult()
        if warehouse_id not in self._slots:
            await self.generate_slots(warehouse_id, datetime.now(timezone.utc))

        available_slots = [s for s in self._slots[warehouse_id] if not s.is_full]

        for shipment_id in shipment_ids:
            shipment = await self.shipment_repo.get_by_id(shipment_id)
            if shipment is None:
                result.conflicts.append(f"Shipment {shipment_id} not found")
                result.unscheduled.append(shipment_id)
                continue

            slot = self._find_best_slot(available_slots, shipment.scheduled_delivery)
            if slot is None:
                result.unscheduled.append(shipment_id)
                result.conflicts.append(f"No slot available for shipment {shipment_id}")
                continue

            slot.booked += 1
            schedule = DeliverySchedule(
                shipment_id=shipment_id,
                slot=slot,
                estimated_arrival=slot.date,
                estimated_departure=slot.date + timedelta(hours=self.SLOT_DURATION_HOURS),
                dock_door=f"DOCK-{slot.booked:02d}",
            )
            result.scheduled.append(schedule)
            shipment.scheduled_delivery = schedule.estimated_arrival

        logger.info(
            "deliveries_scheduled",
            warehouse_id=str(warehouse_id),
            scheduled=len(result.scheduled),
            unscheduled=len(result.unscheduled),
        )
        return result

    def _find_best_slot(
        self, slots: list[DeliverySlot], preferred: datetime | None
    ) -> DeliverySlot | None:
        available = [s for s in slots if not s.is_full]
        if not available:
            return None
        if preferred is None:
            return available[0]
        return min(available, key=lambda s: abs((s.date - preferred).total_seconds()))

    async def reschedule(
        self, shipment_id: uuid.UUID, new_slot_id: uuid.UUID
    ) -> DeliverySchedule | None:
        for slots in self._slots.values():
            for slot in slots:
                if slot.slot_id == new_slot_id and not slot.is_full:
                    slot.booked += 1
                    return DeliverySchedule(
                        shipment_id=shipment_id,
                        slot=slot,
                        estimated_arrival=slot.date,
                        estimated_departure=slot.date + timedelta(hours=self.SLOT_DURATION_HOURS),
                    )
        return None
