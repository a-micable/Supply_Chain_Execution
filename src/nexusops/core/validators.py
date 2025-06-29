"""Business rule validators for cross-domain consistency checks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from nexusops.core.types import OrderStatus, PurchaseOrderStatus, ShipmentStatus


@dataclass
class ValidationIssue:
    code: str
    message: str
    severity: str = "error"
    field_name: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    is_valid: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    def add_error(self, code: str, message: str, **context: Any) -> None:
        self.is_valid = False
        self.issues.append(ValidationIssue(code, message, "error", context=context))

    def add_warning(self, code: str, message: str, **context: Any) -> None:
        self.issues.append(ValidationIssue(code, message, "warning", context=context))


class OrderValidator:
    """Validates order data and state consistency."""

    MAX_LINES = 500
    MAX_QUANTITY_PER_LINE = 10000
    MAX_PRIORITY = 10

    @classmethod
    def validate_create(
        cls,
        external_order_id: str,
        lines: list[dict[str, Any]],
        ship_to_address: dict[str, Any],
        priority: int,
    ) -> ValidationResult:
        result = ValidationResult(is_valid=True)

        if not external_order_id or len(external_order_id) > 128:
            result.add_error("INVALID_ORDER_ID", "External order ID required, max 128 chars")

        if not lines:
            result.add_error("NO_LINES", "Order must have at least one line")

        if len(lines) > cls.MAX_LINES:
            result.add_error("TOO_MANY_LINES", f"Maximum {cls.MAX_LINES} lines allowed")

        for i, line in enumerate(lines):
            qty = line.get("quantity", 0)
            if qty <= 0 or qty > cls.MAX_QUANTITY_PER_LINE:
                result.add_error(
                    "INVALID_QUANTITY",
                    f"Line {i}: quantity must be 1-{cls.MAX_QUANTITY_PER_LINE}",
                    line_index=i,
                )

        required_addr = {"city", "state", "postal_code"}
        missing = required_addr - set(ship_to_address.keys())
        if missing:
            result.add_error("INCOMPLETE_ADDRESS", f"Missing address fields: {missing}")

        if priority < 1 or priority > cls.MAX_PRIORITY:
            result.add_error("INVALID_PRIORITY", f"Priority must be 1-{cls.MAX_PRIORITY}")

        return result

    @classmethod
    def validate_status_transition(cls, current: str, target: str) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        terminal = {OrderStatus.DELIVERED, OrderStatus.CANCELLED}
        if current in terminal:
            result.add_error(
                "TERMINAL_STATE",
                f"Cannot transition from terminal state {current}",
            )
        return result


class ShipmentValidator:
    """Validates shipment data integrity."""

    @classmethod
    def validate_addresses(
        cls, origin: dict[str, Any], destination: dict[str, Any]
    ) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        if origin == destination:
            result.add_warning("SAME_ORIGIN_DEST", "Origin and destination are identical")
        for label, addr in [("origin", origin), ("destination", destination)]:
            if not addr.get("city"):
                result.add_error("MISSING_CITY", f"{label} address missing city", field_name=label)
        return result

    @classmethod
    def validate_weight(cls, weight_kg: Decimal | None, max_kg: Decimal = Decimal("1000")) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        if weight_kg is not None and weight_kg > max_kg:
            result.add_error("WEIGHT_EXCEEDED", f"Weight {weight_kg}kg exceeds max {max_kg}kg")
        if weight_kg is not None and weight_kg <= 0:
            result.add_error("INVALID_WEIGHT", "Weight must be positive")
        return result

    @classmethod
    def validate_state_history(cls, history: list[dict[str, Any]]) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        if not history:
            return result
        statuses = [h.get("status") for h in history]
        if len(statuses) != len(set(statuses)):
            result.add_warning("DUPLICATE_STATUS_IN_HISTORY", "Duplicate statuses in history")
        return result


class InventoryValidator:
    """Validates inventory balance consistency."""

    @classmethod
    def validate_balance(
        cls,
        on_hand: int,
        reserved: int,
        allocated: int,
        damaged: int = 0,
        quarantine: int = 0,
    ) -> ValidationResult:
        result = ValidationResult(is_valid=True)

        for name, val in [
            ("on_hand", on_hand), ("reserved", reserved),
            ("allocated", allocated), ("damaged", damaged), ("quarantine", quarantine),
        ]:
            if val < 0:
                result.add_error("NEGATIVE_BALANCE", f"{name} cannot be negative", field_name=name)

        committed = reserved + allocated + damaged + quarantine
        if committed > on_hand:
            result.add_error(
                "OVERCOMMITTED",
                f"Committed ({committed}) exceeds on_hand ({on_hand})",
                on_hand=on_hand,
                committed=committed,
            )

        available = on_hand - committed
        if available < 0:
            result.add_error("NEGATIVE_AVAILABLE", f"Available quantity is {available}")

        return result

    @classmethod
    def validate_adjustment(cls, current: int, delta: int, reason: str) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        if not reason:
            result.add_error("MISSING_REASON", "Adjustment reason is required")
        if current + delta < 0:
            result.add_error(
                "ADJUSTMENT_BELOW_ZERO",
                f"Adjustment would result in negative balance: {current + delta}",
            )
        return result


class ProcurementValidator:
    """Validates purchase order business rules."""

    @classmethod
    def validate_po_lines(cls, lines: list[dict[str, Any]]) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        if not lines:
            result.add_error("NO_PO_LINES", "Purchase order requires at least one line")
        for i, line in enumerate(lines):
            if line.get("quantity", 0) <= 0:
                result.add_error("INVALID_PO_QTY", f"Line {i}: invalid quantity", line_index=i)
            cost = Decimal(str(line.get("unit_cost", "0")))
            if cost < 0:
                result.add_error("INVALID_UNIT_COST", f"Line {i}: negative unit cost", line_index=i)
        return result

    @classmethod
    def validate_supplier_active(cls, is_active: bool, supplier_code: str) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        if not is_active:
            result.add_error(
                "INACTIVE_SUPPLIER",
                f"Supplier {supplier_code} is not active",
            )
        return result


class TransferValidator:
    """Validates inter-warehouse transfer requests."""

    @classmethod
    def validate_transfer(
        cls,
        source_id: uuid.UUID,
        dest_id: uuid.UUID,
        quantity: int,
        available: int,
    ) -> ValidationResult:
        result = ValidationResult(is_valid=True)
        if source_id == dest_id:
            result.add_error("SAME_WAREHOUSE", "Source and destination must differ")
        if quantity <= 0:
            result.add_error("INVALID_QUANTITY", "Transfer quantity must be positive")
        if quantity > available:
            result.add_error(
                "INSUFFICIENT_STOCK",
                f"Requested {quantity}, available {available}",
                requested=quantity,
                available=available,
            )
        return result
