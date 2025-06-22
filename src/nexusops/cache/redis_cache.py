"""Redis cache layer with invalidation tracking."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from nexusops.config.settings import get_settings
from nexusops.core.exceptions import CacheInvalidationError
from nexusops.core.logging import get_logger

logger = get_logger(__name__)


class CacheKey:
    INVENTORY = "inv:{warehouse_id}:{sku_id}"
    NETWORK_VISIBILITY = "netvis:{sku_id}"
    ROUTING = "route:{order_id}"
    FORECAST = "forecast:{warehouse_id}:{sku_id}"
    SAFETY_STOCK = "ss:{warehouse_id}:{sku_id}"


class RedisCache:
    """Async Redis cache with domain-specific invalidation."""

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self.redis = redis_client
        self.settings = get_settings()

    async def get(self, key: str) -> Any | None:
        raw = await self.redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds or self.settings.cache_ttl_inventory_seconds
        await self.redis.setex(key, ttl, json.dumps(value, default=str))

    async def delete(self, key: str) -> None:
        await self.redis.delete(key)

    async def get_inventory(
        self, warehouse_id: str, sku_id: str
    ) -> dict[str, Any] | None:
        key = CacheKey.INVENTORY.format(warehouse_id=warehouse_id, sku_id=sku_id)
        return await self.get(key)

    async def set_inventory(
        self, warehouse_id: str, sku_id: str, data: dict[str, Any]
    ) -> None:
        key = CacheKey.INVENTORY.format(warehouse_id=warehouse_id, sku_id=sku_id)
        await self.set(key, data, self.settings.cache_ttl_inventory_seconds)

    async def invalidate_inventory(
        self, warehouse_id: str, sku_id: str
    ) -> None:
        keys = [
            CacheKey.INVENTORY.format(warehouse_id=warehouse_id, sku_id=sku_id),
            CacheKey.NETWORK_VISIBILITY.format(sku_id=sku_id),
            CacheKey.SAFETY_STOCK.format(warehouse_id=warehouse_id, sku_id=sku_id),
        ]
        if keys:
            await self.redis.delete(*keys)
        logger.debug("cache_invalidated", keys=keys)

    async def invalidate_routing(self, order_id: str) -> None:
        key = CacheKey.ROUTING.format(order_id=order_id)
        await self.delete(key)

    async def invalidate_forecast(
        self, warehouse_id: str, sku_id: str
    ) -> None:
        key = CacheKey.FORECAST.format(warehouse_id=warehouse_id, sku_id=sku_id)
        await self.delete(key)

    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all keys matching pattern. Use with caution."""
        count = 0
        async for key in self.redis.scan_iter(match=pattern):
            await self.redis.delete(key)
            count += 1
        return count

    async def get_or_set(
        self, key: str, factory, ttl_seconds: int | None = None
    ) -> Any:
        cached = await self.get(key)
        if cached is not None:
            return cached
        value = await factory()
        await self.set(key, value, ttl_seconds)
        return value


async def create_redis_client() -> aioredis.Redis:
    settings = get_settings()
    return aioredis.from_url(str(settings.redis_url), decode_responses=True)
