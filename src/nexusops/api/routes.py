"""FastAPI route handlers."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from nexusops import __version__
from nexusops.core.context import set_correlation_id
from nexusops.core.exceptions import NexusOpsError
from nexusops.db.session import get_db_session
from nexusops.domain.inventory.allocation import AllocationRequest
from nexusops.domain.optimization.engine import OptimizationEngine, OptimizationInput
from nexusops.domain.warehouse.receiving import ReceivingLine
from nexusops.domain.warehouse.transfers import TransferRequest
from nexusops.schemas.api import (
    AllocationRequestSchema,
    AuditEntryResponse,
    HealthResponse,
    NetworkVisibilityResponse,
    OptimizationRequest,
    OrderCreate,
    OrderResponse,
    ReceivingRequest,
    ShipmentResponse,
    TransferRequestSchema,
)
from nexusops.services.audit_service import AuditService
from nexusops.services.fulfillment_service import FulfillmentService
from nexusops.services.inventory_service import InventoryService
from nexusops.services.procurement_service import ProcurementService
from nexusops.services.transportation_service import TransportationService
from nexusops.services.warehouse_service import WarehouseService

router = APIRouter()


async def correlation_id_middleware(
    request: Request,
    x_correlation_id: str | None = Header(default=None),
) -> None:
    cid = x_correlation_id or str(uuid.uuid4())
    set_correlation_id(cid)


def handle_domain_error(exc: NexusOpsError) -> HTTPException:
    status_map = {
        "NOT_FOUND": 404,
        "CONFLICT": 409,
        "VALIDATION_ERROR": 422,
        "CONCURRENCY_ERROR": 409,
        "ALLOCATION_ERROR": 422,
        "INSUFFICIENT_INVENTORY": 422,
        "ROUTING_CONFLICT": 422,
        "SHIPMENT_STATE_ERROR": 422,
        "WORKFLOW_ERROR": 500,
    }
    status = status_map.get(exc.code, 500)
    return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.message, "details": exc.details})


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    from nexusops.config.settings import get_settings
    settings = get_settings()
    return HealthResponse(status="healthy", version=__version__, environment=settings.environment)


@router.post("/orders", response_model=OrderResponse, dependencies=[Depends(correlation_id_middleware)])
async def create_order(
    body: OrderCreate,
    session: AsyncSession = Depends(get_db_session),
) -> OrderResponse:
    service = FulfillmentService(session)
    try:
        order = await service.create_order(
            external_order_id=body.external_order_id,
            customer_id=body.customer_id,
            ship_to_address=body.ship_to_address.model_dump(),
            lines=[l.model_dump(mode="json") for l in body.lines],
            priority=body.priority,
            allow_partial=body.allow_partial_fulfillment,
            routing_strategy=body.routing_strategy,
        )
        return OrderResponse.model_validate(order)
    except NexusOpsError as exc:
        raise handle_domain_error(exc) from exc


@router.post("/orders/{order_id}/fulfill", dependencies=[Depends(correlation_id_middleware)])
async def fulfill_order(
    order_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    service = FulfillmentService(session)
    try:
        result = await service.process_order(order_id)
        shipments = await service.generate_shipments(order_id)
        return {
            "order_id": str(order_id),
            "status": result.status,
            "is_partial": result.is_partial,
            "shipments_created": len(shipments),
            "workflow_id": result.workflow_id,
        }
    except NexusOpsError as exc:
        raise handle_domain_error(exc) from exc


@router.get("/inventory/network/{sku_id}", response_model=NetworkVisibilityResponse)
async def network_visibility(
    sku_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> NetworkVisibilityResponse:
    service = InventoryService(session)
    warehouses = await service.get_network_visibility(sku_id)
    return NetworkVisibilityResponse(sku_id=sku_id, warehouses=warehouses)


@router.post("/inventory/allocate", dependencies=[Depends(correlation_id_middleware)])
async def allocate_inventory(
    body: AllocationRequestSchema,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    service = InventoryService(session)
    request = AllocationRequest(
        order_id=body.order_id,
        order_line_id=body.order_line_id,
        sku_id=body.sku_id,
        quantity=body.quantity,
        preferred_warehouse_id=body.preferred_warehouse_id,
        allow_split=body.allow_split,
    )
    try:
        result = await service.allocate_for_order_line(request)
        return {
            "total_allocated": result.total_allocated,
            "backorder_quantity": result.backorder_quantity,
            "allocations": [
                {"warehouse_id": str(w), "quantity": q} for w, q in result.allocations
            ],
        }
    except NexusOpsError as exc:
        raise handle_domain_error(exc) from exc


@router.post("/inventory/reconcile/{warehouse_id}")
async def reconcile_inventory(
    warehouse_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    service = InventoryService(session)
    report = await service.reconcile(warehouse_id)
    return {
        "is_balanced": report.is_balanced,
        "discrepancies": len(report.discrepancies),
        "details": [
            {
                "sku_id": str(d.sku_id),
                "type": d.discrepancy_type,
                "severity": d.severity,
            }
            for d in report.discrepancies
        ],
    }


@router.post("/shipments/{shipment_id}/route")
async def plan_shipment_routes(
    shipment_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    service = TransportationService(session)
    result = await service.plan_routes(shipment_id)
    return {
        "shipment_id": str(shipment_id),
        "options": len(result.options),
        "selected_cost": str(result.selected_option.estimated_cost) if result.selected_option else None,
    }


@router.post("/shipments/{shipment_id}/assign-carrier")
async def assign_carrier(
    shipment_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    service = TransportationService(session)
    assignment = await service.assign_carrier(shipment_id)
    return {
        "carrier_code": assignment.carrier_code,
        "estimated_cost": str(assignment.estimated_cost),
        "score": assignment.score,
    }


@router.post("/procurement/replenish/{warehouse_id}")
async def trigger_replenishment(
    warehouse_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    service = ProcurementService(session)
    plan = await service.generate_replenishment(warehouse_id)
    return {"lines": len(plan.lines), "run_id": str(plan.run_id)}


@router.post("/warehouse/receive")
async def receive_inventory(
    body: ReceivingRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    service = WarehouseService(session)
    lines = [
        ReceivingLine(
            sku_id=l.sku_id,
            quantity_expected=l.quantity_expected,
            quantity_received=l.quantity_received,
            damage_quantity=l.damage_quantity,
        )
        for l in body.lines
    ]
    result = await service.receive_po(body.po_id, body.warehouse_id, lines)
    return {
        "total_received": result.total_received,
        "tasks_created": len(result.tasks_created),
        "discrepancies": result.discrepancies,
    }


@router.post("/warehouse/transfers")
async def create_transfer(
    body: TransferRequestSchema,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    service = WarehouseService(session)
    try:
        transfer = await service.initiate_transfer(
            TransferRequest(
                source_warehouse_id=body.source_warehouse_id,
                destination_warehouse_id=body.destination_warehouse_id,
                sku_id=body.sku_id,
                quantity=body.quantity,
            )
        )
        return {"transfer_number": transfer.transfer_number, "status": transfer.status}
    except NexusOpsError as exc:
        raise handle_domain_error(exc) from exc


@router.post("/optimization/run")
async def run_optimization(
    body: OptimizationRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    engine = OptimizationEngine(session)
    try:
        result = await engine.optimize(
            OptimizationInput(
                reference_type=body.reference_type,
                reference_id=body.reference_id,
                objective=body.objective,
                constraints=body.constraints,
                parameters=body.parameters,
            )
        )
        return {
            "run_id": str(result.run_id),
            "objective_value": result.objective_value,
            "is_feasible": result.is_feasible,
            "solution": result.solution,
        }
    except NexusOpsError as exc:
        raise handle_domain_error(exc) from exc


@router.get("/audit/{entity_type}/{entity_id}", response_model=list[AuditEntryResponse])
async def get_audit_trail(
    entity_type: str,
    entity_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditEntryResponse]:
    audit = AuditService(session)
    entries = await audit.get_entity_history(entity_type, entity_id)
    return [AuditEntryResponse.model_validate(e) for e in entries]
