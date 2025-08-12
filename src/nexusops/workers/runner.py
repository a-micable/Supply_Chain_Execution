"""Background worker system for event processing and scheduled jobs."""

from __future__ import annotations

import asyncio
import signal
from datetime import datetime, timezone

from nexusops.config.settings import get_settings
from nexusops.core.logging import configure_logging, get_logger
from nexusops.db.session import get_session_factory
from nexusops.domain.inventory.allocation import AllocationEngine
from nexusops.domain.inventory.forecasting import ForecastEngine
from nexusops.domain.inventory.safety_stock import SafetyStockCalculator
from nexusops.domain.procurement.replenishment import ReplenishmentPlanner
from nexusops.domain.procurement.vendor_performance import VendorPerformanceTracker
from nexusops.events.bus import EventBus
from nexusops.repositories.events import DomainEventRepository
from nexusops.repositories.inventory import InventoryReservationRepository
from nexusops.repositories.warehouse import WarehouseRepository

logger = get_logger(__name__)


class WorkerRunner:
    """Polls and processes pending domain events and scheduled tasks."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.running = True
        self.session_factory = get_session_factory()

    async def run(self) -> None:
        configure_logging()
        logger.info("worker_started")

        loop = asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown)

        while self.running:
            try:
                await self._process_cycle()
            except Exception as exc:
                logger.error("worker_cycle_error", error=str(exc))
            await asyncio.sleep(self.settings.worker_poll_interval_ms / 1000)

    def _shutdown(self) -> None:
        logger.info("worker_shutdown_requested")
        self.running = False

    async def _process_cycle(self) -> None:
        async with self.session_factory() as session:
            async with session.begin():
                event_bus = EventBus(session)
                processed = await event_bus.process_pending(self.settings.worker_batch_size)
                if processed:
                    logger.info("events_processed", count=processed)

                await self._expire_reservations(session)
                await self._run_scheduled_jobs(session)

    async def _expire_reservations(self, session) -> None:
        reservation_repo = InventoryReservationRepository(session)
        allocation_engine = AllocationEngine(session)
        expired = await reservation_repo.get_expired()
        for reservation in expired:
            await allocation_engine._release_single_reservation(reservation)
        if expired:
            logger.info("reservations_expired", count=len(expired))

    async def _run_scheduled_jobs(self, session) -> None:
        now = datetime.now(timezone.utc)
        if now.minute == 0:
            tracker = VendorPerformanceTracker(session)
            updated = await tracker.update_supplier_scores()
            if updated:
                logger.info("vendor_scores_updated", count=updated)


async def main() -> None:
    runner = WorkerRunner()
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
