"""Reservation lifecycle management and expiry processing."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.exceptions import ReservationExpiredError
from nexusops.core.logging import get_logger
from nexusops.domain.inventory.allocation import AllocationEngine
from nexusops.repositories.inventory import InventoryReservationRepository

logger = get_logger(__name__)


@dataclass
class ReservationSummary:
    reservation_id: uuid.UUID
    order_id: uuid.UUID
    warehouse_id: uuid.UUID
    sku_id: uuid.UUID
    quantity: int
    status: str
    expires_at: datetime
    seconds_remaining: int
    is_expired: bool


@dataclass
class ExpiryProcessResult:
    processed: int
    released: int
    errors: list[str] = field(default_factory=list)


class ReservationManager:
    """Manages reservation lifecycle including extension and bulk expiry."""

    DEFAULT_TTL_MINUTES = 30
    MAX_EXTENSION_MINUTES = 60

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.reservation_repo = InventoryReservationRepository(session)
        self.allocation_engine = AllocationEngine(session)

    async def get_order_reservations(self, order_id: uuid.UUID) -> list[ReservationSummary]:
        reservations = await self.reservation_repo.get_active_for_order(order_id)
        now = datetime.now(timezone.utc)

        def _aware(dt: datetime) -> datetime:
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        return [
            ReservationSummary(
                reservation_id=r.id,
                order_id=r.order_id,
                warehouse_id=r.warehouse_id,
                sku_id=r.sku_id,
                quantity=r.quantity,
                status=r.status,
                expires_at=_aware(r.expires_at),
                seconds_remaining=max(0, int((_aware(r.expires_at) - now).total_seconds())),
                is_expired=_aware(r.expires_at) < now,
            )
            for r in reservations
        ]

    async def extend_reservation(
        self, reservation_id: uuid.UUID, additional_minutes: int = 15
    ) -> ReservationSummary:
        reservation = await self.reservation_repo.get_by_id_or_raise(reservation_id)
        if reservation.status != "active":
            raise ReservationExpiredError(f"Reservation {reservation_id} is not active")

        extension = min(additional_minutes, self.MAX_EXTENSION_MINUTES)
        reservation.expires_at = reservation.expires_at + timedelta(minutes=extension)

        summaries = await self.get_order_reservations(reservation.order_id)
        return next(s for s in summaries if s.reservation_id == reservation_id)

    async def process_expired(self) -> ExpiryProcessResult:
        result = ExpiryProcessResult(processed=0, released=0)
        expired = await self.reservation_repo.get_expired()

        for reservation in expired:
            result.processed += 1
            try:
                await self.allocation_engine._release_single_reservation(reservation)
                result.released += reservation.quantity
            except Exception as exc:
                result.errors.append(f"Reservation {reservation.id}: {exc}")

        if result.processed:
            logger.info(
                "expired_reservations_processed",
                processed=result.processed,
                released=result.released,
            )
        return result

    async def confirm_all_for_order(self, order_id: uuid.UUID) -> int:
        reservations = await self.reservation_repo.get_active_for_order(order_id)
        confirmed = 0
        for reservation in reservations:
            try:
                await self.allocation_engine.confirm_allocation(reservation.id)
                confirmed += 1
            except ReservationExpiredError:
                logger.warning(
                    "reservation_confirm_failed_expired",
                    reservation_id=str(reservation.id),
                )
        return confirmed

    async def total_reserved_by_sku(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID
    ) -> int:
        return await self.reservation_repo.sum_reserved_quantity(warehouse_id, sku_id)

    async def find_orders_with_expiring_soon(
        self, within_minutes: int = 5
    ) -> list[uuid.UUID]:
        cutoff = datetime.now(timezone.utc) + timedelta(minutes=within_minutes)
        from sqlalchemy import select
        from nexusops.models.inventory import InventoryReservation

        stmt = select(InventoryReservation.order_id).where(
            InventoryReservation.status == "active",
            InventoryReservation.expires_at <= cutoff,
            InventoryReservation.expires_at > datetime.now(timezone.utc),
        ).distinct()
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
