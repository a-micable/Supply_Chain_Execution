"""Tests for supplier qualification workflow."""

from __future__ import annotations

from decimal import Decimal

import pytest

from nexusops.domain.procurement.supplier_qualification import (
    QualificationStatus,
    SupplierQualificationService,
)
from nexusops.models.procurement import Supplier


@pytest.mark.asyncio
async def test_initiate_qualification(session):
    supplier = Supplier(
        supplier_code="SUP-QUAL-001",
        name="New Supplier Inc",
        is_active=True,
    )
    session.add(supplier)
    await session.flush()

    service = SupplierQualificationService(session)
    qual = await service.initiate_qualification(supplier.id)
    assert qual.status == QualificationStatus.PENDING
    assert len(qual.criteria) == 5


@pytest.mark.asyncio
async def test_qualification_pass(session):
    supplier = Supplier(supplier_code="SUP-QUAL-002", name="Good Supplier", is_active=True)
    session.add(supplier)
    await session.flush()

    service = SupplierQualificationService(session)
    qual = await service.initiate_qualification(supplier.id)

    for criterion in qual.criteria:
        await service.score_criterion(qual, criterion.name, 0.9)

    completed = await service.complete_qualification(qual, "reviewer@nexusops.com")
    assert completed.status == QualificationStatus.QUALIFIED
    assert completed.overall_score >= 0.75

    updated = await service.supplier_repo.get_by_id(supplier.id)
    assert updated.is_preferred


@pytest.mark.asyncio
async def test_qualification_fail(session):
    supplier = Supplier(supplier_code="SUP-QUAL-003", name="Poor Supplier", is_active=True)
    session.add(supplier)
    await session.flush()

    service = SupplierQualificationService(session)
    qual = await service.initiate_qualification(supplier.id)

    for criterion in qual.criteria:
        await service.score_criterion(qual, criterion.name, 0.3)

    completed = await service.complete_qualification(qual, "reviewer@nexusops.com")
    assert completed.status == QualificationStatus.REJECTED


@pytest.mark.asyncio
async def test_suspend_and_reactivate(session):
    supplier = Supplier(
        supplier_code="SUP-QUAL-004",
        name="Suspended Supplier",
        is_active=True,
        is_preferred=True,
    )
    session.add(supplier)
    await session.flush()

    service = SupplierQualificationService(session)
    suspended = await service.suspend_supplier(supplier.id, "quality audit failure")
    assert not suspended.is_active
    assert not suspended.is_preferred

    reactivated = await service.reactivate_supplier(supplier.id, "admin@nexusops.com")
    assert reactivated.is_active
