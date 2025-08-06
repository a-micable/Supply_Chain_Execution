"""Audit trail service for compliance and manual override tracking."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.context import get_actor_id, get_correlation_id, get_override_reason
from nexusops.core.logging import get_logger
from nexusops.models.audit import AuditEntry
from nexusops.repositories.audit import AuditRepository

logger = get_logger(__name__)


class AuditService:
    """Records immutable audit entries for all state changes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit_repo = AuditRepository(session)

    async def record(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        before_state: dict[str, Any] | None = None,
        after_state: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEntry:
        override_reason = get_override_reason()
        entry = AuditEntry(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_id=get_actor_id(),
            correlation_id=str(get_correlation_id()),
            event_timestamp=datetime.now(timezone.utc),
            before_state=before_state,
            after_state=after_state,
            metadata_=metadata or {},
            is_manual_override=override_reason is not None,
            override_reason=override_reason,
        )
        await self.audit_repo.add(entry)
        logger.info(
            "audit_recorded",
            entity_type=entity_type,
            entity_id=str(entity_id),
            action=action,
        )
        return entry

    async def record_inventory_change(
        self,
        warehouse_id: uuid.UUID,
        sku_id: uuid.UUID,
        action: str,
        before: dict[str, Any],
        after: dict[str, Any],
    ) -> AuditEntry:
        return await self.record(
            entity_type="inventory_balance",
            entity_id=sku_id,
            action=action,
            before_state=before,
            after_state=after,
            metadata={"warehouse_id": str(warehouse_id)},
        )

    async def record_shipment_transition(
        self,
        shipment_id: uuid.UUID,
        from_status: str,
        to_status: str,
    ) -> AuditEntry:
        return await self.record(
            entity_type="shipment",
            entity_id=shipment_id,
            action="state_transition",
            before_state={"status": from_status},
            after_state={"status": to_status},
        )

    async def get_entity_history(
        self, entity_type: str, entity_id: uuid.UUID, limit: int = 100
    ) -> list[AuditEntry]:
        return await self.audit_repo.list_for_entity(entity_type, entity_id, limit)

    async def get_correlation_trail(self, correlation_id: str) -> list[AuditEntry]:
        return await self.audit_repo.list_by_correlation(correlation_id)

    async def list_manual_overrides(
        self, start: datetime, end: datetime
    ) -> list[AuditEntry]:
        return await self.audit_repo.list_manual_overrides(start, end)
