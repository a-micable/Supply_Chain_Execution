"""FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from nexusops import __version__
from nexusops.api.middleware import CorrelationIdMiddleware, RequestTimingMiddleware
from nexusops.api.routes import router
from nexusops.config.settings import get_settings
from nexusops.core.exceptions import NexusOpsError
from nexusops.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    settings = get_settings()
    logger.info("nexusops_starting", version=__version__, environment=settings.environment)
    yield
    logger.info("nexusops_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="NexusOps",
        description="Supply Chain Execution and Logistics Optimization Platform",
        version=__version__,
        lifespan=lifespan,
        docs_url=f"{settings.api_prefix}/docs" if settings.debug else None,
    )

    app.add_middleware(RequestTimingMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    @app.exception_handler(NexusOpsError)
    async def nexusops_error_handler(request: Request, exc: NexusOpsError) -> JSONResponse:
        logger.error("domain_error", code=exc.code, message=exc.message)
        return JSONResponse(
            status_code=422,
            content={"code": exc.code, "message": exc.message, "details": exc.details},
        )

    app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
