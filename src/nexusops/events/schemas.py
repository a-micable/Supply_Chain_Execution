"""Domain event definitions and serialization."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from nexusops.core.types import EventType


@dataclass
class DomainEventPayload:
    event_type: EventType
    aggregate_type: str
    aggregate_id: uuid.UUID
    payload: dict[str, Any]
    correlation_id: str
    causation_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "aggregate_type": self.aggregate_type,
            "aggregate_id": str(self.aggregate_id),
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "metadata": self.metadata,
            "occurred_at": self.occurred_at.isoformat(),
        }


@dataclass
class InventoryAdjustedEvent:
    warehouse_id: uuid.UUID
    sku_id: uuid.UUID
    quantity_delta: int
    reason: str
    balance_before: int
    balance_after: int

    def to_payload(self) -> dict[str, Any]:
        return {
            "warehouse_id": str(self.warehouse_id),
            "sku_id": str(self.sku_id),
            "quantity_delta": self.quantity_delta,
            "reason": self.reason,
            "balance_before": self.balance_before,
            "balance_after": self.balance_after,
        }


@dataclass
class ShipmentStateChangedEvent:
    shipment_id: uuid.UUID
    previous_status: str
    new_status: str
    shipment_number: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "shipment_id": str(self.shipment_id),
            "previous_status": self.previous_status,
            "new_status": self.new_status,
            "shipment_number": self.shipment_number,
        }


@dataclass
class ForecastUpdatedEvent:
    warehouse_id: uuid.UUID
    sku_id: uuid.UUID
    model_version: str
    drift_detected: bool
    drift_score: float

    def to_payload(self) -> dict[str, Any]:
        return {
            "warehouse_id": str(self.warehouse_id),
            "sku_id": str(self.sku_id),
            "model_version": self.model_version,
            "drift_detected": self.drift_detected,
            "drift_score": self.drift_score,
        }
