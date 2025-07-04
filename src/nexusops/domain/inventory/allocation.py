"""Inventory allocation engine with multi-warehouse support."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.context import get_correlation_id
from nexusops.core.exceptions import (
    AllocationError,
    InsufficientInventoryError,
    ReservationExpiredError,
)
from nexusops.core.logging import get_logger
from nexusops.core.types import EventType, InventoryState
from nexusops.models.inventory import InventoryBalance, InventoryReservation
from nexusops.repositories.inventory import (
    InventoryBalanceRepository,
    InventoryReservationRepository,
)
from nexusops.repositories.warehouse import WarehouseRepository

logger = get_logger(__name__)


@dataclass
class AllocationRequest:
    order_id: uuid.UUID
    order_line_id: uuid.UUID
    sku_id: uuid.UUID
    quantity: int
    preferred_warehouse_id: uuid.UUID | None = None
    allow_split: bool = True


@dataclass
class AllocationResult:
    order_line_id: uuid.UUID
    allocations: list[tuple[uuid.UUID, int]] = field(default_factory=list)
    total_allocated: int = 0
    backorder_quantity: int = 0
    reservation_ids: list[uuid.UUID] = field(default_factory=list)

    @property
    def is_fully_allocated(self) -> bool:
        return self.backorder_quantity == 0


@dataclass
class WarehouseScore:
    warehouse_id: uuid.UUID
    available: int
    distance_score: float
    cost_score: float
    priority_score: float

    @property
    def composite_score(self) -> float:
        return self.distance_score * 0.3 + self.cost_score * 0.4 + self.priority_score * 0.3


class AllocationEngine:
    """Determines optimal warehouse allocation for order lines."""

    RESERVATION_TTL_MINUTES = 30

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.balance_repo = InventoryBalanceRepository(session)
        self.reservation_repo = InventoryReservationRepository(session)
        self.warehouse_repo = WarehouseRepository(session)

    async def allocate(self, request: AllocationRequest) -> AllocationResult:
        logger.info(
            "allocation_started",
            order_id=str(request.order_id),
            sku_id=str(request.sku_id),
            quantity=request.quantity,
        )

        result = AllocationResult(order_line_id=request.order_line_id)
        remaining = request.quantity

        warehouse_scores = await self._rank_warehouses(request)
        if request.preferred_warehouse_id:
            warehouse_scores.sort(
                key=lambda w: (w.warehouse_id != request.preferred_warehouse_id, -w.composite_score)
            )

        for score in warehouse_scores:
            if remaining <= 0:
                break
            if score.available <= 0:
                continue

            allocate_qty = min(remaining, score.available)
            if not request.allow_split and allocate_qty < remaining:
                continue

            reservation = await self._create_reservation(
                request, score.warehouse_id, allocate_qty
            )
            await self._apply_allocation(score.warehouse_id, request.sku_id, allocate_qty)

            result.allocations.append((score.warehouse_id, allocate_qty))
            result.reservation_ids.append(reservation.id)
            result.total_allocated += allocate_qty
            remaining -= allocate_qty

        result.backorder_quantity = remaining

        if result.total_allocated == 0:
            available_total = sum(s.available for s in warehouse_scores)
            raise InsufficientInventoryError(
                request.sku_id, request.quantity, available_total
            )

        logger.info(
            "allocation_completed",
            order_id=str(request.order_id),
            allocated=result.total_allocated,
            backorder=result.backorder_quantity,
        )
        return result

    async def release_reservations(self, order_id: uuid.UUID) -> int:
        reservations = await self.reservation_repo.get_active_for_order(order_id)
        released = 0
        for reservation in reservations:
            await self._release_single_reservation(reservation)
            released += reservation.quantity
        return released

    async def confirm_allocation(
        self, reservation_id: uuid.UUID
    ) -> None:
        reservation = await self.reservation_repo.get_by_id_or_raise(reservation_id)
        if reservation.status != "active":
            raise ReservationExpiredError(
                f"Reservation {reservation_id} is not active: {reservation.status}"
            )
        if reservation.expires_at < datetime.now(timezone.utc):
            await self._release_single_reservation(reservation)
            raise ReservationExpiredError(f"Reservation {reservation_id} has expired")

        reservation.status = "confirmed"
        balance = await self.balance_repo.get_balance(
            reservation.warehouse_id, reservation.sku_id
        )
        if balance:
            balance.reserved -= reservation.quantity
            balance.allocated += reservation.quantity
            balance.version += 1

    async def _rank_warehouses(self, request: AllocationRequest) -> list[WarehouseScore]:
        warehouses = await self.warehouse_repo.list_active()
        scores: list[WarehouseScore] = []

        for warehouse in warehouses:
            available = await self.balance_repo.get_aggregated_available(
                warehouse.id, request.sku_id
            )
            priority_score = 1.0 / max(warehouse.fulfillment_priority, 1)
            scores.append(
                WarehouseScore(
                    warehouse_id=warehouse.id,
                    available=available,
                    distance_score=0.5,
                    cost_score=0.5,
                    priority_score=priority_score,
                )
            )

        scores.sort(key=lambda s: s.composite_score, reverse=True)
        return scores

    async def _create_reservation(
        self,
        request: AllocationRequest,
        warehouse_id: uuid.UUID,
        quantity: int,
    ) -> InventoryReservation:
        reservation = InventoryReservation(
            order_id=request.order_id,
            order_line_id=request.order_line_id,
            warehouse_id=warehouse_id,
            sku_id=request.sku_id,
            quantity=quantity,
            status="active",
            expires_at=datetime.now(timezone.utc)
            + timedelta(minutes=self.RESERVATION_TTL_MINUTES),
            correlation_id=str(get_correlation_id()),
        )
        return await self.reservation_repo.add(reservation)

    async def _apply_allocation(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID, quantity: int
    ) -> InventoryBalance:
        balance = await self.balance_repo.get_balance(warehouse_id, sku_id)
        if balance is None:
            raise AllocationError(
                f"No inventory balance for warehouse {warehouse_id}, sku {sku_id}"
            )
        if balance.available < quantity:
            raise InsufficientInventoryError(
                sku_id, quantity, balance.available, warehouse_id
            )
        balance.reserved += quantity
        balance.version += 1
        return balance

    async def _release_single_reservation(
        self, reservation: InventoryReservation
    ) -> None:
        balance = await self.balance_repo.get_balance(
            reservation.warehouse_id, reservation.sku_id
        )
        if balance:
            if reservation.status == "confirmed":
                balance.allocated = max(0, balance.allocated - reservation.quantity)
            else:
                balance.reserved = max(0, balance.reserved - reservation.quantity)
            balance.version += 1
        reservation.status = "released"
