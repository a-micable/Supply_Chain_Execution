"""Putaway location optimization for received inventory."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.logging import get_logger
from nexusops.core.types import WarehouseTaskType
from nexusops.models.warehouse import WarehouseLocation, WarehouseTask
from nexusops.repositories.warehouse import WarehouseLocationRepository, WarehouseTaskRepository

logger = get_logger(__name__)


@dataclass
class PutawayRecommendation:
    sku_id: uuid.UUID
    quantity: int
    source_location_id: uuid.UUID | None
    target_location_id: uuid.UUID
    target_zone: str
    distance_score: float
    capacity_remaining: int
    reason: str


@dataclass
class PutawayPlan:
    warehouse_id: uuid.UUID
    recommendations: list[PutawayRecommendation]
    task_ids: list[uuid.UUID]


class PutawayOptimizer:
    """Determines optimal storage locations for received inventory."""

    ZONE_PRIORITY = {"A": 1, "B": 2, "C": 3, "D": 4, "STAGING": 0}
    VELOCITY_ZONE_MAP = {"high": "A", "medium": "B", "low": "C"}

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.location_repo = WarehouseLocationRepository(session)
        self.task_repo = WarehouseTaskRepository(session)

    async def plan_putaway(
        self,
        warehouse_id: uuid.UUID,
        sku_id: uuid.UUID,
        quantity: int,
        velocity_class: str = "medium",
        source_location_id: uuid.UUID | None = None,
    ) -> PutawayPlan:
        preferred_zone = self.VELOCITY_ZONE_MAP.get(velocity_class, "B")
        locations = await self.location_repo.list_pickable(warehouse_id, preferred_zone)

        if not locations:
            locations = await self.location_repo.list_pickable(warehouse_id)

        recommendations: list[PutawayRecommendation] = []
        remaining = quantity

        for loc in sorted(locations, key=lambda l: self.ZONE_PRIORITY.get(l.zone, 99)):
            if remaining <= 0:
                break
            capacity = loc.capacity_units or 100
            assign_qty = min(remaining, capacity)
            if assign_qty <= 0:
                continue

            recommendations.append(
                PutawayRecommendation(
                    sku_id=sku_id,
                    quantity=assign_qty,
                    source_location_id=source_location_id,
                    target_location_id=loc.id,
                    target_zone=loc.zone,
                    distance_score=self._distance_score(loc),
                    capacity_remaining=capacity - assign_qty,
                    reason=f"velocity_{velocity_class}_zone_{loc.zone}",
                )
            )
            remaining -= assign_qty

        task_ids = await self._create_putaway_tasks(warehouse_id, recommendations)
        logger.info(
            "putaway_planned",
            warehouse_id=str(warehouse_id),
            locations=len(recommendations),
            remaining=remaining,
        )
        return PutawayPlan(
            warehouse_id=warehouse_id,
            recommendations=recommendations,
            task_ids=task_ids,
        )

    async def execute_putaway(self, task_id: uuid.UUID, operator_id: str) -> None:
        task = await self.task_repo.get_by_id_or_raise(task_id)
        if task.task_type != WarehouseTaskType.PUTAWAY:
            raise ValueError(f"Task {task_id} is not a putaway task")
        task.status = "completed"
        task.assigned_to = operator_id

    def _distance_score(self, location: WarehouseLocation) -> float:
        zone_score = self.ZONE_PRIORITY.get(location.zone, 5)
        aisle_penalty = int(location.aisle or "0") * 0.1 if location.aisle else 0
        return zone_score + aisle_penalty

    async def _create_putaway_tasks(
        self, warehouse_id: uuid.UUID, recommendations: list[PutawayRecommendation]
    ) -> list[uuid.UUID]:
        task_ids: list[uuid.UUID] = []
        for rec in recommendations:
            task = WarehouseTask(
                warehouse_id=warehouse_id,
                task_type=WarehouseTaskType.PUTAWAY,
                status="pending",
                source_location_id=rec.source_location_id,
                target_location_id=rec.target_location_id,
                sku_id=rec.sku_id,
                quantity=rec.quantity,
                task_data={"reason": rec.reason, "zone": rec.target_zone},
            )
            created = await self.task_repo.add(task)
            task_ids.append(created.id)
        return task_ids

    async def suggest_consolidation(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID
    ) -> list[PutawayRecommendation]:
        locations = await self.location_repo.list_pickable(warehouse_id)
        partial_locations = []
        for loc in locations:
            if loc.capacity_units and loc.capacity_units < 50:
                partial_locations.append(loc)
        return [
            PutawayRecommendation(
                sku_id=sku_id,
                quantity=0,
                source_location_id=loc.id,
                target_location_id=loc.id,
                target_zone=loc.zone,
                distance_score=0,
                capacity_remaining=loc.capacity_units or 0,
                reason="consolidation_candidate",
            )
            for loc in partial_locations[:5]
        ]
