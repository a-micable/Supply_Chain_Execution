"""Inter-warehouse transfer operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.context import get_correlation_id
from nexusops.core.exceptions import InsufficientInventoryError, WorkflowError
from nexusops.core.logging import get_logger
from nexusops.core.types import WarehouseTaskType
from nexusops.models.warehouse import WarehouseTask, WarehouseTransfer
from nexusops.repositories.inventory import InventoryBalanceRepository
from nexusops.repositories.warehouse import WarehouseTaskRepository, WarehouseTransferRepository

logger = get_logger(__name__)


@dataclass
class TransferRequest:
    source_warehouse_id: uuid.UUID
    destination_warehouse_id: uuid.UUID
    sku_id: uuid.UUID
    quantity: int
    scheduled_ship_date: datetime | None = None


class TransferService:
    """Manages inventory transfers between warehouses."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.transfer_repo = WarehouseTransferRepository(session)
        self.balance_repo = InventoryBalanceRepository(session)
        self.task_repo = WarehouseTaskRepository(session)

    async def initiate_transfer(self, request: TransferRequest) -> WarehouseTransfer:
        if request.source_warehouse_id == request.destination_warehouse_id:
            raise WorkflowError("Source and destination warehouses must differ")

        available = await self.balance_repo.get_aggregated_available(
            request.source_warehouse_id, request.sku_id
        )
        if available < request.quantity:
            raise InsufficientInventoryError(
                request.sku_id, request.quantity, available, request.source_warehouse_id
            )

        transfer_number = f"XFR-{uuid.uuid4().hex[:10].upper()}"
        transfer = WarehouseTransfer(
            transfer_number=transfer_number,
            source_warehouse_id=request.source_warehouse_id,
            destination_warehouse_id=request.destination_warehouse_id,
            sku_id=request.sku_id,
            quantity=request.quantity,
            status="pending",
            scheduled_ship_date=request.scheduled_ship_date,
            correlation_id=str(get_correlation_id()),
        )
        await self.transfer_repo.add(transfer)

        source_balance = await self.balance_repo.get_balance(
            request.source_warehouse_id, request.sku_id
        )
        if source_balance:
            source_balance.on_hand -= request.quantity
            source_balance.in_transit += request.quantity
            source_balance.version += 1

        await self._create_transfer_out_task(transfer)
        logger.info("transfer_initiated", transfer_number=transfer_number)
        return transfer

    async def ship_transfer(self, transfer_id: uuid.UUID) -> WarehouseTransfer:
        transfer = await self.transfer_repo.get_by_id_or_raise(transfer_id)
        if transfer.status not in ("pending", "picking"):
            raise WorkflowError(f"Transfer {transfer_id} cannot be shipped from status {transfer.status}")

        transfer.status = "shipped"
        transfer.quantity_shipped = transfer.quantity
        return transfer

    async def receive_transfer(
        self, transfer_id: uuid.UUID, quantity_received: int | None = None
    ) -> WarehouseTransfer:
        transfer = await self.transfer_repo.get_by_id_or_raise(transfer_id)
        if transfer.status not in ("shipped", "in_transit"):
            raise WorkflowError(f"Transfer {transfer_id} not in shippable state")

        qty = quantity_received or transfer.quantity_shipped
        transfer.quantity_received = qty
        transfer.status = "received"

        source_balance = await self.balance_repo.get_balance(
            transfer.source_warehouse_id, transfer.sku_id
        )
        if source_balance:
            source_balance.in_transit = max(0, source_balance.in_transit - qty)

        dest_balance = await self.balance_repo.get_balance(
            transfer.destination_warehouse_id, transfer.sku_id
        )
        if dest_balance:
            dest_balance.on_hand += qty
            dest_balance.version += 1
        else:
            from nexusops.models.inventory import InventoryBalance
            dest_balance = InventoryBalance(
                warehouse_id=transfer.destination_warehouse_id,
                sku_id=transfer.sku_id,
                on_hand=qty,
            )
            await self.balance_repo.add(dest_balance)

        await self._create_transfer_in_task(transfer, qty)
        return transfer

    async def _create_transfer_out_task(self, transfer: WarehouseTransfer) -> WarehouseTask:
        task = WarehouseTask(
            warehouse_id=transfer.source_warehouse_id,
            task_type=WarehouseTaskType.TRANSFER_OUT,
            status="pending",
            sku_id=transfer.sku_id,
            quantity=transfer.quantity,
            reference_type="transfer",
            reference_id=transfer.id,
        )
        return await self.task_repo.add(task)

    async def _create_transfer_in_task(
        self, transfer: WarehouseTransfer, quantity: int
    ) -> WarehouseTask:
        task = WarehouseTask(
            warehouse_id=transfer.destination_warehouse_id,
            task_type=WarehouseTaskType.TRANSFER_IN,
            status="pending",
            sku_id=transfer.sku_id,
            quantity=quantity,
            reference_type="transfer",
            reference_id=transfer.id,
        )
        return await self.task_repo.add(task)
