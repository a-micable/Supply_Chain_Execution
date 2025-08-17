"""Tests for business rule validators."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from nexusops.core.types import OrderStatus
from nexusops.core.validators import (
    InventoryValidator,
    OrderValidator,
    ProcurementValidator,
    ShipmentValidator,
    TransferValidator,
)


class TestOrderValidator:
    def test_valid_order(self):
        result = OrderValidator.validate_create(
            "ORD-001",
            [{"sku_id": str(uuid.uuid4()), "quantity": 5}],
            {"city": "Boston", "state": "MA", "postal_code": "02101"},
            5,
        )
        assert result.is_valid

    def test_missing_lines(self):
        result = OrderValidator.validate_create("ORD-001", [], {"city": "X", "state": "Y", "postal_code": "1"}, 5)
        assert not result.is_valid

    def test_invalid_quantity(self):
        result = OrderValidator.validate_create(
            "ORD-001",
            [{"quantity": 0}],
            {"city": "X", "state": "Y", "postal_code": "1"},
            5,
        )
        assert not result.is_valid

    def test_terminal_state_transition(self):
        result = OrderValidator.validate_status_transition(OrderStatus.DELIVERED, OrderStatus.PICKING)
        assert not result.is_valid


class TestShipmentValidator:
    def test_valid_addresses(self):
        result = ShipmentValidator.validate_addresses(
            {"city": "A"}, {"city": "B"}
        )
        assert result.is_valid

    def test_weight_exceeded(self):
        result = ShipmentValidator.validate_weight(Decimal("2000"))
        assert not result.is_valid


class TestInventoryValidator:
    def test_valid_balance(self):
        result = InventoryValidator.validate_balance(100, 20, 30, 5, 0)
        assert result.is_valid

    def test_overcommitted(self):
        result = InventoryValidator.validate_balance(50, 30, 30)
        assert not result.is_valid

    def test_negative_field(self):
        result = InventoryValidator.validate_balance(-1, 0, 0)
        assert not result.is_valid

    def test_adjustment_below_zero(self):
        result = InventoryValidator.validate_adjustment(10, -20, "cycle_count")
        assert not result.is_valid


class TestProcurementValidator:
    def test_valid_po_lines(self):
        result = ProcurementValidator.validate_po_lines([
            {"quantity": 100, "unit_cost": "10.00"},
        ])
        assert result.is_valid

    def test_inactive_supplier(self):
        result = ProcurementValidator.validate_supplier_active(False, "SUP-001")
        assert not result.is_valid


class TestTransferValidator:
    def test_valid_transfer(self):
        result = TransferValidator.validate_transfer(
            uuid.uuid4(), uuid.uuid4(), 50, 100
        )
        assert result.is_valid

    def test_same_warehouse(self):
        wid = uuid.uuid4()
        result = TransferValidator.validate_transfer(wid, wid, 10, 100)
        assert not result.is_valid

    def test_insufficient_stock(self):
        result = TransferValidator.validate_transfer(
            uuid.uuid4(), uuid.uuid4(), 100, 50
        )
        assert not result.is_valid
