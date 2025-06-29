"""Shared domain types and identifiers."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import NewType

WarehouseId = NewType("WarehouseId", uuid.UUID)
SkuId = NewType("SkuId", uuid.UUID)
OrderId = NewType("OrderId", uuid.UUID)
ShipmentId = NewType("ShipmentId", uuid.UUID)
PurchaseOrderId = NewType("PurchaseOrderId", uuid.UUID)
SupplierId = NewType("SupplierId", uuid.UUID)
CarrierId = NewType("CarrierId", uuid.UUID)
LocationId = NewType("LocationId", uuid.UUID)
ReservationId = NewType("ReservationId", uuid.UUID)
EventId = NewType("EventId", uuid.UUID)
CorrelationId = NewType("CorrelationId", str)


class InventoryState(StrEnum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    ALLOCATED = "allocated"
    IN_TRANSIT = "in_transit"
    DAMAGED = "damaged"
    QUARANTINE = "quarantine"
    ON_HOLD = "on_hold"


class OrderStatus(StrEnum):
    RECEIVED = "received"
    VALIDATING = "validating"
    ALLOCATING = "allocating"
    PARTIALLY_ALLOCATED = "partially_allocated"
    FULFILLMENT_PLANNED = "fulfillment_planned"
    PICKING = "picking"
    PACKED = "packed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    BACKORDERED = "backordered"


class ShipmentStatus(StrEnum):
    DRAFT = "draft"
    PLANNED = "planned"
    CONSOLIDATED = "consolidated"
    LABEL_GENERATED = "label_generated"
    IN_TRANSIT = "in_transit"
    OUT_FOR_DELIVERY = "out_for_delivery"
    DELIVERED = "delivered"
    EXCEPTION = "exception"
    CANCELLED = "cancelled"


class PurchaseOrderStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    PARTIALLY_RECEIVED = "partially_received"
    RECEIVED = "received"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class WarehouseTaskType(StrEnum):
    RECEIVE = "receive"
    PUTAWAY = "putaway"
    PICK = "pick"
    PACK = "pack"
    TRANSFER_OUT = "transfer_out"
    TRANSFER_IN = "transfer_in"
    CYCLE_COUNT = "cycle_count"


class WarehouseTaskStatus(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EventType(StrEnum):
    INVENTORY_ADJUSTED = "inventory.adjusted"
    INVENTORY_RESERVED = "inventory.reserved"
    INVENTORY_RELEASED = "inventory.released"
    ALLOCATION_CREATED = "allocation.created"
    ALLOCATION_FAILED = "allocation.failed"
    ORDER_ROUTED = "order.routed"
    FULFILLMENT_PLANNED = "fulfillment.planned"
    SHIPMENT_CREATED = "shipment.created"
    SHIPMENT_STATE_CHANGED = "shipment.state_changed"
    ROUTE_PLANNED = "route.planned"
    FORECAST_UPDATED = "forecast.updated"
    PO_SUBMITTED = "procurement.po_submitted"
    RECEIVING_COMPLETED = "warehouse.receiving_completed"
    OPTIMIZATION_RUN = "optimization.run"
    MANUAL_OVERRIDE = "audit.manual_override"


class Money:
    """Immutable monetary amount with fixed precision."""

    __slots__ = ("amount", "currency")

    def __init__(self, amount: Decimal | str | float, currency: str = "USD") -> None:
        self.amount = Decimal(str(amount)).quantize(Decimal("0.0001"))
        self.currency = currency

    def __add__(self, other: Money) -> Money:
        if self.currency != other.currency:
            raise ValueError(f"Currency mismatch: {self.currency} vs {other.currency}")
        return Money(self.amount + other.amount, self.currency)

    def __repr__(self) -> str:
        return f"Money({self.amount}, {self.currency})"


class Quantity:
    """Inventory quantity with unit of measure."""

    __slots__ = ("value", "uom")

    def __init__(self, value: int, uom: str = "EA") -> None:
        if value < 0:
            raise ValueError("Quantity cannot be negative")
        self.value = value
        self.uom = uom

    def __sub__(self, other: Quantity) -> Quantity:
        if self.uom != other.uom:
            raise ValueError(f"UOM mismatch: {self.uom} vs {other.uom}")
        return Quantity(self.value - other.value, self.uom)

    def __add__(self, other: Quantity) -> Quantity:
        if self.uom != other.uom:
            raise ValueError(f"UOM mismatch: {self.uom} vs {other.uom}")
        return Quantity(self.value + other.value, self.uom)

    def __ge__(self, other: Quantity) -> bool:
        return self.value >= other.value

    def __gt__(self, other: Quantity) -> bool:
        return self.value > other.value

    def __le__(self, other: Quantity) -> bool:
        return self.value <= other.value


class Timestamped:
    created_at: datetime
    updated_at: datetime
