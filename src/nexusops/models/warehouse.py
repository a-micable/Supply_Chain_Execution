"""Warehouse operations ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexusops.db.base import Base, TimestampMixin, UUIDMixin, VersionMixin


class Warehouse(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "warehouses"

    warehouse_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    address: Mapped[dict] = mapped_column(JSONB, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    capacity_units: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(default=True)
    fulfillment_priority: Mapped[int] = mapped_column(Integer, default=5)
    operating_hours: Mapped[dict] = mapped_column(JSONB, default=dict)

    locations: Mapped[list[WarehouseLocation]] = relationship(back_populates="warehouse")


class WarehouseLocation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "warehouse_locations"
    __table_args__ = (
        Index("ix_location_warehouse_zone", "warehouse_id", "zone"),
    )

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    location_code: Mapped[str] = mapped_column(String(32), nullable=False)
    zone: Mapped[str] = mapped_column(String(16), nullable=False)
    aisle: Mapped[str | None] = mapped_column(String(8))
    rack: Mapped[str | None] = mapped_column(String(8))
    level: Mapped[str | None] = mapped_column(String(8))
    location_type: Mapped[str] = mapped_column(String(16), default="storage")
    capacity_units: Mapped[int | None] = mapped_column(Integer)
    is_pickable: Mapped[bool] = mapped_column(default=True)

    warehouse: Mapped[Warehouse] = relationship(back_populates="locations")


class WarehouseTask(Base, UUIDMixin, TimestampMixin, VersionMixin):
    __tablename__ = "warehouse_tasks"
    __table_args__ = (
        Index("ix_task_warehouse_status", "warehouse_id", "status"),
        Index("ix_task_type_status", "task_type", "status"),
    )

    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    assigned_to: Mapped[str | None] = mapped_column(String(64))
    source_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouse_locations.id")
    )
    target_location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouse_locations.id")
    )
    sku_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("skus.id"))
    quantity: Mapped[int | None] = mapped_column(Integer)
    reference_type: Mapped[str | None] = mapped_column(String(32))
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task_data: Mapped[dict] = mapped_column(JSONB, default=dict)


class WarehouseTransfer(Base, UUIDMixin, TimestampMixin, VersionMixin):
    __tablename__ = "warehouse_transfers"
    __table_args__ = (Index("ix_transfer_status", "status"),)

    transfer_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    source_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    destination_warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="pending")
    sku_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skus.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_shipped: Mapped[int] = mapped_column(Integer, default=0)
    quantity_received: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_ship_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
