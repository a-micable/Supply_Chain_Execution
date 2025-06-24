"""Request and workflow execution context."""

from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nexusops.core.types import CorrelationId

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)
_actor_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("actor_id", default=None)
_override_reason: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "override_reason", default=None
)


def get_correlation_id() -> CorrelationId:
    cid = _correlation_id.get()
    if cid is None:
        cid = str(uuid.uuid4())
        _correlation_id.set(cid)
    return CorrelationId(cid)


def set_correlation_id(correlation_id: str) -> None:
    _correlation_id.set(correlation_id)


def get_actor_id() -> str | None:
    return _actor_id.get()


def set_actor_id(actor_id: str) -> None:
    _actor_id.set(actor_id)


def get_override_reason() -> str | None:
    return _override_reason.get()


def set_override_reason(reason: str) -> None:
    _override_reason.set(reason)


@dataclass
class WorkflowContext:
    """Tracks multi-step workflow execution state."""

    workflow_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    steps_completed: list[str] = field(default_factory=list)
    steps_pending: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    compensations: list[str] = field(default_factory=list)

    def mark_step_complete(self, step: str) -> None:
        if step in self.steps_pending:
            self.steps_pending.remove(step)
        self.steps_completed.append(step)

    def register_compensation(self, step: str) -> None:
        self.compensations.insert(0, step)

    @property
    def is_complete(self) -> bool:
        return len(self.steps_pending) == 0
