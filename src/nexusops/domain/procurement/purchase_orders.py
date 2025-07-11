"""Purchase order lifecycle management."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.context import get_correlation_id
from nexusops.core.exceptions import ValidationError, WorkflowError
from nexusops.core.logging import get_logger
from nexusops.core.types import EventType, PurchaseOrderStatus
from nexusops.events.bus import EventBus
from nexusops.events.schemas import DomainEventPayload
from nexusops.models.procurement import PurchaseOrder
from nexusops.repositories.procurement import PurchaseOrderRepository, SupplierRepository

logger = get_logger(__name__)

PO_TRANSITIONS: dict[str, set[str]] = {
    PurchaseOrderStatus.DRAFT: {PurchaseOrderStatus.SUBMITTED, PurchaseOrderStatus.CANCELLED},
    PurchaseOrderStatus.SUBMITTED: {
        PurchaseOrderStatus.ACKNOWLEDGED,
        PurchaseOrderStatus.CANCELLED,
    },
    PurchaseOrderStatus.ACKNOWLEDGED: {
        PurchaseOrderStatus.PARTIALLY_RECEIVED,
        PurchaseOrderStatus.RECEIVED,
        PurchaseOrderStatus.CANCELLED,
    },
    PurchaseOrderStatus.PARTIALLY_RECEIVED: {
        PurchaseOrderStatus.RECEIVED,
        PurchaseOrderStatus.CLOSED,
    },
    PurchaseOrderStatus.RECEIVED: {PurchaseOrderStatus.CLOSED},
    PurchaseOrderStatus.CLOSED: set(),
    PurchaseOrderStatus.CANCELLED: set(),
}


class PurchaseOrderManager:
    """Manages purchase order state transitions and validation."""

    def __init__(self, session: AsyncSession, event_bus: EventBus | None = None) -> None:
        self.session = session
        self.event_bus = event_bus
        self.po_repo = PurchaseOrderRepository(session)
        self.supplier_repo = SupplierRepository(session)

    async def submit(self, po_id: uuid.UUID) -> PurchaseOrder:
        po = await self.po_repo.get_with_lines(po_id)
        if po is None:
            raise ValidationError(f"Purchase order {po_id} not found")
        self._validate_transition(po.status, PurchaseOrderStatus.SUBMITTED)
        if not po.lines:
            raise ValidationError(f"PO {po_id} has no lines")

        supplier = await self.supplier_repo.get_by_id(po.supplier_id)
        if supplier is None or not supplier.is_active:
            raise ValidationError(f"Supplier {po.supplier_id} is inactive")

        po.status = PurchaseOrderStatus.SUBMITTED
        await self._publish_event(po, "submitted")
        logger.info("po_submitted", po_number=po.po_number)
        return po

    async def acknowledge(self, po_id: uuid.UUID, expected_delivery: datetime | None = None) -> PurchaseOrder:
        po = await self.po_repo.get_by_id_or_raise(po_id)
        self._validate_transition(po.status, PurchaseOrderStatus.ACKNOWLEDGED)
        po.status = PurchaseOrderStatus.ACKNOWLEDGED
        if expected_delivery:
            po.expected_delivery = expected_delivery
        await self._publish_event(po, "acknowledged")
        return po

    async def record_receipt(
        self, po_id: uuid.UUID, line_receipts: dict[uuid.UUID, int]
    ) -> PurchaseOrder:
        po = await self.po_repo.get_with_lines(po_id)
        if po is None:
            raise ValidationError(f"PO {po_id} not found")

        if po.status not in (
            PurchaseOrderStatus.ACKNOWLEDGED,
            PurchaseOrderStatus.PARTIALLY_RECEIVED,
        ):
            raise WorkflowError(f"Cannot receive against PO in status {po.status}")

        total_received = 0
        for line in po.lines:
            if line.id in line_receipts:
                qty = line_receipts[line.id]
                if line.quantity_received + qty > line.quantity_ordered:
                    raise ValidationError(
                        f"Over-receipt on line {line.id}: "
                        f"ordered {line.quantity_ordered}, "
                        f"already received {line.quantity_received}, "
                        f"attempting {qty}"
                    )
                line.quantity_received += qty
                total_received += qty
                if line.quantity_received >= line.quantity_ordered:
                    line.line_status = "closed"

        all_closed = all(l.line_status == "closed" for l in po.lines)
        any_received = any(l.quantity_received > 0 for l in po.lines)

        if all_closed:
            po.status = PurchaseOrderStatus.RECEIVED
        elif any_received:
            po.status = PurchaseOrderStatus.PARTIALLY_RECEIVED

        await self._publish_event(po, "receipt_recorded", {"total_received": total_received})
        return po

    async def close(self, po_id: uuid.UUID) -> PurchaseOrder:
        po = await self.po_repo.get_by_id_or_raise(po_id)
        self._validate_transition(po.status, PurchaseOrderStatus.CLOSED)
        po.status = PurchaseOrderStatus.CLOSED
        return po

    async def cancel(self, po_id: uuid.UUID, reason: str) -> PurchaseOrder:
        po = await self.po_repo.get_by_id_or_raise(po_id)
        self._validate_transition(po.status, PurchaseOrderStatus.CANCELLED)
        if po.status in (PurchaseOrderStatus.RECEIVED, PurchaseOrderStatus.PARTIALLY_RECEIVED):
            raise WorkflowError(f"Cannot cancel PO {po_id} with receipts recorded")
        po.status = PurchaseOrderStatus.CANCELLED
        po.notes = f"Cancelled: {reason}"
        return po

    def _validate_transition(self, current: str, target: str) -> None:
        allowed = PO_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise WorkflowError(f"Invalid PO transition: {current} -> {target}")

    async def _publish_event(
        self, po: PurchaseOrder, action: str, extra: dict | None = None
    ) -> None:
        if self.event_bus is None:
            return
        payload = {"po_number": po.po_number, "status": po.status, "action": action}
        if extra:
            payload.update(extra)
        await self.event_bus.publish(
            DomainEventPayload(
                event_type=EventType.PO_SUBMITTED,
                aggregate_type="purchase_order",
                aggregate_id=po.id,
                payload=payload,
                correlation_id=str(get_correlation_id()),
            )
        )

    async def calculate_open_po_value(self, warehouse_id: uuid.UUID) -> Decimal:
        open_pos = await self.po_repo.list_open_for_warehouse(warehouse_id)
        total = Decimal("0")
        for po in open_pos:
            for line in po.lines:
                remaining = line.quantity_ordered - line.quantity_received
                total += Decimal(str(remaining)) * line.unit_cost
        return total

    async def list_overdue(self) -> list[PurchaseOrder]:
        now = datetime.now(timezone.utc)
        pending = await self.po_repo.list_pending_receipt()
        return [po for po in pending if po.expected_delivery and po.expected_delivery < now]
