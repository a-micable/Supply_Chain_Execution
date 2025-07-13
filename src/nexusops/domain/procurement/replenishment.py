"""Replenishment planning based on safety stock and forecasts."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.logging import get_logger
from nexusops.domain.inventory.safety_stock import SafetyStockCalculator
from nexusops.models.procurement import PurchaseOrder, PurchaseOrderLine
from nexusops.repositories.inventory import InventoryBalanceRepository, SafetyStockPolicyRepository
from nexusops.repositories.procurement import PurchaseOrderRepository, SupplierRepository

logger = get_logger(__name__)


@dataclass
class ReplenishmentLine:
    sku_id: uuid.UUID
    warehouse_id: uuid.UUID
    current_available: int
    reorder_point: int
    safety_stock: int
    suggested_order_qty: int
    preferred_supplier_id: uuid.UUID | None = None
    unit_cost: Decimal = Decimal("0")


@dataclass
class ReplenishmentPlan:
    warehouse_id: uuid.UUID
    lines: list[ReplenishmentLine] = field(default_factory=list)
    run_id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ReplenishmentPlanner:
    """Generates replenishment plans when inventory falls below reorder points."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.policy_repo = SafetyStockPolicyRepository(session)
        self.balance_repo = InventoryBalanceRepository(session)
        self.supplier_repo = SupplierRepository(session)
        self.po_repo = PurchaseOrderRepository(session)
        self.safety_calc = SafetyStockCalculator(session)

    async def generate_plan(self, warehouse_id: uuid.UUID) -> ReplenishmentPlan:
        plan = ReplenishmentPlan(warehouse_id=warehouse_id)
        below_reorder = await self.policy_repo.list_below_reorder_point()

        for policy, available in below_reorder:
            if policy.warehouse_id != warehouse_id:
                continue

            safety_result = await self.safety_calc.calculate(
                policy.warehouse_id, policy.sku_id
            )
            order_qty = max(
                safety_result.reorder_point - available + safety_result.safety_stock_qty,
                safety_result.safety_stock_qty,
            )

            supplier = await self._select_supplier()
            plan.lines.append(
                ReplenishmentLine(
                    sku_id=policy.sku_id,
                    warehouse_id=warehouse_id,
                    current_available=available,
                    reorder_point=safety_result.reorder_point,
                    safety_stock=safety_result.safety_stock_qty,
                    suggested_order_qty=order_qty,
                    preferred_supplier_id=supplier.id if supplier else None,
                    unit_cost=Decimal("10.00"),
                )
            )

        logger.info(
            "replenishment_plan_generated",
            warehouse_id=str(warehouse_id),
            line_count=len(plan.lines),
        )
        return plan

    async def create_purchase_orders(
        self, plan: ReplenishmentPlan
    ) -> list[PurchaseOrder]:
        if not plan.lines:
            return []

        supplier_groups: dict[uuid.UUID, list[ReplenishmentLine]] = {}
        for line in plan.lines:
            sid = line.preferred_supplier_id or uuid.uuid4()
            supplier_groups.setdefault(sid, []).append(line)

        orders: list[PurchaseOrder] = []
        for supplier_id, lines in supplier_groups.items():
            po_number = f"PO-{uuid.uuid4().hex[:10].upper()}"
            total = sum(l.suggested_order_qty * l.unit_cost for l in lines)

            po = PurchaseOrder(
                po_number=po_number,
                supplier_id=supplier_id,
                warehouse_id=plan.warehouse_id,
                status="draft",
                order_date=datetime.now(timezone.utc),
                expected_delivery=datetime.now(timezone.utc) + timedelta(days=14),
                total_amount=total,
                replenishment_run_id=plan.run_id,
            )
            await self.po_repo.add(po)

            for line in lines:
                po_line = PurchaseOrderLine(
                    purchase_order_id=po.id,
                    sku_id=line.sku_id,
                    quantity_ordered=line.suggested_order_qty,
                    unit_cost=line.unit_cost,
                )
                self.session.add(po_line)

            orders.append(po)

        return orders

    async def _select_supplier(self):
        preferred = await self.supplier_repo.list_preferred()
        return preferred[0] if preferred else None
