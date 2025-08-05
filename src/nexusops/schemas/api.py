"""Pydantic request/response schemas for API layer."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AddressSchema(BaseModel):
    street: str
    city: str
    state: str
    postal_code: str
    country: str = "US"
    latitude: float | None = None
    longitude: float | None = None


class OrderLineCreate(BaseModel):
    sku_id: uuid.UUID
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(default=Decimal("0"))


class OrderCreate(BaseModel):
    external_order_id: str
    customer_id: str
    ship_to_address: AddressSchema
    lines: list[OrderLineCreate] = Field(min_length=1)
    priority: int = Field(default=5, ge=1, le=10)
    allow_partial_fulfillment: bool = True
    routing_strategy: str = "cost_optimized"


class OrderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_order_id: str
    customer_id: str
    status: str
    priority: int
    allow_partial_fulfillment: bool
    created_at: datetime


class AllocationRequestSchema(BaseModel):
    order_id: uuid.UUID
    order_line_id: uuid.UUID
    sku_id: uuid.UUID
    quantity: int = Field(gt=0)
    preferred_warehouse_id: uuid.UUID | None = None
    allow_split: bool = True


class NetworkVisibilityResponse(BaseModel):
    sku_id: uuid.UUID
    warehouses: list[dict[str, Any]]


class ShipmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    shipment_number: str
    status: str
    warehouse_id: uuid.UUID
    carrier_id: uuid.UUID | None
    total_packages: int
    created_at: datetime


class PurchaseOrderCreate(BaseModel):
    supplier_id: uuid.UUID
    warehouse_id: uuid.UUID
    lines: list[dict[str, Any]]


class ReceivingLineSchema(BaseModel):
    sku_id: uuid.UUID
    quantity_expected: int
    quantity_received: int
    damage_quantity: int = 0


class ReceivingRequest(BaseModel):
    po_id: uuid.UUID
    warehouse_id: uuid.UUID
    lines: list[ReceivingLineSchema]


class TransferRequestSchema(BaseModel):
    source_warehouse_id: uuid.UUID
    destination_warehouse_id: uuid.UUID
    sku_id: uuid.UUID
    quantity: int = Field(gt=0)


class OptimizationRequest(BaseModel):
    reference_type: str
    reference_id: uuid.UUID
    objective: str
    constraints: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)


class AuditEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    action: str
    event_timestamp: datetime
    is_manual_override: bool


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
