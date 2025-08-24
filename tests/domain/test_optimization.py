"""Optimization engine tests."""

from __future__ import annotations

import uuid

import pytest

from nexusops.core.exceptions import OptimizationInfeasibleError
from nexusops.domain.optimization.engine import OptimizationEngine, OptimizationInput


@pytest.mark.asyncio
async def test_cost_optimization(session, sample_warehouse):
    engine = OptimizationEngine(session)
    result = await engine.optimize(
        OptimizationInput(
            reference_type="order",
            reference_id=uuid.uuid4(),
            objective="minimize_cost",
        )
    )
    assert result.is_feasible
    assert "selected_warehouse" in result.solution


@pytest.mark.asyncio
async def test_fill_rate_optimization(session, sample_warehouse, sample_sku, stocked_balance):
    engine = OptimizationEngine(session)
    result = await engine.optimize(
        OptimizationInput(
            reference_type="order",
            reference_id=uuid.uuid4(),
            objective="maximize_fill_rate",
            parameters={"sku_id": str(sample_sku.id), "demand": 200},
        )
    )
    assert result.is_feasible
    assert "fill_rate" in result.solution


@pytest.mark.asyncio
async def test_unknown_objective_raises(session):
    engine = OptimizationEngine(session)
    with pytest.raises(OptimizationInfeasibleError):
        await engine.optimize(
            OptimizationInput(
                reference_type="test",
                reference_id=uuid.uuid4(),
                objective="invalid_objective",
            )
        )


@pytest.mark.asyncio
async def test_inventory_placement_optimization(session, sample_warehouse):
    engine = OptimizationEngine(session)
    result = await engine.optimize(
        OptimizationInput(
            reference_type="network",
            reference_id=uuid.uuid4(),
            objective="balance_inventory",
            parameters={"total_units": 5000},
        )
    )
    assert result.is_feasible
    assert "placement" in result.solution
