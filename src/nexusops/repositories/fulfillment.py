"""Fulfillment engine repository layer."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from nexusops.models.fulfillment import FulfillmentPlan, Order, OrderLine
from nexusops.repositories.base import BaseRepository


class OrderRepository(BaseRepository[Order]):
    model = Order

    async def get_with_lines(self, order_id: uuid.UUID) -> Order | None:
        stmt = (
            select(Order)
            .options(selectinload(Order.lines))
            .where(Order.id == order_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_external_id(self, external_order_id: str) -> Order | None:
        stmt = select(Order).where(Order.external_order_id == external_order_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_status(self, status: str, limit: int = 100) -> list[Order]:
        stmt = (
            select(Order)
            .where(Order.status == status)
            .order_by(Order.priority.asc(), Order.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_pending_allocation(self, limit: int = 50) -> list[Order]:
        statuses = ("received", "validating", "allocating")
        stmt = (
            select(Order)
            .options(selectinload(Order.lines))
            .where(Order.status.in_(statuses))
            .order_by(Order.priority.asc(), Order.created_at.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class OrderLineRepository(BaseRepository[OrderLine]):
    model = OrderLine

    async def get_unfulfilled_lines(self, order_id: uuid.UUID) -> list[OrderLine]:
        stmt = select(OrderLine).where(
            OrderLine.order_id == order_id,
            OrderLine.quantity_ordered > OrderLine.quantity_allocated,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class FulfillmentPlanRepository(BaseRepository[FulfillmentPlan]):
    model = FulfillmentPlan

    async def get_plans_for_order(self, order_id: uuid.UUID) -> list[FulfillmentPlan]:
        stmt = select(FulfillmentPlan).where(FulfillmentPlan.order_id == order_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_plan(
        self, order_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> FulfillmentPlan | None:
        stmt = select(FulfillmentPlan).where(
            FulfillmentPlan.order_id == order_id,
            FulfillmentPlan.warehouse_id == warehouse_id,
            FulfillmentPlan.status.in_(("planned", "executing")),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
