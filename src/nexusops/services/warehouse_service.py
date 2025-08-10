"""Warehouse operations service."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.domain.warehouse.pick_pack import PickLine, PickPackService, PickWave
from nexusops.domain.warehouse.receiving import ReceivingLine, ReceivingResult, ReceivingService
from nexusops.domain.warehouse.transfers import TransferRequest, TransferService
from nexusops.models.warehouse import WarehouseTransfer
from nexusops.services.audit_service import AuditService


class WarehouseService:
    """Orchestrates receiving, picking, packing, and transfers."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.receiving = ReceivingService(session)
        self.pick_pack = PickPackService(session)
        self.transfers = TransferService(session)
        self.audit = AuditService(session)

    async def receive_po(
        self, po_id: uuid.UUID, warehouse_id: uuid.UUID, lines: list[ReceivingLine]
    ) -> ReceivingResult:
        result = await self.receiving.receive_against_po(po_id, warehouse_id, lines)
        await self.audit.record(
            entity_type="purchase_order",
            entity_id=po_id,
            action="received",
            after_state={"total_received": result.total_received},
        )
        return result

    async def create_pick_wave(
        self, warehouse_id: uuid.UUID, order_id: uuid.UUID, lines: list[PickLine]
    ) -> PickWave:
        return await self.pick_pack.create_pick_wave(warehouse_id, order_id, lines)

    async def initiate_transfer(self, request: TransferRequest) -> WarehouseTransfer:
        transfer = await self.transfers.initiate_transfer(request)
        await self.audit.record(
            entity_type="transfer",
            entity_id=transfer.id,
            action="initiated",
            after_state={"quantity": request.quantity},
        )
        return transfer
