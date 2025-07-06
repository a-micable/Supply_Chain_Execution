"""Cross-warehouse inventory reconciliation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.exceptions import ReconciliationError
from nexusops.core.logging import get_logger
from nexusops.repositories.inventory import (
    InventoryBalanceRepository,
    InventoryReservationRepository,
)

logger = get_logger(__name__)


@dataclass
class ReconciliationDiscrepancy:
    warehouse_id: uuid.UUID
    sku_id: uuid.UUID
    balance_on_hand: int
    computed_available: int
    reserved_in_reservations: int
    reserved_in_balance: int
    allocated_in_balance: int
    discrepancy_type: str
    severity: str


@dataclass
class ReconciliationReport:
    discrepancies: list[ReconciliationDiscrepancy] = field(default_factory=list)
    warehouses_checked: int = 0
    skus_checked: int = 0
    is_balanced: bool = True

    def add_discrepancy(self, d: ReconciliationDiscrepancy) -> None:
        self.discrepancies.append(d)
        self.is_balanced = False


class InventoryReconciler:
    """Detects and reports inventory synchronization inconsistencies."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.balance_repo = InventoryBalanceRepository(session)
        self.reservation_repo = InventoryReservationRepository(session)

    async def reconcile_warehouse(self, warehouse_id: uuid.UUID) -> ReconciliationReport:
        report = ReconciliationReport()
        balances = await self.balance_repo.list_by_warehouse(warehouse_id)
        report.warehouses_checked = 1

        sku_ids = {b.sku_id for b in balances}
        report.skus_checked = len(sku_ids)

        for sku_id in sku_ids:
            sku_balances = [b for b in balances if b.sku_id == sku_id]
            total_on_hand = sum(b.on_hand for b in sku_balances)
            total_reserved = sum(b.reserved for b in sku_balances)
            total_allocated = sum(b.allocated for b in sku_balances)

            reservation_total = await self.reservation_repo.sum_reserved_quantity(
                warehouse_id, sku_id
            )

            if reservation_total != total_reserved:
                report.add_discrepancy(
                    ReconciliationDiscrepancy(
                        warehouse_id=warehouse_id,
                        sku_id=sku_id,
                        balance_on_hand=total_on_hand,
                        computed_available=total_on_hand - total_reserved - total_allocated,
                        reserved_in_reservations=reservation_total,
                        reserved_in_balance=total_reserved,
                        allocated_in_balance=total_allocated,
                        discrepancy_type="reservation_mismatch",
                        severity="high" if abs(reservation_total - total_reserved) > 10 else "medium",
                    )
                )

            for balance in sku_balances:
                computed_available = (
                    balance.on_hand
                    - balance.reserved
                    - balance.allocated
                    - balance.damaged
                    - balance.quarantine
                )
                if computed_available < 0:
                    report.add_discrepancy(
                        ReconciliationDiscrepancy(
                            warehouse_id=warehouse_id,
                            sku_id=sku_id,
                            balance_on_hand=balance.on_hand,
                            computed_available=computed_available,
                            reserved_in_reservations=reservation_total,
                            reserved_in_balance=balance.reserved,
                            allocated_in_balance=balance.allocated,
                            discrepancy_type="negative_available",
                            severity="critical",
                        )
                    )

        logger.info(
            "reconciliation_completed",
            warehouse_id=str(warehouse_id),
            is_balanced=report.is_balanced,
            discrepancy_count=len(report.discrepancies),
        )
        return report

    async def reconcile_network(self, warehouse_ids: list[uuid.UUID]) -> ReconciliationReport:
        combined = ReconciliationReport()
        for wh_id in warehouse_ids:
            report = await self.reconcile_warehouse(wh_id)
            combined.discrepancies.extend(report.discrepancies)
            combined.warehouses_checked += report.warehouses_checked
            combined.skus_checked += report.skus_checked
            if not report.is_balanced:
                combined.is_balanced = False
        return combined

    async def auto_repair_reservation_mismatch(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID
    ) -> bool:
        report = await self.reconcile_warehouse(warehouse_id)
        mismatches = [
            d
            for d in report.discrepancies
            if d.sku_id == sku_id and d.discrepancy_type == "reservation_mismatch"
        ]
        if not mismatches:
            return False

        discrepancy = mismatches[0]
        balance = await self.balance_repo.get_balance(warehouse_id, sku_id)
        if balance is None:
            raise ReconciliationError(
                f"No balance found for warehouse {warehouse_id}, sku {sku_id}"
            )

        balance.reserved = discrepancy.reserved_in_reservations
        balance.version += 1
        logger.info(
            "reservation_mismatch_repaired",
            warehouse_id=str(warehouse_id),
            sku_id=str(sku_id),
            new_reserved=balance.reserved,
        )
        return True
