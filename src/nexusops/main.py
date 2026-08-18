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
from nexusops.db.session import get_session_factory
from nexusops.models.auth import Role, User, UserRole
from sqlalchemy import select
from datetime import datetime, timezone
import hashlib
import uuid

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    configure_logging()
    settings = get_settings()
    logger.info("nexusops_starting", version=__version__, environment=settings.environment)
    # Bootstrap demo RBAC data for local development/testing.
    try:
        factory = get_session_factory()
        async with factory() as session:
            existing_roles = (await session.execute(select(Role.name))).all()
            existing_role_names = {r[0] for r in existing_roles}
            for role_name in ("admin", "warehouse_operator", "auditor"):
                if role_name not in existing_role_names:
                    session.add(Role(name=role_name, description=None))
            await session.flush()

            existing_users = (await session.execute(select(User.username))).all()
            existing_user_names = {u[0] for u in existing_users}

            def hash_password(password: str, *, salt: str) -> str:
                dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
                return dk.hex()

            # Admin bootstrap (password: admin123)
            if "admin" not in existing_user_names:
                admin_id = uuid.uuid4()
                session.add(
                    User(
                        id=admin_id,
                        username="admin",
                        display_name="Admin",
                        password_hash=hash_password("admin123", salt=str(admin_id)),
                        is_active=True,
                    )
                )

            if "operator" not in existing_user_names:
                operator_id = uuid.uuid4()
                session.add(
                    User(
                        id=operator_id,
                        username="operator",
                        display_name="Warehouse Operator",
                        password_hash=hash_password("operator123", salt=str(operator_id)),
                        is_active=True,
                    )
                )

            await session.flush()

            roles_by_name = {
                name: role_id
                for (name, role_id) in (
                    await session.execute(select(Role.name, Role.id))
                ).all()
            }

            async def ensure_user_role(user_username: str, role_name: str) -> None:
                user = (await session.execute(select(User).where(User.username == user_username))).scalar_one()
                role_id = roles_by_name[role_name]
                stmt = select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role_id)
                exists = (await session.execute(stmt)).scalar_one_or_none()
                if not exists:
                    session.add(UserRole(user_id=user.id, role_id=role_id, granted_at=datetime.now(timezone.utc)))

            # Ensure role bindings (idempotent).
            if "admin" in existing_user_names:
                await ensure_user_role("admin", "admin")
                await ensure_user_role("admin", "auditor")
            if "operator" in existing_user_names:
                await ensure_user_role("operator", "warehouse_operator")

            await session.commit()
    except Exception:
        # Never block startup for bootstrap; production deployments should provide their own users/roles.
        logger.exception("rbac_bootstrap_failed")
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
