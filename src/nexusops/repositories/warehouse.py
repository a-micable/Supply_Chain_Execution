"""Warehouse operations repository layer."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from nexusops.models.warehouse import (
    Warehouse,
    WarehouseLocation,
    WarehouseTask,
    WarehouseTransfer,
)
from nexusops.repositories.base import BaseRepository


class WarehouseRepository(BaseRepository[Warehouse]):
    model = Warehouse

    async def get_by_code(self, warehouse_code: str) -> Warehouse | None:
        stmt = select(Warehouse).where(Warehouse.warehouse_code == warehouse_code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Warehouse]:
        stmt = (
            select(Warehouse)
            .where(Warehouse.is_active.is_(True))
            .order_by(Warehouse.fulfillment_priority.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class WarehouseLocationRepository(BaseRepository[WarehouseLocation]):
    model = WarehouseLocation

    async def get_by_code(
        self, warehouse_id: uuid.UUID, location_code: str
    ) -> WarehouseLocation | None:
        stmt = select(WarehouseLocation).where(
            WarehouseLocation.warehouse_id == warehouse_id,
            WarehouseLocation.location_code == location_code,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_pickable(
        self, warehouse_id: uuid.UUID, zone: str | None = None
    ) -> list[WarehouseLocation]:
        conditions = [
            WarehouseLocation.warehouse_id == warehouse_id,
            WarehouseLocation.is_pickable.is_(True),
        ]
        if zone:
            conditions.append(WarehouseLocation.zone == zone)
        stmt = select(WarehouseLocation).where(*conditions)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class WarehouseTaskRepository(BaseRepository[WarehouseTask]):
    model = WarehouseTask

    async def list_pending(
        self, warehouse_id: uuid.UUID, task_type: str | None = None, limit: int = 50
    ) -> list[WarehouseTask]:
        conditions = [
            WarehouseTask.warehouse_id == warehouse_id,
            WarehouseTask.status == "pending",
        ]
        if task_type:
            conditions.append(WarehouseTask.task_type == task_type)
        stmt = (
            select(WarehouseTask)
            .where(*conditions)
            .order_by(WarehouseTask.priority.asc(), WarehouseTask.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_reference(
        self, reference_type: str, reference_id: uuid.UUID
    ) -> list[WarehouseTask]:
        stmt = select(WarehouseTask).where(
            WarehouseTask.reference_type == reference_type,
            WarehouseTask.reference_id == reference_id,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class WarehouseTransferRepository(BaseRepository[WarehouseTransfer]):
    model = WarehouseTransfer

    async def get_by_number(self, transfer_number: str) -> WarehouseTransfer | None:
        stmt = select(WarehouseTransfer).where(
            WarehouseTransfer.transfer_number == transfer_number
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_in_transit(self) -> list[WarehouseTransfer]:
        stmt = select(WarehouseTransfer).where(
            WarehouseTransfer.status.in_(("shipped", "in_transit"))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
