"""Inventory network ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexusops.db.base import Base, TimestampMixin, UUIDMixin, VersionMixin


class Sku(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "skus"

    sku_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    uom: Mapped[str] = mapped_column(String(16), default="EA")
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    is_hazmat: Mapped[bool] = mapped_column(default=False)
    is_active: Mapped[bool] = mapped_column(default=True)
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7)

    balances: Mapped[list[InventoryBalance]] = relationship(back_populates="sku")
    forecasts: Mapped[list[InventoryForecast]] = relationship(back_populates="sku")


class InventoryBalance(Base, UUIDMixin, TimestampMixin, VersionMixin):
    __tablename__ = "inventory_balances"
    __table_args__ = (
        UniqueConstraint("warehouse_id", "sku_id", "location_id", name="uq_balance_location"),
        Index("ix_balance_warehouse_sku", "warehouse_id", "sku_id"),
    )

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id"), nullable=False
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouse_locations.id")
    )
    on_hand: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reserved: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    allocated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    in_transit: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    damaged: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quarantine: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    sku: Mapped[Sku] = relationship(back_populates="balances")

    @property
    def available(self) -> int:
        return max(0, self.on_hand - self.reserved - self.allocated - self.damaged - self.quarantine)


class InventoryReservation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "inventory_reservations"
    __table_args__ = (Index("ix_reservation_order", "order_id"),)

    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    order_line_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(64))


class SafetyStockPolicy(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "safety_stock_policies"
    __table_args__ = (UniqueConstraint("warehouse_id", "sku_id", name="uq_safety_stock"),)

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id"), nullable=False
    )
    service_level: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.95"))
    safety_stock_qty: Mapped[int] = mapped_column(Integer, default=0)
    reorder_point: Mapped[int] = mapped_column(Integer, default=0)
    max_stock: Mapped[int | None] = mapped_column(Integer)
    demand_std_dev: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7)


class InventoryForecast(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "inventory_forecasts"
    __table_args__ = (
        Index("ix_forecast_warehouse_sku_date", "warehouse_id", "sku_id", "forecast_date"),
    )

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id"), nullable=False
    )
    forecast_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    predicted_demand: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence_lower: Mapped[int | None] = mapped_column(Integer)
    confidence_upper: Mapped[int | None] = mapped_column(Integer)
    model_version: Mapped[str] = mapped_column(String(32), default="v1")
    drift_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))

    sku: Mapped[Sku] = relationship(back_populates="forecasts")
