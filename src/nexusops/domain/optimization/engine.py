"""Optimization engine for cost, placement, and capacity planning."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.exceptions import OptimizationInfeasibleError
from nexusops.core.logging import get_logger
from nexusops.models.audit import PlanningDecision
from nexusops.repositories.audit import PlanningDecisionRepository
from nexusops.repositories.inventory import InventoryBalanceRepository
from nexusops.repositories.warehouse import WarehouseRepository

logger = get_logger(__name__)


@dataclass
class OptimizationInput:
    reference_type: str
    reference_id: uuid.UUID
    objective: str
    constraints: dict[str, Any] = field(default_factory=dict)
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class OptimizationResult:
    run_id: uuid.UUID
    objective_value: float
    solution: dict[str, Any]
    alternatives_evaluated: int
    execution_time_ms: int
    is_feasible: bool
    metadata: dict[str, Any] = field(default_factory=dict)


class OptimizationEngine:
    """Unified optimization engine for supply chain decisions."""

    OBJECTIVES = ("minimize_cost", "minimize_transit", "maximize_fill_rate", "balance_inventory")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.decision_repo = PlanningDecisionRepository(session)
        self.balance_repo = InventoryBalanceRepository(session)
        self.warehouse_repo = WarehouseRepository(session)

    async def optimize(self, input_data: OptimizationInput) -> OptimizationResult:
        import time
        start = time.monotonic()
        run_id = uuid.uuid4()

        if input_data.objective == "minimize_cost":
            result = await self._optimize_cost(input_data)
        elif input_data.objective == "maximize_fill_rate":
            result = await self._optimize_fill_rate(input_data)
        elif input_data.objective == "balance_inventory":
            result = await self._optimize_inventory_placement(input_data)
        elif input_data.objective == "minimize_transit":
            result = await self._optimize_transportation(input_data)
        else:
            raise OptimizationInfeasibleError(f"Unknown objective: {input_data.objective}")

        elapsed_ms = int((time.monotonic() - start) * 1000)
        result.run_id = run_id
        result.execution_time_ms = elapsed_ms

        await self._record_decision(input_data, result)
        logger.info(
            "optimization_completed",
            run_id=str(run_id),
            objective=input_data.objective,
            feasible=result.is_feasible,
            elapsed_ms=elapsed_ms,
        )
        return result

    async def _optimize_cost(self, input_data: OptimizationInput) -> OptimizationResult:
        warehouses = await self.warehouse_repo.list_active()
        costs = []
        for wh in warehouses:
            priority_factor = wh.fulfillment_priority
            costs.append({"warehouse_id": str(wh.id), "cost": priority_factor * 10 + 50})

        if not costs:
            raise OptimizationInfeasibleError("No warehouses available for cost optimization")

        best = min(costs, key=lambda c: c["cost"])
        return OptimizationResult(
            run_id=uuid.uuid4(),
            objective_value=float(best["cost"]),
            solution={"selected_warehouse": best["warehouse_id"]},
            alternatives_evaluated=len(costs),
            execution_time_ms=0,
            is_feasible=True,
        )

    async def _optimize_fill_rate(self, input_data: OptimizationInput) -> OptimizationResult:
        sku_id = input_data.parameters.get("sku_id")
        if not sku_id:
            raise OptimizationInfeasibleError("sku_id required for fill rate optimization")

        visibility = await self.balance_repo.get_network_visibility(uuid.UUID(str(sku_id)))
        total_available = sum(v[3] for v in visibility)
        demand = input_data.parameters.get("demand", total_available)

        fill_rate = min(1.0, total_available / max(demand, 1))
        allocation = {}
        remaining = demand
        for wh_id, _, _, available in sorted(visibility, key=lambda x: -x[3]):
            if remaining <= 0:
                break
            alloc = min(remaining, available)
            allocation[str(wh_id)] = alloc
            remaining -= alloc

        return OptimizationResult(
            run_id=uuid.uuid4(),
            objective_value=fill_rate,
            solution={"allocation": allocation, "fill_rate": fill_rate},
            alternatives_evaluated=len(visibility),
            execution_time_ms=0,
            is_feasible=fill_rate > 0,
        )

    async def _optimize_inventory_placement(
        self, input_data: OptimizationInput
    ) -> OptimizationResult:
        warehouses = await self.warehouse_repo.list_active()
        n_wh = len(warehouses)
        if n_wh == 0:
            raise OptimizationInfeasibleError("No warehouses for placement optimization")

        total_inventory = input_data.parameters.get("total_units", 1000)
        demands = np.random.default_rng(42).uniform(0.5, 2.0, n_wh)
        demands = demands / demands.sum()

        placement = {}
        for i, wh in enumerate(warehouses):
            units = int(total_inventory * demands[i])
            placement[str(wh.id)] = units

        return OptimizationResult(
            run_id=uuid.uuid4(),
            objective_value=float(np.std(list(placement.values()))),
            solution={"placement": placement},
            alternatives_evaluated=n_wh,
            execution_time_ms=0,
            is_feasible=True,
            metadata={"algorithm": "demand_weighted_distribution"},
        )

    async def _optimize_transportation(
        self, input_data: OptimizationInput
    ) -> OptimizationResult:
        stops = input_data.parameters.get("stops", [])
        if len(stops) < 2:
            return OptimizationResult(
                run_id=uuid.uuid4(),
                objective_value=0,
                solution={"route": stops},
                alternatives_evaluated=1,
                execution_time_ms=0,
                is_feasible=True,
            )

        n = len(stops)
        dist_matrix = np.zeros((n, n))
        for i in range(n):
            for j in range(i + 1, n):
                d = abs(stops[i].get("lat", 0) - stops[j].get("lat", 0)) + abs(
                    stops[i].get("lng", 0) - stops[j].get("lng", 0)
                )
                dist_matrix[i][j] = d
                dist_matrix[j][i] = d

        return OptimizationResult(
            run_id=uuid.uuid4(),
            objective_value=float(dist_matrix.sum()),
            solution={"distance_matrix": dist_matrix.tolist(), "stop_count": n},
            alternatives_evaluated=n * (n - 1) // 2,
            execution_time_ms=0,
            is_feasible=True,
        )

    async def _record_decision(
        self, input_data: OptimizationInput, result: OptimizationResult
    ) -> None:
        decision = PlanningDecision(
            decision_type=f"optimization_{input_data.objective}",
            reference_type=input_data.reference_type,
            reference_id=input_data.reference_id,
            algorithm="unified_optimizer",
            algorithm_version="2.1",
            input_snapshot={
                "objective": input_data.objective,
                "constraints": input_data.constraints,
                "parameters": input_data.parameters,
            },
            output_snapshot=result.solution,
            score=result.objective_value,
            alternatives_considered=result.alternatives_evaluated,
            execution_time_ms=result.execution_time_ms,
        )
        await self.decision_repo.add(decision)
