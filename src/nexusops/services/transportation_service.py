"""Transportation management service."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.domain.transportation.carrier_assignment import CarrierAssigner, CarrierAssignment
from nexusops.domain.transportation.consolidation import ConsolidationEngine, ConsolidationResult
from nexusops.domain.transportation.routing import RoutePlanner, RoutePlanningResult
from nexusops.repositories.transportation import ShipmentRepository
from nexusops.services.audit_service import AuditService


class TransportationService:
    """Orchestrates routing, carrier assignment, and consolidation."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.shipment_repo = ShipmentRepository(session)
        self.route_planner = RoutePlanner(session)
        self.carrier_assigner = CarrierAssigner(session)
        self.consolidation_engine = ConsolidationEngine(session)
        self.audit = AuditService(session)

    async def plan_routes(self, shipment_id: uuid.UUID) -> RoutePlanningResult:
        result = await self.route_planner.plan_routes(shipment_id)
        await self.audit.record(
            entity_type="shipment",
            entity_id=shipment_id,
            action="routes_planned",
            after_state={"option_count": len(result.options)},
        )
        return result

    async def assign_carrier(self, shipment_id: uuid.UUID) -> CarrierAssignment:
        return await self.carrier_assigner.assign_carrier(shipment_id)

    async def consolidate_shipments(
        self, warehouse_id: uuid.UUID, window_start: datetime | None = None
    ) -> ConsolidationResult:
        return await self.consolidation_engine.consolidate_window(warehouse_id, window_start)
