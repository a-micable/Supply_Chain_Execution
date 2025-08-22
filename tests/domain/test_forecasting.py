"""Forecasting engine tests."""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from nexusops.domain.inventory.forecasting import ForecastEngine, DRIFT_THRESHOLD
from nexusops.models.inventory import InventoryForecast


@pytest.mark.asyncio
async def test_generate_forecast(session, sample_warehouse, sample_sku):
    engine = ForecastEngine(session, horizon_days=30)
    series = await engine.generate_forecast(
        sample_warehouse.id, sample_sku.id, historical_demand=[10, 12, 8, 15, 11, 9, 13]
    )
    assert len(series.points) == 30
    assert all(p.predicted_demand >= 0 for p in series.points)
    assert series.model_version == "v2.1"


@pytest.mark.asyncio
async def test_forecast_drift_detection(session, sample_warehouse, sample_sku):
    now = datetime.now(timezone.utc)
    old_forecast = InventoryForecast(
        warehouse_id=sample_warehouse.id,
        sku_id=sample_sku.id,
        forecast_date=now - timedelta(days=1),
        predicted_demand=10,
    )
    session.add(old_forecast)
    await session.flush()

    engine = ForecastEngine(session, horizon_days=7)
    series = await engine.generate_forecast(
        sample_warehouse.id,
        sample_sku.id,
        historical_demand=[100] * 30,
    )
    assert series.drift_score > 0


@pytest.mark.asyncio
async def test_seasonality_computation():
    engine = ForecastEngine(None)  # type: ignore[arg-type]
    history = [10, 12, 8, 15, 11, 9, 13] * 4
    seasonality = engine._compute_seasonality(history)
    assert len(seasonality) == 7
    assert all(s > 0 for s in seasonality)
