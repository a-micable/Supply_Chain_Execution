"""Transportation management ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nexusops.db.base import Base, TimestampMixin, UUIDMixin, VersionMixin


class Carrier(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "carriers"

    carrier_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    service_levels: Mapped[list] = mapped_column(JSONB, default=list)
    on_time_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    cost_per_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    max_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    is_active: Mapped[bool] = mapped_column(default=True)


class Shipment(Base, UUIDMixin, TimestampMixin, VersionMixin):
    __tablename__ = "shipments"
    __table_args__ = (
        Index("ix_shipment_status", "status"),
        Index("ix_shipment_carrier", "carrier_id"),
    )

    shipment_number: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    order_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id"))
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("warehouses.id"), nullable=False
    )
    carrier_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carriers.id")
    )
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    origin_address: Mapped[dict] = mapped_column(JSONB, nullable=False)
    destination_address: Mapped[dict] = mapped_column(JSONB, nullable=False)
    total_weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    total_packages: Mapped[int] = mapped_column(Integer, default=1)
    scheduled_pickup: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_delivery: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_delivery: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tracking_number: Mapped[str | None] = mapped_column(String(128))
    consolidation_group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    state_history: Mapped[list] = mapped_column(JSONB, default=list)

    stops: Mapped[list[ShipmentStop]] = relationship(back_populates="shipment")
    route_plans: Mapped[list[RoutePlan]] = relationship(back_populates="shipment")


class ShipmentStop(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "shipment_stops"

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_type: Mapped[str] = mapped_column(String(16), nullable=False)
    address: Mapped[dict] = mapped_column(JSONB, nullable=False)
    planned_arrival: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_arrival: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="pending")

    shipment: Mapped[Shipment] = relationship(back_populates="stops")


class RoutePlan(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "route_plans"

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shipments.id"), nullable=False
    )
    carrier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("carriers.id"), nullable=False
    )
    total_distance_km: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    total_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    route_geometry: Mapped[dict] = mapped_column(JSONB, default=dict)
    optimization_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    is_selected: Mapped[bool] = mapped_column(default=False)

    shipment: Mapped[Shipment] = relationship(back_populates="route_plans")
