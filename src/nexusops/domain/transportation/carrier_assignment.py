"""Carrier assignment optimization."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.logging import get_logger
from nexusops.models.transportation import Carrier
from nexusops.repositories.transportation import CarrierRepository, ShipmentRepository

logger = get_logger(__name__)


@dataclass
class CarrierAssignment:
    shipment_id: uuid.UUID
    carrier_id: uuid.UUID
    carrier_code: str
    estimated_cost: Decimal
    estimated_transit_days: int
    score: float
    reason: str


class CarrierAssigner:
    """Assigns optimal carriers based on cost, performance, and capacity."""

    WEIGHT_COST = 0.4
    WEIGHT_PERFORMANCE = 0.35
    WEIGHT_CAPACITY = 0.25

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.carrier_repo = CarrierRepository(session)
        self.shipment_repo = ShipmentRepository(session)

    async def assign_carrier(self, shipment_id: uuid.UUID) -> CarrierAssignment:
        shipment = await self.shipment_repo.get_by_id_or_raise(shipment_id)
        carriers = await self.carrier_repo.list_active()

        if not carriers:
            raise ValueError("No active carriers available")

        weight = shipment.total_weight_kg or Decimal("10")
        scored: list[tuple[Carrier, float, Decimal, int]] = []

        for carrier in carriers:
            if carrier.max_weight_kg and weight > carrier.max_weight_kg:
                continue

            cost = self._estimate_cost(carrier, weight)
            transit_days = self._estimate_transit(carrier)
            score = self._score_carrier(carrier, cost, weight)
            scored.append((carrier, score, cost, transit_days))

        if not scored:
            carrier = carriers[0]
            return CarrierAssignment(
                shipment_id=shipment_id,
                carrier_id=carrier.id,
                carrier_code=carrier.carrier_code,
                estimated_cost=self._estimate_cost(carrier, weight),
                estimated_transit_days=self._estimate_transit(carrier),
                score=0.5,
                reason="fallback_no_capacity_match",
            )

        scored.sort(key=lambda x: x[1], reverse=True)
        best_carrier, best_score, best_cost, best_transit = scored[0]

        shipment.carrier_id = best_carrier.id
        logger.info(
            "carrier_assigned",
            shipment_id=str(shipment_id),
            carrier=best_carrier.carrier_code,
            score=best_score,
        )

        return CarrierAssignment(
            shipment_id=shipment_id,
            carrier_id=best_carrier.id,
            carrier_code=best_carrier.carrier_code,
            estimated_cost=best_cost,
            estimated_transit_days=best_transit,
            score=best_score,
            reason="optimization_score",
        )

    def _estimate_cost(self, carrier: Carrier, weight: Decimal) -> Decimal:
        rate = carrier.cost_per_kg or Decimal("1.00")
        return rate * weight + Decimal("15.00")

    def _estimate_transit(self, carrier: Carrier) -> int:
        performance = float(carrier.on_time_rate or 0.85)
        base_days = 3
        return max(1, int(base_days / performance))

    def _score_carrier(self, carrier: Carrier, cost: Decimal, weight: Decimal) -> float:
        max_cost = Decimal("500")
        cost_score = 1.0 - min(float(cost / max_cost), 1.0)
        perf_score = float(carrier.on_time_rate or 0.8)
        capacity = carrier.max_weight_kg or Decimal("1000")
        capacity_score = min(float(weight / capacity), 1.0)
        return (
            cost_score * self.WEIGHT_COST
            + perf_score * self.WEIGHT_PERFORMANCE
            + (1 - capacity_score) * self.WEIGHT_CAPACITY
        )
