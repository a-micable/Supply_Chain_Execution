"""Domain and infrastructure exceptions."""

from __future__ import annotations

from typing import Any
from uuid import UUID


class NexusOpsError(Exception):
    """Base exception for all NexusOps errors."""

    code: str = "NEXUSOPS_ERROR"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(NexusOpsError):
    code = "NOT_FOUND"


class ConflictError(NexusOpsError):
    code = "CONFLICT"


class ValidationError(NexusOpsError):
    code = "VALIDATION_ERROR"


class ConcurrencyError(NexusOpsError):
    code = "CONCURRENCY_ERROR"


class AllocationError(NexusOpsError):
    code = "ALLOCATION_ERROR"


class InsufficientInventoryError(AllocationError):
    code = "INSUFFICIENT_INVENTORY"

    def __init__(
        self,
        sku_id: UUID,
        requested: int,
        available: int,
        warehouse_id: UUID | None = None,
    ) -> None:
        super().__init__(
            f"Insufficient inventory for SKU {sku_id}: requested {requested}, available {available}",
            details={
                "sku_id": str(sku_id),
                "requested": requested,
                "available": available,
                "warehouse_id": str(warehouse_id) if warehouse_id else None,
            },
        )


class ReservationExpiredError(AllocationError):
    code = "RESERVATION_EXPIRED"


class RoutingConflictError(NexusOpsError):
    code = "ROUTING_CONFLICT"


class ShipmentStateError(NexusOpsError):
    code = "SHIPMENT_STATE_ERROR"

    def __init__(self, shipment_id: UUID, current: str, attempted: str) -> None:
        super().__init__(
            f"Invalid shipment state transition for {shipment_id}: {current} -> {attempted}",
            details={
                "shipment_id": str(shipment_id),
                "current_state": current,
                "attempted_state": attempted,
            },
        )


class ForecastDriftError(NexusOpsError):
    code = "FORECAST_DRIFT"


class EventOrderingError(NexusOpsError):
    code = "EVENT_ORDERING_ERROR"


class CacheInvalidationError(NexusOpsError):
    code = "CACHE_INVALIDATION_ERROR"


class WorkflowError(NexusOpsError):
    code = "WORKFLOW_ERROR"


class ReconciliationError(NexusOpsError):
    code = "RECONCILIATION_ERROR"


class OptimizationInfeasibleError(NexusOpsError):
    code = "OPTIMIZATION_INFEASIBLE"


class DependencyGraphError(NexusOpsError):
    code = "DEPENDENCY_GRAPH_ERROR"
