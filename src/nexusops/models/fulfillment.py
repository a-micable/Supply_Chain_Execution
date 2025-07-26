"""Fulfillment engine ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexusops.db.base import Base, TimestampMixin, UUIDMixin, VersionMixin


class Order(Base, UUIDMixin, TimestampMixin, VersionMixin):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_order_status_priority", "status", "priority"),)

    external_order_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    customer_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="received", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    ship_to_address: Mapped[dict] = mapped_column(JSONB, nullable=False)
    requested_ship_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    routing_strategy: Mapped[str] = mapped_column(String(32), default="cost_optimized")
    allow_partial_fulfillment: Mapped[bool] = mapped_column(default=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64))

    lines: Mapped[list[OrderLine]] = relationship(back_populates="order", cascade="all, delete-orphan")
    fulfillment_plans: Mapped[list[FulfillmentPlan]] = relationship(back_populates="order")


class OrderLine(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "order_lines"
    __table_args__ = (Index("ix_order_line_order", "order_id"),)

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id"), nullable=False
    )
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_allocated: Mapped[int] = mapped_column(Integer, default=0)
    quantity_shipped: Mapped[int] = mapped_column(Integer, default=0)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    backorder_quantity: Mapped[int] = mapped_column(Integer, default=0)

    order: Mapped[Order] = relationship(back_populates="lines")


class FulfillmentPlan(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "fulfillment_plans"
    __table_args__ = (Index("ix_fulfillment_plan_order", "order_id"),)

    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="planned")
    planned_ship_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    routing_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    plan_details: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_partial: Mapped[bool] = mapped_column(default=False)

    order: Mapped[Order] = relationship(back_populates="fulfillment_plans")
