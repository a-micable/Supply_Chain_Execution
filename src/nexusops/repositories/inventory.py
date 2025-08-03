"""Inventory network repository layer."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.models.inventory import (
    InventoryBalance,
    InventoryForecast,
    InventoryReservation,
    SafetyStockPolicy,
    Sku,
)
from nexusops.repositories.base import BaseRepository


class SkuRepository(BaseRepository[Sku]):
    model = Sku

    async def get_by_code(self, sku_code: str) -> Sku | None:
        stmt = select(Sku).where(Sku.sku_code == sku_code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class InventoryBalanceRepository(BaseRepository[InventoryBalance]):
    model = InventoryBalance

    async def get_balance(
        self,
        warehouse_id: uuid.UUID,
        sku_id: uuid.UUID,
        location_id: uuid.UUID | None = None,
    ) -> InventoryBalance | None:
        conditions = [
            InventoryBalance.warehouse_id == warehouse_id,
            InventoryBalance.sku_id == sku_id,
        ]
        if location_id is not None:
            conditions.append(InventoryBalance.location_id == location_id)
        else:
            conditions.append(InventoryBalance.location_id.is_(None))

        stmt = select(InventoryBalance).where(and_(*conditions))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_network_visibility(
        self, sku_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, int, int, int]]:
        """Return (warehouse_id, on_hand, reserved, available) across network."""
        stmt = (
            select(
                InventoryBalance.warehouse_id,
                func.sum(InventoryBalance.on_hand).label("on_hand"),
                func.sum(InventoryBalance.reserved).label("reserved"),
                func.sum(
                    InventoryBalance.on_hand
                    - InventoryBalance.reserved
                    - InventoryBalance.allocated
                    - InventoryBalance.damaged
                    - InventoryBalance.quarantine
                ).label("available"),
            )
            .where(InventoryBalance.sku_id == sku_id)
            .group_by(InventoryBalance.warehouse_id)
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1] or 0, row[2] or 0, max(0, row[3] or 0)) for row in result.all()]

    async def get_aggregated_available(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID
    ) -> int:
        stmt = select(
            func.coalesce(
                func.sum(
                    InventoryBalance.on_hand
                    - InventoryBalance.reserved
                    - InventoryBalance.allocated
                    - InventoryBalance.damaged
                    - InventoryBalance.quarantine
                ),
                0,
            )
        ).where(
            InventoryBalance.warehouse_id == warehouse_id,
            InventoryBalance.sku_id == sku_id,
        )
        result = await self.session.execute(stmt)
        return max(0, result.scalar_one())

    async def list_by_warehouse(self, warehouse_id: uuid.UUID) -> list[InventoryBalance]:
        stmt = select(InventoryBalance).where(InventoryBalance.warehouse_id == warehouse_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class InventoryReservationRepository(BaseRepository[InventoryReservation]):
    model = InventoryReservation

    async def get_active_for_order(self, order_id: uuid.UUID) -> list[InventoryReservation]:
        stmt = select(InventoryReservation).where(
            InventoryReservation.order_id == order_id,
            InventoryReservation.status == "active",
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_expired(self, as_of: datetime | None = None) -> list[InventoryReservation]:
        cutoff = as_of or datetime.now(timezone.utc)
        stmt = select(InventoryReservation).where(
            InventoryReservation.status == "active",
            InventoryReservation.expires_at < cutoff,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def sum_reserved_quantity(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID
    ) -> int:
        stmt = select(func.coalesce(func.sum(InventoryReservation.quantity), 0)).where(
            InventoryReservation.warehouse_id == warehouse_id,
            InventoryReservation.sku_id == sku_id,
            InventoryReservation.status == "active",
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()


class SafetyStockPolicyRepository(BaseRepository[SafetyStockPolicy]):
    model = SafetyStockPolicy

    async def get_policy(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID
    ) -> SafetyStockPolicy | None:
        stmt = select(SafetyStockPolicy).where(
            SafetyStockPolicy.warehouse_id == warehouse_id,
            SafetyStockPolicy.sku_id == sku_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_below_reorder_point(self) -> list[tuple[SafetyStockPolicy, int]]:
        """Return policies where current available is below reorder point."""
        stmt = (
            select(
                SafetyStockPolicy,
                func.coalesce(
                    func.sum(
                        InventoryBalance.on_hand
                        - InventoryBalance.reserved
                        - InventoryBalance.allocated
                    ),
                    0,
                ).label("available"),
            )
            .outerjoin(
                InventoryBalance,
                and_(
                    InventoryBalance.warehouse_id == SafetyStockPolicy.warehouse_id,
                    InventoryBalance.sku_id == SafetyStockPolicy.sku_id,
                ),
            )
            .group_by(SafetyStockPolicy.id)
            .having(
                func.coalesce(
                    func.sum(
                        InventoryBalance.on_hand
                        - InventoryBalance.reserved
                        - InventoryBalance.allocated
                    ),
                    0,
                )
                < SafetyStockPolicy.reorder_point
            )
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]


class InventoryForecastRepository(BaseRepository[InventoryForecast]):
    model = InventoryForecast

    async def get_forecast_series(
        self,
        warehouse_id: uuid.UUID,
        sku_id: uuid.UUID,
        start_date: datetime,
        end_date: datetime,
    ) -> list[InventoryForecast]:
        stmt = (
            select(InventoryForecast)
            .where(
                InventoryForecast.warehouse_id == warehouse_id,
                InventoryForecast.sku_id == sku_id,
                InventoryForecast.forecast_date >= start_date,
                InventoryForecast.forecast_date <= end_date,
            )
            .order_by(InventoryForecast.forecast_date)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID
    ) -> InventoryForecast | None:
        stmt = (
            select(InventoryForecast)
            .where(
                InventoryForecast.warehouse_id == warehouse_id,
                InventoryForecast.sku_id == sku_id,
            )
            .order_by(InventoryForecast.forecast_date.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
