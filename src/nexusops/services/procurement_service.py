"""Procurement system service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.types import PurchaseOrderStatus
from nexusops.domain.procurement.replenishment import ReplenishmentPlanner, ReplenishmentPlan
from nexusops.domain.procurement.vendor_performance import PerformanceReport, VendorPerformanceTracker
from nexusops.models.procurement import PurchaseOrder
from nexusops.repositories.procurement import PurchaseOrderRepository, SupplierRepository
from nexusops.services.audit_service import AuditService


class ProcurementService:
    """Manages purchase orders, replenishment, and vendor performance."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.po_repo = PurchaseOrderRepository(session)
        self.supplier_repo = SupplierRepository(session)
        self.replenishment_planner = ReplenishmentPlanner(session)
        self.vendor_tracker = VendorPerformanceTracker(session)
        self.audit = AuditService(session)

    async def submit_purchase_order(self, po_id: uuid.UUID) -> PurchaseOrder:
        po = await self.po_repo.get_by_id_or_raise(po_id)
        if po.status != PurchaseOrderStatus.DRAFT:
            raise ValueError(f"PO {po_id} cannot be submitted from status {po.status}")
        po.status = PurchaseOrderStatus.SUBMITTED
        await self.audit.record(
            entity_type="purchase_order",
            entity_id=po_id,
            action="submitted",
            before_state={"status": PurchaseOrderStatus.DRAFT},
            after_state={"status": PurchaseOrderStatus.SUBMITTED},
        )
        return po

    async def generate_replenishment(self, warehouse_id: uuid.UUID) -> ReplenishmentPlan:
        plan = await self.replenishment_planner.generate_plan(warehouse_id)
        if plan.lines:
            await self.replenishment_planner.create_purchase_orders(plan)
        return plan

    async def get_vendor_performance(self, period_days: int = 90) -> PerformanceReport:
        return await self.vendor_tracker.generate_report(period_days)

    async def create_po(
        self,
        supplier_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        lines: list[dict],
    ) -> PurchaseOrder:
        po_number = f"PO-{uuid.uuid4().hex[:10].upper()}"
        total = sum(
            Decimal(str(l["quantity"])) * Decimal(str(l.get("unit_cost", "0")))
            for l in lines
        )
        po = PurchaseOrder(
            po_number=po_number,
            supplier_id=supplier_id,
            warehouse_id=warehouse_id,
            status=PurchaseOrderStatus.DRAFT,
            order_date=datetime.now(timezone.utc),
            total_amount=total,
        )
        await self.po_repo.add(po)

        from nexusops.models.procurement import PurchaseOrderLine
        for line_data in lines:
            po_line = PurchaseOrderLine(
                purchase_order_id=po.id,
                sku_id=uuid.UUID(str(line_data["sku_id"])),
                quantity_ordered=line_data["quantity"],
                unit_cost=Decimal(str(line_data.get("unit_cost", "0"))),
            )
            self.session.add(po_line)

        return po
