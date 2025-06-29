"""Multi-step workflow orchestration with compensation."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from nexusops.core.context import WorkflowContext
from nexusops.core.exceptions import WorkflowError
from nexusops.core.logging import get_logger

logger = get_logger(__name__)

StepHandler = Callable[[WorkflowContext], Awaitable[Any]]
CompensationHandler = Callable[[WorkflowContext], Awaitable[None]]


class WorkflowOrchestrator:
    """Executes multi-step workflows with saga-style compensation."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._steps: list[tuple[str, StepHandler, CompensationHandler | None]] = []

    def add_step(
        self,
        name: str,
        handler: StepHandler,
        compensation: CompensationHandler | None = None,
    ) -> WorkflowOrchestrator:
        self._steps.append((name, handler, compensation))
        return self

    async def execute(self, ctx: WorkflowContext | None = None) -> WorkflowContext:
        ctx = ctx or WorkflowContext(steps_pending=[s[0] for s in self._steps])
        completed_handlers: list[CompensationHandler | None] = []

        for step_name, handler, compensation in self._steps:
            if step_name not in ctx.steps_pending:
                continue
            try:
                logger.info("workflow_step_start", workflow=self.name, step=step_name)
                await handler(ctx)
                ctx.mark_step_complete(step_name)
                completed_handlers.append(compensation)
            except Exception as exc:
                logger.error(
                    "workflow_step_failed",
                    workflow=self.name,
                    step=step_name,
                    error=str(exc),
                )
                await self._compensate(ctx, completed_handlers)
                raise WorkflowError(
                    f"Workflow {self.name} failed at step {step_name}: {exc}",
                    details={"workflow_id": ctx.workflow_id, "failed_step": step_name},
                ) from exc

        logger.info("workflow_completed", workflow=self.name, workflow_id=ctx.workflow_id)
        return ctx

    async def _compensate(
        self,
        ctx: WorkflowContext,
        handlers: list[CompensationHandler | None],
    ) -> None:
        for compensation in reversed(handlers):
            if compensation is None:
                continue
            try:
                await compensation(ctx)
            except Exception as exc:
                logger.error("compensation_failed", error=str(exc))
