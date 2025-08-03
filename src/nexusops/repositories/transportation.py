"""Transportation management repository layer."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload

from nexusops.models.transportation import Carrier, RoutePlan, Shipment, ShipmentStop
from nexusops.repositories.base import BaseRepository


class CarrierRepository(BaseRepository[Carrier]):
    model = Carrier

    async def get_by_code(self, carrier_code: str) -> Carrier | None:
        stmt = select(Carrier).where(Carrier.carrier_code == carrier_code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Carrier]:
        stmt = select(Carrier).where(Carrier.is_active.is_(True))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class ShipmentRepository(BaseRepository[Shipment]):
    model = Shipment

    async def get_with_stops(self, shipment_id: uuid.UUID) -> Shipment | None:
        stmt = (
            select(Shipment)
            .options(selectinload(Shipment.stops))
            .where(Shipment.id == shipment_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_number(self, shipment_number: str) -> Shipment | None:
        stmt = select(Shipment).where(Shipment.shipment_number == shipment_number)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_status(self, status: str, limit: int = 100) -> list[Shipment]:
        stmt = (
            select(Shipment)
            .where(Shipment.status == status)
            .order_by(Shipment.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_consolidation_candidates(
        self,
        warehouse_id: uuid.UUID,
        window_start: datetime,
        window_end: datetime,
    ) -> list[Shipment]:
        stmt = select(Shipment).where(
            Shipment.warehouse_id == warehouse_id,
            Shipment.status == "planned",
            Shipment.consolidation_group_id.is_(None),
            Shipment.scheduled_pickup >= window_start,
            Shipment.scheduled_pickup <= window_end,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_consolidation_group(
        self, group_id: uuid.UUID
    ) -> list[Shipment]:
        stmt = select(Shipment).where(Shipment.consolidation_group_id == group_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class RoutePlanRepository(BaseRepository[RoutePlan]):
    model = RoutePlan

    async def get_selected_for_shipment(self, shipment_id: uuid.UUID) -> RoutePlan | None:
        stmt = select(RoutePlan).where(
            RoutePlan.shipment_id == shipment_id,
            RoutePlan.is_selected.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_alternatives(self, shipment_id: uuid.UUID) -> list[RoutePlan]:
        stmt = (
            select(RoutePlan)
            .where(RoutePlan.shipment_id == shipment_id)
            .order_by(RoutePlan.estimated_cost.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
