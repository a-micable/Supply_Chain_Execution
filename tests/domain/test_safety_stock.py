"""Safety stock calculation tests."""

from __future__ import annotations

import pytest
from decimal import Decimal

from nexusops.domain.inventory.safety_stock import SafetyStockCalculator
from nexusops.models.inventory import InventoryForecast, SafetyStockPolicy


@pytest.mark.asyncio
async def test_calculate_safety_stock(session, sample_warehouse, sample_sku):
    calc = SafetyStockCalculator(session)
    result = await calc.calculate(
        sample_warehouse.id, sample_sku.id, service_level=0.95, lead_time_days=7
    )
    assert result.safety_stock_qty >= 0
    assert result.reorder_point >= result.safety_stock_qty
    assert result.service_level == 0.95


@pytest.mark.asyncio
async def test_safety_stock_with_forecast_history(session, sample_warehouse, sample_sku):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    for i in range(30):
        forecast = InventoryForecast(
            warehouse_id=sample_warehouse.id,
            sku_id=sample_sku.id,
            forecast_date=now - timedelta(days=30 - i),
            predicted_demand=10 + (i % 5),
        )
        session.add(forecast)
    await session.flush()

    calc = SafetyStockCalculator(session)
    result = await calc.calculate(sample_warehouse.id, sample_sku.id)
    assert result.avg_daily_demand > 0
    assert result.demand_std_dev >= 0


@pytest.mark.asyncio
async def test_persist_safety_stock_policy(session, sample_warehouse, sample_sku):
    calc = SafetyStockCalculator(session)
    await calc.calculate(sample_warehouse.id, sample_sku.id)

    policy = await calc.policy_repo.get_policy(sample_warehouse.id, sample_sku.id)
    assert policy is not None
    assert policy.safety_stock_qty >= 0
