"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUSOPS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    app_name: str = "NexusOps"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v2"
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://nexusops:nexusops_dev@localhost:5433/nexusops"
    )
    redis_url: RedisDsn = Field(default="redis://localhost:6379/0")
    event_stream_key: str = "nexusops:events"
    worker_poll_interval_ms: int = 500
    worker_batch_size: int = 50
    allocation_lock_ttl_seconds: int = 300
    forecast_horizon_days: int = 90
    safety_stock_service_level: float = 0.95
    max_route_stops: int = 25
    consolidation_window_hours: int = 4
    cache_ttl_inventory_seconds: int = 60
    cache_ttl_routing_seconds: int = 120
    audit_retention_days: int = 2555
    enable_optimization_engine: bool = True
    jwt_secret: str = Field(default="change-me-in-production", repr=False)
    correlation_id_header: str = "X-Correlation-ID"


@lru_cache
def get_settings() -> Settings:
    return Settings()
