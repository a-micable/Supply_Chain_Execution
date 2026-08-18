"""JWT authentication + RBAC dependencies."""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from nexusops.config.settings import get_settings
from nexusops.core.context import set_actor_id
from nexusops.db.session import get_db_session
from nexusops.models.auth import Role, User, UserRole
from nexusops.schemas.api import MeResponse, TokenRequest, TokenResponse


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v2/auth/token")


def _hash_password(password: str, *, salt: str) -> str:
    # Deterministic salt for bootstrap; for real systems use per-user random salt.
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return dk.hex()


def verify_password(password: str, password_hash: str, *, salt: str) -> bool:
    expected = _hash_password(password, salt=salt)
    return hmac.compare_digest(expected, password_hash)


def create_access_token(*, user_id: uuid.UUID, username: str, roles: list[str]) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=60)
    payload = {
        "sub": str(user_id),
        "username": username,
        "roles": roles,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


async def _load_user_and_roles(session: AsyncSession, *, user_id: uuid.UUID) -> tuple[User, list[str]]:
    stmt = select(User).where(User.id == user_id)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    roles_stmt = (
        select(Role.name)
        .select_from(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user_id)
    )
    roles = [r for (r,) in (await session.execute(roles_stmt)).all()]
    return user, roles


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: AsyncSession = Depends(get_db_session),
) -> MeResponse:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = uuid.UUID(str(sub))
    user, roles = await _load_user_and_roles(session, user_id=user_id)

    set_actor_id(user.username)
    return MeResponse(user_id=str(user.id), username=user.username, roles=roles)


def require_roles(*required: str):
    def _checker(me: MeResponse = Depends(get_current_user)) -> MeResponse:
        if not required:
            return me
        if not set(me.roles).intersection(required):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return me

    return _checker


async def issue_token(
    body: TokenRequest,
    session: AsyncSession,
) -> TokenResponse:
    stmt = select(User).where(User.username == body.username)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    salt = str(user.id)  # simple, deterministic bootstrap salt
    if not verify_password(body.password, user.password_hash, salt=salt):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    roles_stmt = (
        select(Role.name)
        .select_from(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user.id)
    )
    roles = [r for (r,) in (await session.execute(roles_stmt)).all()]

    token = create_access_token(user_id=user.id, username=user.username, roles=roles)
    return TokenResponse(
        access_token=token,
        user_id=str(user.id),
        username=user.username,
        roles=roles,
    )

