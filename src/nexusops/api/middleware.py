"""FastAPI middleware for request tracing and error handling."""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from nexusops.config.settings import get_settings
from nexusops.core.context import set_correlation_id
from nexusops.core.logging import get_logger

logger = get_logger(__name__)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Injects correlation ID into request context for distributed tracing."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        header = settings.correlation_id_header
        correlation_id = request.headers.get(header) or str(uuid.uuid4())
        set_correlation_id(correlation_id)

        response = await call_next(request)
        response.headers[header] = correlation_id
        return response


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Logs request duration for performance monitoring."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start) * 1000

        if duration_ms > 1000:
            logger.warning(
                "slow_request",
                path=request.url.path,
                method=request.method,
                duration_ms=round(duration_ms, 2),
            )
        else:
            logger.debug(
                "request_completed",
                path=request.url.path,
                method=request.method,
                duration_ms=round(duration_ms, 2),
                status=response.status_code,
            )
        response.headers["X-Response-Time-Ms"] = str(round(duration_ms, 2))
        return response
