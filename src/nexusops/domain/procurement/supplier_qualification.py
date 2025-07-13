"""Supplier onboarding and qualification workflows."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.logging import get_logger
from nexusops.models.procurement import Supplier
from nexusops.repositories.procurement import SupplierRepository

logger = get_logger(__name__)


class QualificationStatus(StrEnum):
    PENDING = "pending"
    DOCUMENTS_RECEIVED = "documents_received"
    AUDIT_SCHEDULED = "audit_scheduled"
    AUDIT_PASSED = "audit_passed"
    QUALIFIED = "qualified"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


@dataclass
class QualificationCriterion:
    name: str
    weight: float
    score: float = 0.0
    passed: bool = False
    notes: str = ""


@dataclass
class SupplierQualification:
    supplier_id: uuid.UUID
    status: QualificationStatus
    criteria: list[QualificationCriterion] = field(default_factory=list)
    overall_score: float = 0.0
    qualified_at: datetime | None = None
    reviewer: str | None = None

    @property
    def is_qualified(self) -> bool:
        return self.status == QualificationStatus.QUALIFIED


DEFAULT_CRITERIA = [
    QualificationCriterion("financial_stability", 0.25),
    QualificationCriterion("quality_certifications", 0.20),
    QualificationCriterion("delivery_track_record", 0.25),
    QualificationCriterion("capacity_assessment", 0.15),
    QualificationCriterion("compliance_documentation", 0.15),
]


class SupplierQualificationService:
    """Manages supplier onboarding and qualification processes."""

    MIN_QUALIFICATION_SCORE = 0.75

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.supplier_repo = SupplierRepository(session)

    async def initiate_qualification(self, supplier_id: uuid.UUID) -> SupplierQualification:
        supplier = await self.supplier_repo.get_by_id_or_raise(supplier_id)
        qualification = SupplierQualification(
            supplier_id=supplier_id,
            status=QualificationStatus.PENDING,
            criteria=[QualificationCriterion(c.name, c.weight) for c in DEFAULT_CRITERIA],
        )
        logger.info("qualification_initiated", supplier_code=supplier.supplier_code)
        return qualification

    async def score_criterion(
        self,
        qualification: SupplierQualification,
        criterion_name: str,
        score: float,
        notes: str = "",
    ) -> None:
        for criterion in qualification.criteria:
            if criterion.name == criterion_name:
                criterion.score = min(1.0, max(0.0, score))
                criterion.passed = criterion.score >= 0.6
                criterion.notes = notes
                break
        qualification.overall_score = self._calculate_overall_score(qualification)

    def _calculate_overall_score(self, qualification: SupplierQualification) -> float:
        total = sum(c.score * c.weight for c in qualification.criteria)
        return round(total, 4)

    async def complete_qualification(
        self,
        qualification: SupplierQualification,
        reviewer: str,
    ) -> SupplierQualification:
        if qualification.overall_score >= self.MIN_QUALIFICATION_SCORE:
            qualification.status = QualificationStatus.QUALIFIED
            qualification.qualified_at = datetime.now(timezone.utc)
            qualification.reviewer = reviewer

            supplier = await self.supplier_repo.get_by_id_or_raise(qualification.supplier_id)
            supplier.is_preferred = qualification.overall_score >= 0.85
            supplier.quality_score = Decimal(str(qualification.overall_score))
        else:
            qualification.status = QualificationStatus.REJECTED
            qualification.reviewer = reviewer

        logger.info(
            "qualification_completed",
            supplier_id=str(qualification.supplier_id),
            status=qualification.status,
            score=qualification.overall_score,
        )
        return qualification

    async def suspend_supplier(self, supplier_id: uuid.UUID, reason: str) -> Supplier:
        supplier = await self.supplier_repo.get_by_id_or_raise(supplier_id)
        supplier.is_active = False
        supplier.is_preferred = False
        metrics = dict(supplier.performance_metrics or {})
        metrics["suspension_reason"] = reason
        metrics["suspended_at"] = datetime.now(timezone.utc).isoformat()
        supplier.performance_metrics = metrics
        logger.warning("supplier_suspended", supplier_code=supplier.supplier_code, reason=reason)
        return supplier

    async def reactivate_supplier(
        self, supplier_id: uuid.UUID, reviewer: str
    ) -> Supplier:
        supplier = await self.supplier_repo.get_by_id_or_raise(supplier_id)
        supplier.is_active = True
        metrics = dict(supplier.performance_metrics or {})
        metrics["reactivated_at"] = datetime.now(timezone.utc).isoformat()
        metrics["reactivated_by"] = reviewer
        metrics.pop("suspension_reason", None)
        supplier.performance_metrics = metrics
        return supplier

    async def list_suppliers_needing_review(
        self, min_score: float = 0.7
    ) -> list[Supplier]:
        suppliers = await self.supplier_repo.list_by_performance_threshold(0.0)
        return [
            s for s in suppliers
            if s.is_active and float(s.quality_score or 0) < min_score
        ]

    async def bulk_score_from_performance(self) -> int:
        """Update qualification scores from historical performance metrics."""
        suppliers = await self.supplier_repo.list_preferred()
        updated = 0
        for supplier in suppliers:
            on_time = float(supplier.on_time_delivery_rate or 0.8)
            quality = float(supplier.quality_score or 0.8)
            composite = on_time * 0.5 + quality * 0.5
            supplier.quality_score = Decimal(str(round(composite, 4)))
            updated += 1
        return updated
