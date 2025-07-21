"""Event handlers for domain event processing."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.cache.redis_cache import RedisCache
from nexusops.core.logging import get_logger
from nexusops.core.types import EventType
from nexusops.events.schemas import DomainEventPayload
from nexusops.services.audit_service import AuditService

logger = get_logger(__name__)


class InventoryEventHandler:
    """Handles inventory-related domain events."""

    def __init__(self, session: AsyncSession, cache: RedisCache | None = None) -> None:
        self.session = session
        self.cache = cache
        self.audit = AuditService(session)

    async def handle_adjusted(self, event: DomainEventPayload) -> None:
        warehouse_id = event.payload.get("warehouse_id")
        sku_id = event.payload.get("sku_id")
        if self.cache and warehouse_id and sku_id:
            await self.cache.invalidate_inventory(warehouse_id, sku_id)
        logger.info("inventory_adjusted_processed", correlation_id=event.correlation_id)

    async def handle_reserved(self, event: DomainEventPayload) -> None:
        await self.audit.record(
            entity_type="inventory_reservation",
            entity_id=uuid.UUID(event.payload.get("reservation_id", str(uuid.uuid4()))),
            action="reserved",
            after_state=event.payload,
        )

    async def handle_allocation_created(self, event: DomainEventPayload) -> None:
        warehouse_id = event.payload.get("warehouse_id")
        sku_id = event.payload.get("sku_id")
        if self.cache and warehouse_id and sku_id:
            await self.cache.invalidate_inventory(warehouse_id, sku_id)
            await self.cache.invalidate_routing(event.payload.get("order_id", ""))


class ShipmentEventHandler:
    """Handles shipment lifecycle events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    async def handle_state_changed(self, event: DomainEventPayload) -> None:
        shipment_id = uuid.UUID(event.payload["shipment_id"])
        await self.audit.record_shipment_transition(
            shipment_id,
            event.payload.get("previous_status", "unknown"),
            event.payload.get("new_status", "unknown"),
        )
        logger.info(
            "shipment_state_event_processed",
            shipment_id=str(shipment_id),
        )

    async def handle_created(self, event: DomainEventPayload) -> None:
        logger.info(
            "shipment_created_event",
            shipment_number=event.payload.get("shipment_number"),
        )


class ForecastEventHandler:
    """Handles forecast update events and drift alerts."""

    DRIFT_ALERT_THRESHOLD = 0.25

    def __init__(self, session: AsyncSession, cache: RedisCache | None = None) -> None:
        self.session = session
        self.cache = cache

    async def handle_updated(self, event: DomainEventPayload) -> None:
        drift_score = event.payload.get("drift_score", 0)
        if drift_score > self.DRIFT_ALERT_THRESHOLD:
            logger.warning(
                "forecast_drift_alert",
                warehouse_id=event.payload.get("warehouse_id"),
                sku_id=event.payload.get("sku_id"),
                drift_score=drift_score,
            )
        if self.cache:
            wh = event.payload.get("warehouse_id")
            sku = event.payload.get("sku_id")
            if wh and sku:
                await self.cache.invalidate_forecast(wh, sku)


class RoutingEventHandler:
    """Handles order routing events."""

    def __init__(self, session: AsyncSession, cache: RedisCache | None = None) -> None:
        self.session = session
        self.cache = cache
        self.audit = AuditService(session)

    async def handle_order_routed(self, event: DomainEventPayload) -> None:
        order_id = event.payload.get("order_id")
        if self.cache and order_id:
            await self.cache.invalidate_routing(order_id)
        await self.audit.record(
            entity_type="order",
            entity_id=uuid.UUID(order_id) if order_id else uuid.uuid4(),
            action="routed",
            after_state=event.payload,
        )


def register_all_handlers(event_bus, session: AsyncSession, cache: RedisCache | None = None) -> None:
    """Register all event handlers with the event bus."""
    inv_handler = InventoryEventHandler(session, cache)
    ship_handler = ShipmentEventHandler(session)
    forecast_handler = ForecastEventHandler(session, cache)
    routing_handler = RoutingEventHandler(session, cache)

    event_bus.subscribe(EventType.INVENTORY_ADJUSTED.value, inv_handler.handle_adjusted)
    event_bus.subscribe(EventType.INVENTORY_RESERVED.value, inv_handler.handle_reserved)
    event_bus.subscribe(EventType.ALLOCATION_CREATED.value, inv_handler.handle_allocation_created)
    event_bus.subscribe(EventType.SHIPMENT_STATE_CHANGED.value, ship_handler.handle_state_changed)
    event_bus.subscribe(EventType.SHIPMENT_CREATED.value, ship_handler.handle_created)
    event_bus.subscribe(EventType.FORECAST_UPDATED.value, forecast_handler.handle_updated)
    event_bus.subscribe(EventType.ORDER_ROUTED.value, routing_handler.handle_order_routed)
