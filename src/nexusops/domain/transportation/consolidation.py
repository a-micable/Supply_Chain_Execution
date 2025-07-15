"""Shipment consolidation engine."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.config.settings import get_settings
from nexusops.core.logging import get_logger
from nexusops.repositories.transportation import ShipmentRepository

logger = get_logger(__name__)


@dataclass
class ConsolidationGroup:
    group_id: uuid.UUID
    warehouse_id: uuid.UUID
    shipment_ids: list[uuid.UUID] = field(default_factory=list)
    total_weight_kg: Decimal = Decimal("0")
    destination_region: str = ""
    estimated_savings: Decimal = Decimal("0")


@dataclass
class ConsolidationResult:
    groups: list[ConsolidationGroup]
    shipments_consolidated: int
    total_savings: Decimal


class ConsolidationEngine:
    """Groups compatible shipments for consolidated delivery."""

    MAX_GROUP_WEIGHT_KG = Decimal("500")
    MAX_GROUP_SIZE = 10

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.shipment_repo = ShipmentRepository(session)
        self.settings = get_settings()

    async def consolidate_window(
        self, warehouse_id: uuid.UUID, window_start: datetime | None = None
    ) -> ConsolidationResult:
        now = datetime.now(timezone.utc)
        start = window_start or now
        end = start + timedelta(hours=self.settings.consolidation_window_hours)

        candidates = await self.shipment_repo.list_consolidation_candidates(
            warehouse_id, start, end
        )

        region_groups: dict[str, list] = {}
        for shipment in candidates:
            region = self._extract_region(shipment.destination_address)
            region_groups.setdefault(region, []).append(shipment)

        groups: list[ConsolidationGroup] = []
        total_consolidated = 0
        total_savings = Decimal("0")

        for region, shipments in region_groups.items():
            current_group: ConsolidationGroup | None = None

            for shipment in sorted(shipments, key=lambda s: s.total_weight_kg or Decimal("0")):
                weight = shipment.total_weight_kg or Decimal("10")

                if (
                    current_group is None
                    or len(current_group.shipment_ids) >= self.MAX_GROUP_SIZE
                    or current_group.total_weight_kg + weight > self.MAX_GROUP_WEIGHT_KG
                ):
                    if current_group and current_group.shipment_ids:
                        groups.append(current_group)
                    current_group = ConsolidationGroup(
                        group_id=uuid.uuid4(),
                        warehouse_id=warehouse_id,
                        destination_region=region,
                    )

                current_group.shipment_ids.append(shipment.id)
                current_group.total_weight_kg += weight
                shipment.consolidation_group_id = current_group.group_id
                total_consolidated += 1

            if current_group and current_group.shipment_ids:
                savings = Decimal(str(len(current_group.shipment_ids) * 5))
                current_group.estimated_savings = savings
                total_savings += savings
                groups.append(current_group)

        logger.info(
            "consolidation_completed",
            warehouse_id=str(warehouse_id),
            groups=len(groups),
            consolidated=total_consolidated,
        )
        return ConsolidationResult(
            groups=groups,
            shipments_consolidated=total_consolidated,
            total_savings=total_savings,
        )

    def _extract_region(self, address: dict) -> str:
        postal = address.get("postal_code", "")[:3]
        state = address.get("state", "UNKNOWN")
        return f"{state}-{postal}"
