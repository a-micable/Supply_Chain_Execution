"""Inventory forecasting with drift detection."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.exceptions import ForecastDriftError
from nexusops.core.logging import get_logger
from nexusops.models.inventory import InventoryForecast
from nexusops.repositories.inventory import InventoryForecastRepository

logger = get_logger(__name__)

DRIFT_THRESHOLD = 0.25
MODEL_VERSION = "v2.1"


@dataclass
class ForecastPoint:
    date: datetime
    predicted_demand: int
    confidence_lower: int
    confidence_upper: int


@dataclass
class ForecastSeries:
    warehouse_id: uuid.UUID
    sku_id: uuid.UUID
    points: list[ForecastPoint]
    model_version: str = MODEL_VERSION
    drift_detected: bool = False
    drift_score: float = 0.0


class ForecastEngine:
    """Generates demand forecasts and detects model drift."""

    def __init__(self, session: AsyncSession, horizon_days: int = 90) -> None:
        self.session = session
        self.horizon_days = horizon_days
        self.forecast_repo = InventoryForecastRepository(session)

    async def generate_forecast(
        self,
        warehouse_id: uuid.UUID,
        sku_id: uuid.UUID,
        historical_demand: list[int] | None = None,
    ) -> ForecastSeries:
        history = historical_demand or await self._load_historical_demand(
            warehouse_id, sku_id
        )

        if len(history) < 7:
            history = history + [max(history) if history else 1] * (7 - len(history))

        baseline = float(np.mean(history[-30:])) if len(history) >= 30 else float(np.mean(history))
        std = float(np.std(history[-30:])) if len(history) >= 30 else float(np.std(history))

        trend = self._compute_trend(history)
        seasonality = self._compute_seasonality(history)

        points: list[ForecastPoint] = []
        now = datetime.now(timezone.utc)

        for day_offset in range(1, self.horizon_days + 1):
            forecast_date = now + timedelta(days=day_offset)
            seasonal_factor = seasonality[day_offset % 7]
            predicted = max(0, int(baseline * seasonal_factor + trend * day_offset))
            lower = max(0, int(predicted - 1.96 * std))
            upper = int(predicted + 1.96 * std)

            points.append(
                ForecastPoint(
                    date=forecast_date,
                    predicted_demand=predicted,
                    confidence_lower=lower,
                    confidence_upper=upper,
                )
            )

        drift_score = await self._check_drift(warehouse_id, sku_id, baseline)
        series = ForecastSeries(
            warehouse_id=warehouse_id,
            sku_id=sku_id,
            points=points,
            drift_detected=drift_score > DRIFT_THRESHOLD,
            drift_score=drift_score,
        )

        await self._persist_forecast(series)
        if series.drift_detected:
            logger.warning(
                "forecast_drift_detected",
                warehouse_id=str(warehouse_id),
                sku_id=str(sku_id),
                drift_score=drift_score,
            )
        return series

    async def validate_forecast_accuracy(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID
    ) -> float:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=30)
        forecasts = await self.forecast_repo.get_forecast_series(
            warehouse_id, sku_id, start, end
        )
        if not forecasts:
            return 0.0

        errors = []
        for f in forecasts:
            if f.confidence_lower is not None and f.confidence_upper is not None:
                interval_width = f.confidence_upper - f.confidence_lower
                if interval_width > 0:
                    errors.append(abs(f.predicted_demand - (f.confidence_lower + f.confidence_upper) / 2) / interval_width)

        return float(np.mean(errors)) if errors else 0.0

    async def _load_historical_demand(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID
    ) -> list[int]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=180)
        forecasts = await self.forecast_repo.get_forecast_series(
            warehouse_id, sku_id, start, end
        )
        return [f.predicted_demand for f in forecasts]

    def _compute_trend(self, history: list[int]) -> float:
        if len(history) < 2:
            return 0.0
        x = np.arange(len(history))
        y = np.array(history, dtype=float)
        coeffs = np.polyfit(x, y, 1)
        return float(coeffs[0])

    def _compute_seasonality(self, history: list[int]) -> list[float]:
        if len(history) < 14:
            return [1.0] * 7
        weekly = []
        for dow in range(7):
            day_values = [history[i] for i in range(dow, len(history), 7)]
            weekly.append(float(np.mean(day_values)) if day_values else 1.0)
        avg = sum(weekly) / 7
        return [w / avg if avg > 0 else 1.0 for w in weekly]

    async def _check_drift(
        self, warehouse_id: uuid.UUID, sku_id: uuid.UUID, new_baseline: float
    ) -> float:
        latest = await self.forecast_repo.get_latest(warehouse_id, sku_id)
        if latest is None:
            return 0.0
        old_baseline = float(latest.predicted_demand)
        if old_baseline == 0:
            return 0.0
        return abs(new_baseline - old_baseline) / old_baseline

    async def _persist_forecast(self, series: ForecastSeries) -> None:
        for point in series.points:
            forecast = InventoryForecast(
                warehouse_id=series.warehouse_id,
                sku_id=series.sku_id,
                forecast_date=point.date,
                predicted_demand=point.predicted_demand,
                confidence_lower=point.confidence_lower,
                confidence_upper=point.confidence_upper,
                model_version=series.model_version,
                drift_score=Decimal(str(round(series.drift_score, 4))),
            )
            await self.forecast_repo.add(forecast)
