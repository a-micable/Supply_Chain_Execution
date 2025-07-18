"""Warehouse picking and packing operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.exceptions import InsufficientInventoryError
from nexusops.core.logging import get_logger
from nexusops.core.types import WarehouseTaskStatus, WarehouseTaskType
from nexusops.models.warehouse import WarehouseTask
from nexusops.repositories.inventory import InventoryBalanceRepository
from nexusops.repositories.warehouse import WarehouseLocationRepository, WarehouseTaskRepository

logger = get_logger(__name__)


@dataclass
class PickLine:
    order_line_id: uuid.UUID
    sku_id: uuid.UUID
    quantity: int
    location_id: uuid.UUID | None = None


@dataclass
class PickWave:
    wave_id: uuid.UUID
    warehouse_id: uuid.UUID
    order_id: uuid.UUID
    lines: list[PickLine] = field(default_factory=list)
    tasks: list[uuid.UUID] = field(default_factory=list)
    status: str = "pending"


@dataclass
class PackResult:
    order_id: uuid.UUID
    packages: int
    total_weight_kg: float
    task_ids: list[uuid.UUID]


class PickPackService:
    """Manages pick waves and pack station operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.task_repo = WarehouseTaskRepository(session)
        self.location_repo = WarehouseLocationRepository(session)
        self.balance_repo = InventoryBalanceRepository(session)

    async def create_pick_wave(
        self, warehouse_id: uuid.UUID, order_id: uuid.UUID, lines: list[PickLine]
    ) -> PickWave:
        wave = PickWave(
            wave_id=uuid.uuid4(),
            warehouse_id=warehouse_id,
            order_id=order_id,
            lines=lines,
        )

        for line in lines:
            location = await self._find_pick_location(warehouse_id, line.sku_id, line.quantity)
            if location is None:
                raise InsufficientInventoryError(
                    line.sku_id, line.quantity, 0, warehouse_id
                )

            task = WarehouseTask(
                warehouse_id=warehouse_id,
                task_type=WarehouseTaskType.PICK,
                status=WarehouseTaskStatus.PENDING,
                priority=3,
                source_location_id=location.id,
                sku_id=line.sku_id,
                quantity=line.quantity,
                reference_type="order",
                reference_id=order_id,
                task_data={
                    "wave_id": str(wave.wave_id),
                    "order_line_id": str(line.order_line_id),
                },
            )
            created = await self.task_repo.add(task)
            wave.tasks.append(created.id)
            line.location_id = location.id

        logger.info(
            "pick_wave_created",
            wave_id=str(wave.wave_id),
            task_count=len(wave.tasks),
        )
        return wave

    async def complete_pick(self, task_id: uuid.UUID, operator_id: str) -> None:
        task = await self.task_repo.get_by_id_or_raise(task_id)
        if task.task_type != WarehouseTaskType.PICK:
            raise ValueError(f"Task {task_id} is not a pick task")

        task.status = WarehouseTaskStatus.COMPLETED
        task.assigned_to = operator_id
        task.completed_at = datetime.now(timezone.utc)

        if task.source_location_id and task.sku_id and task.quantity:
            balance = await self.balance_repo.get_balance(
                task.warehouse_id, task.sku_id, task.source_location_id
            )
            if balance:
                balance.on_hand -= task.quantity
                balance.allocated = max(0, balance.allocated - task.quantity)
                balance.version += 1

    async def create_pack_task(
        self, warehouse_id: uuid.UUID, order_id: uuid.UUID, package_count: int = 1
    ) -> PackResult:
        task_ids: list[uuid.UUID] = []
        for i in range(package_count):
            task = WarehouseTask(
                warehouse_id=warehouse_id,
                task_type=WarehouseTaskType.PACK,
                status=WarehouseTaskStatus.PENDING,
                reference_type="order",
                reference_id=order_id,
                task_data={"package_index": i + 1, "total_packages": package_count},
            )
            created = await self.task_repo.add(task)
            task_ids.append(created.id)

        return PackResult(
            order_id=order_id,
            packages=package_count,
            total_weight_kg=0.0,
            task_ids=task_ids,
        )

    async def _find_pick_location(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID, quantity: int
    ):
        locations = await self.location_repo.list_pickable(warehouse_id)
        for loc in locations:
            balance = await self.balance_repo.get_balance(warehouse_id, sku_id, loc.id)
            if balance and balance.available >= quantity:
                return loc
        balance = await self.balance_repo.get_balance(warehouse_id, sku_id)
        if balance and balance.available >= quantity:
            return None
        return None
