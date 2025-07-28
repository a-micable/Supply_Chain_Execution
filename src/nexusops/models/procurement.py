"""Procurement system ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexusops.db.base import Base, TimestampMixin, UUIDMixin, VersionMixin


class Supplier(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "suppliers"

    supplier_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(256))
    lead_time_days: Mapped[int] = mapped_column(Integer, default=14)
    on_time_delivery_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    quality_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30)
    is_preferred: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    performance_metrics: Mapped[dict] = mapped_column(JSONB, default=dict)

    purchase_orders: Mapped[list[PurchaseOrder]] = relationship(back_populates="supplier")


class PurchaseOrder(Base, UUIDMixin, TimestampMixin, VersionMixin):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        Index("ix_po_status", "status"),
        Index("ix_po_supplier", "supplier_id"),
    )

    po_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("suppliers.id"), nullable=False
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    order_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_delivery: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 4), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    replenishment_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    notes: Mapped[str | None] = mapped_column(String(1024))

    supplier: Mapped[Supplier] = relationship(back_populates="purchase_orders")
    lines: Mapped[list[PurchaseOrderLine]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan"
    )


class PurchaseOrderLine(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "purchase_order_lines"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_orders.id"), nullable=False
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id"), nullable=False
    )
    quantity_ordered: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    line_status: Mapped[str] = mapped_column(String(32), default="open")

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
