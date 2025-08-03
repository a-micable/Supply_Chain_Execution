"""Procurement system repository layer."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from nexusops.models.procurement import PurchaseOrder, PurchaseOrderLine, Supplier
from nexusops.repositories.base import BaseRepository


class SupplierRepository(BaseRepository[Supplier]):
    model = Supplier

    async def get_by_code(self, supplier_code: str) -> Supplier | None:
        stmt = select(Supplier).where(Supplier.supplier_code == supplier_code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_preferred(self) -> list[Supplier]:
        stmt = (
            select(Supplier)
            .where(Supplier.is_preferred.is_(True), Supplier.is_active.is_(True))
            .order_by(Supplier.on_time_delivery_rate.desc().nullslast())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_performance_threshold(
        self, min_on_time_rate: float
    ) -> list[Supplier]:
        stmt = select(Supplier).where(
            Supplier.is_active.is_(True),
            Supplier.on_time_delivery_rate >= min_on_time_rate,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class PurchaseOrderRepository(BaseRepository[PurchaseOrder]):
    model = PurchaseOrder

    async def get_with_lines(self, po_id: uuid.UUID) -> PurchaseOrder | None:
        stmt = (
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.lines))
            .where(PurchaseOrder.id == po_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_number(self, po_number: str) -> PurchaseOrder | None:
        stmt = select(PurchaseOrder).where(PurchaseOrder.po_number == po_number)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_open_for_warehouse(self, warehouse_id: uuid.UUID) -> list[PurchaseOrder]:
        open_statuses = ("submitted", "acknowledged", "partially_received")
        stmt = (
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.lines))
            .where(
                PurchaseOrder.warehouse_id == warehouse_id,
                PurchaseOrder.status.in_(open_statuses),
            )
            .order_by(PurchaseOrder.expected_delivery.asc().nullslast())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_pending_receipt(self, limit: int = 50) -> list[PurchaseOrder]:
        stmt = (
            select(PurchaseOrder)
            .options(selectinload(PurchaseOrder.lines))
            .where(PurchaseOrder.status.in_(("acknowledged", "partially_received")))
            .order_by(PurchaseOrder.expected_delivery.asc().nullslast())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
