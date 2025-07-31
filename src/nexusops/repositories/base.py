"""Base repository with optimistic locking support."""

from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.exceptions import ConcurrencyError, NotFoundError
from nexusops.db.base import Base, VersionMixin

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    model: type[T]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entity_id: uuid.UUID) -> T | None:
        return await self.session.get(self.model, entity_id)

    async def get_by_id_or_raise(self, entity_id: uuid.UUID) -> T:
        entity = await self.get_by_id(entity_id)
        if entity is None:
            raise NotFoundError(
                f"{self.model.__name__} {entity_id} not found",
                details={"entity_id": str(entity_id)},
            )
        return entity

    async def add(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: T) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    async def update_with_version(
        self, entity_id: uuid.UUID, expected_version: int, **values: object
    ) -> T:
        if not issubclass(self.model, VersionMixin):
            raise TypeError(f"{self.model.__name__} does not support versioning")

        stmt = (
            update(self.model)
            .where(
                self.model.id == entity_id,  # type: ignore[attr-defined]
                self.model.version == expected_version,  # type: ignore[attr-defined]
            )
            .values(**values, version=expected_version + 1)
            .returning(self.model)
        )
        result = await self.session.execute(stmt)
        updated = result.scalar_one_or_none()
        if updated is None:
            raise ConcurrencyError(
                f"Concurrent modification detected for {self.model.__name__} {entity_id}",
                details={"entity_id": str(entity_id), "expected_version": expected_version},
            )
        return updated

    async def list_all(self, limit: int = 100, offset: int = 0) -> list[T]:
        stmt = select(self.model).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
