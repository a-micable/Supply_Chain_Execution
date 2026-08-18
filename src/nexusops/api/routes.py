"""FastAPI route handlers."""

from __future__ import annotations

import uuid
import json
import jwt

from fastapi import APIRouter, Depends, Header, HTTPException, Request, WebSocket, WebSocketDisconnect, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, func
from sqlalchemy.orm import selectinload

from nexusops import __version__
from nexusops.core.context import set_correlation_id
from nexusops.core.exceptions import NexusOpsError
from nexusops.db.session import get_db_session
from nexusops.config.settings import get_settings
from nexusops.domain.inventory.allocation import AllocationRequest
from nexusops.domain.inventory.allocation import AllocationEngine
from nexusops.domain.optimization.engine import OptimizationEngine, OptimizationInput
from nexusops.domain.warehouse.receiving import ReceivingLine
from nexusops.domain.warehouse.transfers import TransferRequest
from nexusops.domain.inventory.allocation import AllocationResult
from nexusops.core.types import OrderStatus, ShipmentStatus
from nexusops.schemas.api import (
    AllocationRequestSchema,
    AuditEntryResponse,
    DashboardKpisResponse,
    HealthResponse,
    NetworkVisibilityResponse,
    OptimizationRequest,
    OrderCreate,
    OrderResponse,
    ReceivingRequest,
    TokenRequest,
    TokenResponse,
    ShipmentResponse,
    TransferRequestSchema,
    WarehouseResponse,
    InventoryBalanceRow,
    InventoryAdjustRequest,
    StockMovementRow,
    MeResponse,
    PurchaseOrderCreate,
    PurchaseOrderResponse,
)
from nexusops.api.auth import get_current_user, issue_token, require_roles
from nexusops.services.audit_service import AuditService
from nexusops.services.fulfillment_service import FulfillmentService
from nexusops.services.inventory_service import InventoryService
from nexusops.services.procurement_service import ProcurementService
from nexusops.services.transportation_service import TransportationService
from nexusops.services.warehouse_service import WarehouseService
from nexusops.repositories.inventory import InventoryBalanceRepository
from nexusops.repositories.fulfillment import OrderRepository, OrderLineRepository
from nexusops.repositories.warehouse import WarehouseRepository, WarehouseTransferRepository
from nexusops.repositories.procurement import PurchaseOrderRepository
from nexusops.repositories.inventory import SafetyStockPolicyRepository
from nexusops.models.inventory import InventoryBalance, Sku
from nexusops.models.fulfillment import Order, OrderLine
from nexusops.models.procurement import PurchaseOrder
from nexusops.models.warehouse import Warehouse, WarehouseTransfer
from nexusops.repositories.audit import AuditRepository
from nexusops.cache.redis_cache import create_redis_client

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


@router.post(
    "/orders",
    response_model=OrderResponse,
    dependencies=[Depends(correlation_id_middleware), Depends(require_roles("admin", "warehouse_operator"))],
)
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


@router.post(
    "/orders/{order_id}/fulfill",
    dependencies=[Depends(correlation_id_middleware), Depends(require_roles("admin", "warehouse_operator"))],
)
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


@router.post(
    "/inventory/allocate",
    dependencies=[Depends(correlation_id_middleware), Depends(require_roles("admin", "warehouse_operator"))],
)
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


@router.post("/inventory/reconcile/{warehouse_id}", dependencies=[Depends(require_roles("admin"))])
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


@router.post("/shipments/{shipment_id}/assign-carrier", dependencies=[Depends(require_roles("admin"))])
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


@router.post("/procurement/replenish/{warehouse_id}", dependencies=[Depends(require_roles("admin"))])
async def trigger_replenishment(
    warehouse_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    service = ProcurementService(session)
    plan = await service.generate_replenishment(warehouse_id)
    return {"lines": len(plan.lines), "run_id": str(plan.run_id)}


@router.post(
    "/warehouse/receive",
    dependencies=[Depends(require_roles("admin", "warehouse_operator"))],
)
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


@router.post(
    "/warehouse/transfers",
    dependencies=[Depends(require_roles("admin", "warehouse_operator"))],
)
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


@router.post("/optimization/run", dependencies=[Depends(require_roles("admin"))])
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


@router.get(
    "/audit/{entity_type}/{entity_id}",
    response_model=list[AuditEntryResponse],
    dependencies=[Depends(require_roles("admin", "auditor"))],
)
async def get_audit_trail(
    entity_type: str,
    entity_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> list[AuditEntryResponse]:
    audit = AuditService(session)
    entries = await audit.get_entity_history(entity_type, entity_id)
    return [AuditEntryResponse.model_validate(e) for e in entries]


# ---------------------------
# Product endpoints (MVP)
# ---------------------------


@router.post("/auth/token", response_model=TokenResponse)
async def token(
    body: TokenRequest,
    session: AsyncSession = Depends(get_db_session),
) -> TokenResponse:
    return await issue_token(body=body, session=session)


@router.get("/auth/me", response_model=MeResponse, dependencies=[Depends(require_roles("admin", "warehouse_operator", "auditor"))])
async def me(current=Depends(get_current_user)) -> MeResponse:
    return current


@router.get("/dashboard/kpis", response_model=DashboardKpisResponse, dependencies=[Depends(require_roles("admin", "warehouse_operator", "auditor"))])
async def dashboard_kpis(session: AsyncSession = Depends(get_db_session)) -> DashboardKpisResponse:
    inv_sum_stmt = select(func.coalesce(func.sum(InventoryBalance.on_hand), 0))
    total_on_hand = (await session.execute(inv_sum_stmt)).scalar_one()

    terminal_statuses = (OrderStatus.DELIVERED, OrderStatus.CANCELLED)
    active_orders_stmt = select(func.count(Order.id)).where(~Order.status.in_(terminal_statuses))
    active_orders = (await session.execute(active_orders_stmt)).scalar_one()

    safety_repo = SafetyStockPolicyRepository(session)
    low_stock_rows = await safety_repo.list_below_reorder_point()
    low_stock_count = len(low_stock_rows)

    # Recent activity: last audit entries for inventory/order/transfer-related entities.
    from nexusops.models.audit import AuditEntry

    recent_stmt = select(AuditEntry).order_by(AuditEntry.event_timestamp.desc()).limit(10)
    recent = (await session.execute(recent_stmt)).scalars().all()
    recent_activity = [
        {
            "id": str(e.id),
            "entity_type": e.entity_type,
            "entity_id": str(e.entity_id),
            "action": e.action,
            "event_timestamp": e.event_timestamp,
            "actor_id": e.actor_id,
            "is_manual_override": e.is_manual_override,
        }
        for e in recent
    ]

    return DashboardKpisResponse(
        total_on_hand=int(total_on_hand),
        active_orders=int(active_orders),
        low_stock_count=int(low_stock_count),
        recent_activity=recent_activity,
    )


@router.websocket("/dashboard/stream")
async def dashboard_stream(websocket: WebSocket) -> None:
    """
    Pushes domain events from the Redis stream to the frontend.
    Auth: `Authorization: Bearer <token>` header or `access_token` query param.
    """
    token = websocket.query_params.get("access_token") or websocket.headers.get("authorization", "").replace("Bearer ", "")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Validate token, set actor_id for audit association (even though WS itself is push-only).
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    except Exception:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    sub = payload.get("sub")
    if not sub:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    username = payload.get("username")
    if username:
        set_actor_id(str(username))

    roles = payload.get("roles") or []
    if not set(roles).intersection({"admin", "warehouse_operator", "auditor"}):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    redis_client = await create_redis_client()
    try:
        last_id = "0-0"
        while True:
            streams = await redis_client.xread({get_settings().event_stream_key: last_id}, count=50, block=5000)
            if not streams:
                continue
            _, entries = streams[0]
            for entry_id, entry in entries:
                last_id = entry_id
                raw = entry.get("data")
                if not raw:
                    continue
                parsed = json.loads(raw)
                await websocket.send_json({"type": "event", "event": parsed})
    except WebSocketDisconnect:
        return
    finally:
        try:
            await redis_client.close()
        except Exception:
            pass


@router.get("/warehouses", response_model=list[WarehouseResponse], dependencies=[Depends(require_roles("admin", "warehouse_operator", "auditor"))])
async def list_warehouses(session: AsyncSession = Depends(get_db_session)) -> list[WarehouseResponse]:
    repo = WarehouseRepository(session)
    warehouses = await repo.list_active()
    return [
        WarehouseResponse(id=w.id, warehouse_code=w.warehouse_code, name=w.name)
        for w in warehouses
    ]


@router.get("/inventory/balances", response_model=list[InventoryBalanceRow], dependencies=[Depends(require_roles("admin", "warehouse_operator", "auditor"))])
async def list_inventory_balances(
    warehouse_id: uuid.UUID | None = None,
    search: str | None = None,
    sort_by: str = "sku_code",
    sort_dir: str = "asc",
    page: int = 1,
    page_size: int = 25,
    session: AsyncSession = Depends(get_db_session),
) -> list[InventoryBalanceRow]:
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 25

    stmt = select(InventoryBalance, Sku).join(Sku, InventoryBalance.sku_id == Sku.id)
    if warehouse_id is not None:
        stmt = stmt.where(InventoryBalance.warehouse_id == warehouse_id)
    if search:
        ilike = f"%{search}%"
        stmt = stmt.where(or_(Sku.sku_code.ilike(ilike), Sku.description.ilike(ilike)))

    available_expr = (
        InventoryBalance.on_hand
        - InventoryBalance.reserved
        - InventoryBalance.allocated
        - InventoryBalance.damaged
        - InventoryBalance.quarantine
    )
    sort_dir_norm = sort_dir.lower()
    if sort_by == "available":
        stmt = stmt.order_by(available_expr.desc() if sort_dir_norm == "desc" else available_expr.asc())
    elif sort_by == "on_hand":
        stmt = stmt.order_by(InventoryBalance.on_hand.desc() if sort_dir_norm == "desc" else InventoryBalance.on_hand.asc())
    else:
        # Default stable sort
        stmt = stmt.order_by(Sku.sku_code.asc() if sort_dir_norm == "asc" else Sku.sku_code.desc())

    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    results = (await session.execute(stmt)).all()
    rows: list[InventoryBalanceRow] = []
    for bal, sku in results:
        available = max(0, (bal.on_hand - bal.reserved - bal.allocated - bal.damaged - bal.quarantine))
        rows.append(
            InventoryBalanceRow(
                warehouse_id=bal.warehouse_id,
                sku_id=bal.sku_id,
                sku_code=sku.sku_code,
                description=sku.description,
                uom=sku.uom,
                on_hand=bal.on_hand,
                reserved=bal.reserved,
                allocated=bal.allocated,
                available=int(available),
            )
        )
    return rows


@router.post(
    "/inventory/balances/{warehouse_id}/{sku_id}",
    dependencies=[Depends(require_roles("admin", "warehouse_operator"))],
)
async def adjust_inventory_balance(
    warehouse_id: uuid.UUID,
    sku_id: uuid.UUID,
    body: InventoryAdjustRequest,
    session: AsyncSession = Depends(get_db_session),
) -> InventoryBalanceRow:
    inv = InventoryService(session)
    # Load current balance to compute delta.
    balance_stmt = select(InventoryBalance).where(
        InventoryBalance.warehouse_id == warehouse_id,
        InventoryBalance.sku_id == sku_id,
    )
    balance = (await session.execute(balance_stmt)).scalar_one_or_none()
    current_on_hand = balance.on_hand if balance else 0
    delta = body.on_hand - current_on_hand
    await inv.adjust_inventory(warehouse_id=warehouse_id, sku_id=sku_id, quantity_delta=delta, reason=body.reason)

    # Reload with computed fields.
    sku_stmt = select(Sku).where(Sku.id == sku_id)
    sku = (await session.execute(sku_stmt)).scalar_one()
    new_balance_stmt = select(InventoryBalance).where(
        InventoryBalance.warehouse_id == warehouse_id,
        InventoryBalance.sku_id == sku_id,
    )
    new_balance = (await session.execute(new_balance_stmt)).scalar_one_or_none()
    if not new_balance:
        raise HTTPException(status_code=404, detail="Inventory balance not found after adjustment")

    available = max(0, new_balance.on_hand - new_balance.reserved - new_balance.allocated - new_balance.damaged - new_balance.quarantine)
    return InventoryBalanceRow(
        warehouse_id=new_balance.warehouse_id,
        sku_id=new_balance.sku_id,
        sku_code=sku.sku_code,
        description=sku.description,
        uom=sku.uom,
        on_hand=new_balance.on_hand,
        reserved=new_balance.reserved,
        allocated=new_balance.allocated,
        available=int(available),
    )


@router.get(
    "/inventory/movements",
    response_model=list[StockMovementRow],
    dependencies=[Depends(require_roles("admin", "warehouse_operator", "auditor"))],
)
async def inventory_movements(
    warehouse_id: uuid.UUID,
    sku_id: uuid.UUID,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[StockMovementRow]:
    from nexusops.models.audit import AuditEntry

    stmt = (
        select(AuditEntry)
        .where(
            AuditEntry.entity_type == "inventory_balance",
            AuditEntry.entity_id == sku_id,
        )
        .order_by(AuditEntry.event_timestamp.desc())
        .limit(200)
    )

    # metadata_ is stored in JSONB under `metadata`.
    if warehouse_id:
        stmt = stmt.where(AuditEntry.metadata_["warehouse_id"].astext == str(warehouse_id))
    if from_ts is not None:
        stmt = stmt.where(AuditEntry.event_timestamp >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(AuditEntry.event_timestamp <= to_ts)

    entries = (await session.execute(stmt)).scalars().all()
    rows: list[StockMovementRow] = []
    for e in entries:
        before_on_hand = e.before_state.get("on_hand") if e.before_state else None
        after_on_hand = e.after_state.get("on_hand") if e.after_state else None
        rows.append(
            StockMovementRow(
                event_timestamp=e.event_timestamp,
                action=e.action,
                before_on_hand=int(before_on_hand) if before_on_hand is not None else None,
                after_on_hand=int(after_on_hand) if after_on_hand is not None else None,
                is_manual_override=bool(e.is_manual_override),
            )
        )
    return rows


@router.get("/orders", response_model=list[OrderResponse], dependencies=[Depends(require_roles("admin", "warehouse_operator", "auditor"))])
async def list_orders(
    status: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 25,
    session: AsyncSession = Depends(get_db_session),
) -> list[OrderResponse]:
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 25

    stmt = select(Order)
    if status:
        stmt = stmt.where(Order.status == status)
    if search:
        ilike = f"%{search}%"
        stmt = stmt.where(or_(Order.external_order_id.ilike(ilike), Order.customer_id.ilike(ilike)))

    stmt = stmt.order_by(Order.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    orders = (await session.execute(stmt)).scalars().all()
    return [OrderResponse.model_validate(o) for o in orders]


@router.post("/orders/{order_id}/reserve", dependencies=[Depends(require_roles("admin", "warehouse_operator"))])
async def reserve_order(order_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> dict:
    order_repo = OrderRepository(session)
    order = await order_repo.get_with_lines(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status in (OrderStatus.CANCELLED, OrderStatus.SHIPPED, OrderStatus.DELIVERED):
        raise HTTPException(status_code=409, detail=f"Order in terminal state: {order.status}")

    alloc_engine = AllocationEngine(session)
    for line in order.lines:
        needed = line.quantity_ordered - line.quantity_allocated
        if needed <= 0:
            continue
        req = AllocationRequest(
            order_id=order.id,
            order_line_id=line.id,
            sku_id=line.sku_id,
            quantity=needed,
            preferred_warehouse_id=None,
            allow_split=order.allow_partial_fulfillment,
        )
        result: AllocationResult = await alloc_engine.allocate(req)
        line.quantity_allocated += result.total_allocated
        line.backorder_quantity = result.backorder_quantity

    any_backorder = any(l.backorder_quantity > 0 for l in order.lines)
    order.status = OrderStatus.PARTIALLY_ALLOCATED if any_backorder else OrderStatus.ALLOCATING

    await AuditService(session).record(
        entity_type="order",
        entity_id=order.id,
        action="reserved",
        after_state={"status": order.status},
    )
    return {"order_id": str(order.id), "status": order.status}


@router.post("/orders/{order_id}/cancel", dependencies=[Depends(require_roles("admin"))])
async def cancel_order(order_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> dict:
    order_repo = OrderRepository(session)
    order = await order_repo.get_with_lines(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.status in (OrderStatus.CANCELLED, OrderStatus.DELIVERED, OrderStatus.SHIPPED):
        raise HTTPException(status_code=409, detail=f"Order in terminal state: {order.status}")

    before = {"status": order.status}

    alloc_engine = AllocationEngine(session)
    await alloc_engine.release_reservations(order_id)
    order.status = OrderStatus.CANCELLED

    await AuditService(session).record(
        entity_type="order",
        entity_id=order.id,
        action="cancelled",
        before_state=before,
        after_state={"status": order.status},
        metadata={"released_reservations_for_order": str(order_id)},
    )
    return {"order_id": str(order.id), "status": order.status}


@router.get("/warehouse/transfers", dependencies=[Depends(require_roles("admin", "warehouse_operator", "auditor"))])
async def list_transfers(
    status: str | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    stmt = select(WarehouseTransfer)
    if status:
        stmt = stmt.where(WarehouseTransfer.status == status)
    stmt = stmt.order_by(WarehouseTransfer.created_at.desc()).limit(100)
    transfers = (await session.execute(stmt)).scalars().all()
    return [
        {
            "transfer_number": t.transfer_number,
            "status": t.status,
            "source_warehouse_id": str(t.source_warehouse_id),
            "destination_warehouse_id": str(t.destination_warehouse_id),
            "sku_id": str(t.sku_id),
            "quantity": t.quantity,
        }
        for t in transfers
    ]


@router.post("/purchase-orders", response_model=PurchaseOrderResponse, dependencies=[Depends(require_roles("admin", "warehouse_operator"))])
async def create_purchase_order(
    body: PurchaseOrderCreate,
    session: AsyncSession = Depends(get_db_session),
) -> PurchaseOrderResponse:
    service = ProcurementService(session)
    po = await service.create_po(
        supplier_id=body.supplier_id,
        warehouse_id=body.warehouse_id,
        lines=body.lines,
    )


@router.get("/purchase-orders", response_model=list[PurchaseOrderResponse], dependencies=[Depends(require_roles("admin", "warehouse_operator", "auditor"))])
async def list_purchase_orders(
    warehouse_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_db_session),
) -> list[PurchaseOrderResponse]:
    repo = PurchaseOrderRepository(session)
    if warehouse_id:
        pos = await repo.list_open_for_warehouse(warehouse_id)
    else:
        pos = await repo.list_pending_receipt(limit=50)
    return [
        PurchaseOrderResponse(
            id=po.id,
            po_number=po.po_number,
            supplier_id=po.supplier_id,
            warehouse_id=po.warehouse_id,
            status=po.status,
            order_date=po.order_date,
            expected_delivery=po.expected_delivery,
            total_amount=po.total_amount,
            currency=po.currency,
        )
        for po in pos
    ]
    return PurchaseOrderResponse(
        id=po.id,
        po_number=po.po_number,
        supplier_id=po.supplier_id,
        warehouse_id=po.warehouse_id,
        status=po.status,
        order_date=po.order_date,
        expected_delivery=po.expected_delivery,
        total_amount=po.total_amount,
        currency=po.currency,
    )


@router.post("/purchase-orders/{po_id}/submit", dependencies=[Depends(require_roles("admin"))])
async def submit_purchase_order(po_id: uuid.UUID, session: AsyncSession = Depends(get_db_session)) -> dict:
    service = ProcurementService(session)
    po = await service.submit_purchase_order(po_id)
    return {"po_id": str(po.id), "po_number": po.po_number, "status": po.status}


@router.post("/purchase-orders/{po_id}/receive", dependencies=[Depends(require_roles("admin", "warehouse_operator"))])
async def receive_purchase_order(
    po_id: uuid.UUID,
    body: ReceivingRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    # Body includes warehouse_id + lines; po_id is taken from path.
    if body.po_id != po_id:
        raise HTTPException(status_code=409, detail="PO id mismatch")
    service = WarehouseService(session)
    receiving_lines = [
        ReceivingLine(
            sku_id=l.sku_id,
            quantity_expected=l.quantity_expected,
            quantity_received=l.quantity_received,
            damage_quantity=l.damage_quantity,
        )
        for l in body.lines
    ]
    result = await service.receive_po(po_id, body.warehouse_id, receiving_lines)
    return {
        "total_received": result.total_received,
        "tasks_created": len(result.tasks_created),
        "discrepancies": result.discrepancies,
    }

