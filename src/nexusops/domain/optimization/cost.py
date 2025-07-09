"""Cost optimization across fulfillment and transportation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from nexusops.core.logging import get_logger
from nexusops.repositories.fulfillment import OrderRepository
from nexusops.repositories.transportation import CarrierRepository, ShipmentRepository
from nexusops.repositories.warehouse import WarehouseRepository

logger = get_logger(__name__)


@dataclass
class CostComponent:
    category: str
    amount: Decimal
    unit: str
    quantity: int = 1


@dataclass
class CostBreakdown:
    reference_id: uuid.UUID
    reference_type: str
    components: list[CostComponent] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum(c.amount for c in self.components)


@dataclass
class CostOptimizationResult:
    original_cost: Decimal
    optimized_cost: Decimal
    savings: Decimal
    savings_pct: float
    recommendations: list[str] = field(default_factory=list)
    alternative_breakdown: CostBreakdown | None = None


class CostOptimizer:
    """Analyzes and optimizes costs across the fulfillment chain."""

    PICK_COST_PER_LINE = Decimal("1.50")
    PACK_COST_PER_PACKAGE = Decimal("3.00")
    STORAGE_COST_PER_UNIT_DAY = Decimal("0.02")
    BASE_SHIPPING_COST = Decimal("15.00")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.order_repo = OrderRepository(session)
        self.shipment_repo = ShipmentRepository(session)
        self.carrier_repo = CarrierRepository(session)
        self.warehouse_repo = WarehouseRepository(session)

    async def analyze_order_cost(self, order_id: uuid.UUID) -> CostBreakdown:
        order = await self.order_repo.get_with_lines(order_id)
        if order is None:
            raise ValueError(f"Order {order_id} not found")

        components: list[CostComponent] = []
        line_count = len(order.lines)
        total_units = sum(l.quantity_ordered for l in order.lines)

        components.append(CostComponent("picking", self.PICK_COST_PER_LINE * line_count, "USD", line_count))
        components.append(CostComponent("packing", self.PACK_COST_PER_PACKAGE, "USD", 1))
        components.append(CostComponent("storage", self.STORAGE_COST_PER_UNIT_DAY * total_units * 3, "USD", total_units))
        components.append(CostComponent("shipping", self.BASE_SHIPPING_COST, "USD", 1))

        for line in order.lines:
            components.append(
                CostComponent(
                    "product",
                    line.unit_price * line.quantity_ordered,
                    "USD",
                    line.quantity_ordered,
                )
            )

        return CostBreakdown(reference_id=order_id, reference_type="order", components=components)

    async def optimize_order_fulfillment_cost(self, order_id: uuid.UUID) -> CostOptimizationResult:
        original = await self.analyze_order_cost(order_id)
        recommendations: list[str] = []

        pick_cost = next((c for c in original.components if c.category == "picking"), None)
        if pick_cost and pick_cost.quantity > 3:
            recommendations.append("Consolidate pick lines to reduce per-line picking cost")

        warehouses = await self.warehouse_repo.list_active()
        if len(warehouses) > 1:
            recommendations.append("Evaluate single-warehouse fulfillment to reduce split shipment costs")

        carriers = await self.carrier_repo.list_active()
        if carriers:
            cheapest = min(carriers, key=lambda c: c.cost_per_kg or Decimal("999"))
            recommendations.append(f"Consider carrier {cheapest.carrier_code} for cost savings")

        optimized_shipping = self.BASE_SHIPPING_COST * Decimal("0.85")
        optimized_total = original.total - self.BASE_SHIPPING_COST + optimized_shipping
        savings = original.total - optimized_total

        return CostOptimizationResult(
            original_cost=original.total,
            optimized_cost=optimized_total,
            savings=savings,
            savings_pct=float(savings / original.total * 100) if original.total > 0 else 0,
            recommendations=recommendations,
        )

    async def analyze_shipment_cost(self, shipment_id: uuid.UUID) -> CostBreakdown:
        shipment = await self.shipment_repo.get_by_id_or_raise(shipment_id)
        components: list[CostComponent] = []

        weight = shipment.total_weight_kg or Decimal("10")
        components.append(CostComponent("weight_based", weight * Decimal("2.50"), "USD"))

        if shipment.carrier_id:
            carrier = await self.carrier_repo.get_by_id(shipment.carrier_id)
            if carrier and carrier.cost_per_kg:
                components.append(
                    CostComponent("carrier_rate", carrier.cost_per_kg * weight, "USD")
                )

        components.append(CostComponent("handling", Decimal("5.00"), "USD"))
        return CostBreakdown(reference_id=shipment_id, reference_type="shipment", components=components)

    async def compare_carrier_costs(
        self, shipment_id: uuid.UUID
    ) -> list[tuple[str, Decimal]]:
        shipment = await self.shipment_repo.get_by_id_or_raise(shipment_id)
        carriers = await self.carrier_repo.list_active()
        weight = shipment.total_weight_kg or Decimal("10")

        costs = []
        for carrier in carriers:
            rate = carrier.cost_per_kg or Decimal("1.00")
            total = rate * weight + self.BASE_SHIPPING_COST
            costs.append((carrier.carrier_code, total))

        return sorted(costs, key=lambda x: x[1])

    async def network_cost_summary(self) -> dict:
        shipments = await self.shipment_repo.list_by_status("planned", limit=100)
        total_shipping = Decimal("0")
        for s in shipments:
            breakdown = await self.analyze_shipment_cost(s.id)
            total_shipping += breakdown.total

        pending = await self.order_repo.list_pending_allocation(limit=100)
        total_order_cost = Decimal("0")
        for order in pending:
            breakdown = await self.analyze_order_cost(order.id)
            total_order_cost += breakdown.total

        return {
            "pending_orders": len(pending),
            "planned_shipments": len(shipments),
            "total_pending_order_cost": str(total_order_cost),
            "total_planned_shipping_cost": str(total_shipping),
        }
