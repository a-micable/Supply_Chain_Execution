"""Warehouse receiving operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.context import get_correlation_id
from nexusops.core.logging import get_logger
from nexusops.core.types import WarehouseTaskType
from nexusops.models.warehouse import WarehouseTask
from nexusops.repositories.inventory import InventoryBalanceRepository
from nexusops.repositories.procurement import PurchaseOrderRepository
from nexusops.repositories.warehouse import WarehouseTaskRepository

logger = get_logger(__name__)


@dataclass
class ReceivingLine:
    sku_id: uuid.UUID
    quantity_expected: int
    quantity_received: int
    po_line_id: uuid.UUID | None = None
    damage_quantity: int = 0


@dataclass
class ReceivingResult:
    po_id: uuid.UUID | None
    warehouse_id: uuid.UUID
    lines: list[ReceivingLine]
    tasks_created: list[uuid.UUID]
    total_received: int
    discrepancies: list[str]


class ReceivingService:
    """Processes inbound receiving against purchase orders."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.po_repo = PurchaseOrderRepository(session)
        self.balance_repo = InventoryBalanceRepository(session)
        self.task_repo = WarehouseTaskRepository(session)

    async def receive_against_po(
        self,
        po_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        lines: list[ReceivingLine],
    ) -> ReceivingResult:
        po = await self.po_repo.get_with_lines(po_id)
        if po is None:
            raise ValueError(f"Purchase order {po_id} not found")

        tasks_created: list[uuid.UUID] = []
        discrepancies: list[str] = []
        total_received = 0

        for recv_line in lines:
            po_line = next(
                (pl for pl in po.lines if pl.sku_id == recv_line.sku_id), None
            )
            if po_line is None:
                discrepancies.append(f"SKU {recv_line.sku_id} not on PO")
                continue

            if recv_line.quantity_received > po_line.quantity_ordered - po_line.quantity_received:
                discrepancies.append(
                    f"Over-receipt for SKU {recv_line.sku_id}: "
                    f"received {recv_line.quantity_received}, "
                    f"remaining {po_line.quantity_ordered - po_line.quantity_received}"
                )

            good_qty = recv_line.quantity_received - recv_line.damage_quantity
            await self._update_inventory(warehouse_id, recv_line.sku_id, good_qty, recv_line.damage_quantity)

            po_line.quantity_received += recv_line.quantity_received
            if po_line.quantity_received >= po_line.quantity_ordered:
                po_line.line_status = "closed"

            putaway_task = await self._create_putaway_task(
                warehouse_id, recv_line.sku_id, good_qty, po_id
            )
            tasks_created.append(putaway_task.id)
            total_received += recv_line.quantity_received

        all_received = all(pl.quantity_received >= pl.quantity_ordered for pl in po.lines)
        any_received = any(pl.quantity_received > 0 for pl in po.lines)
        if all_received:
            po.status = "received"
        elif any_received:
            po.status = "partially_received"

        logger.info(
            "receiving_completed",
            po_id=str(po_id),
            total_received=total_received,
            discrepancies=len(discrepancies),
        )
        return ReceivingResult(
            po_id=po_id,
            warehouse_id=warehouse_id,
            lines=lines,
            tasks_created=tasks_created,
            total_received=total_received,
            discrepancies=discrepancies,
        )

    async def _update_inventory(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID, good_qty: int, damage_qty: int
    ) -> None:
        balance = await self.balance_repo.get_balance(warehouse_id, sku_id)
        if balance is None:
            from nexusops.models.inventory import InventoryBalance
            balance = InventoryBalance(
                warehouse_id=warehouse_id,
                sku_id=sku_id,
                on_hand=good_qty,
                damaged=damage_qty,
            )
            await self.balance_repo.add(balance)
        else:
            balance.on_hand += good_qty
            balance.damaged += damage_qty
            balance.version += 1

    async def _create_putaway_task(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID, quantity: int, po_id: uuid.UUID
    ) -> WarehouseTask:
        task = WarehouseTask(
            warehouse_id=warehouse_id,
            task_type=WarehouseTaskType.PUTAWAY,
            status="pending",
            sku_id=sku_id,
            quantity=quantity,
            reference_type="purchase_order",
            reference_id=po_id,
            task_data={"correlation_id": str(get_correlation_id())},
        )
        return await self.task_repo.add(task)
