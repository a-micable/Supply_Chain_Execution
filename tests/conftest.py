"""Test fixtures and utilities."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import JSON, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexusops.db.base import Base
from nexusops.models import audit, events, fulfillment, inventory, procurement, transportation, warehouse  # noqa: F401
from nexusops.models.inventory import InventoryBalance, Sku
from nexusops.models.warehouse import Warehouse


def _patch_jsonb_for_sqlite() -> None:
    """SQLite test engine cannot compile PostgreSQL JSONB columns."""
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, JSONB):
                column.type = JSON()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest_asyncio.fixture
async def engine():
    _patch_jsonb_for_sqlite()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess
        await sess.rollback()


@pytest_asyncio.fixture
async def sample_warehouse(session: AsyncSession) -> Warehouse:
    wh = Warehouse(
        warehouse_code="WH-EAST-01",
        name="East Coast Distribution Center",
        address={
            "street": "100 Logistics Way",
            "city": "Newark",
            "state": "NJ",
            "postal_code": "07102",
            "country": "US",
            "latitude": 40.7357,
            "longitude": -74.1724,
        },
        fulfillment_priority=3,
    )
    session.add(wh)
    await session.flush()
    return wh


@pytest_asyncio.fixture
async def sample_sku(session: AsyncSession) -> Sku:
    sku = Sku(
        sku_code="SKU-TEST-001",
        description="Test Widget Assembly",
        uom="EA",
        weight_kg=Decimal("2.5"),
    )
    session.add(sku)
    await session.flush()
    return sku


@pytest_asyncio.fixture
async def stocked_balance(
    session: AsyncSession, sample_warehouse: Warehouse, sample_sku: Sku
) -> InventoryBalance:
    balance = InventoryBalance(
        warehouse_id=sample_warehouse.id,
        sku_id=sample_sku.id,
        on_hand=500,
        reserved=0,
        allocated=0,
    )
    session.add(balance)
    await session.flush()
    return balance
