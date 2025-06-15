"""Initial NexusOps schema.

Revision ID: 001_initial
Revises:
Create Date: 2025-06-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "warehouses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("warehouse_code", sa.String(32), unique=True, nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("address", postgresql.JSONB, nullable=False),
        sa.Column("timezone", sa.String(64), server_default="UTC"),
        sa.Column("capacity_units", sa.Integer),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("fulfillment_priority", sa.Integer, server_default="5"),
        sa.Column("operating_hours", postgresql.JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "skus",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("sku_code", sa.String(64), unique=True, nullable=False),
        sa.Column("description", sa.String(512), nullable=False),
        sa.Column("uom", sa.String(16), server_default="EA"),
        sa.Column("weight_kg", sa.Numeric(12, 4)),
        sa.Column("is_hazmat", sa.Boolean, server_default="false"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("lead_time_days", sa.Integer, server_default="7"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "suppliers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("supplier_code", sa.String(32), unique=True, nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("contact_email", sa.String(256)),
        sa.Column("lead_time_days", sa.Integer, server_default="14"),
        sa.Column("on_time_delivery_rate", sa.Numeric(5, 4)),
        sa.Column("quality_score", sa.Numeric(5, 4)),
        sa.Column("payment_terms_days", sa.Integer, server_default="30"),
        sa.Column("is_preferred", sa.Boolean, server_default="false"),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("performance_metrics", postgresql.JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "carriers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("carrier_code", sa.String(32), unique=True, nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("service_levels", postgresql.JSONB, server_default="[]"),
        sa.Column("on_time_rate", sa.Numeric(5, 4)),
        sa.Column("cost_per_kg", sa.Numeric(10, 4)),
        sa.Column("max_weight_kg", sa.Numeric(10, 2)),
        sa.Column("is_active", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "warehouse_locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("location_code", sa.String(32), nullable=False),
        sa.Column("zone", sa.String(16), nullable=False),
        sa.Column("aisle", sa.String(8)),
        sa.Column("rack", sa.String(8)),
        sa.Column("level", sa.String(8)),
        sa.Column("location_type", sa.String(16), server_default="storage"),
        sa.Column("capacity_units", sa.Integer),
        sa.Column("is_pickable", sa.Boolean, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "inventory_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("location_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouse_locations.id")),
        sa.Column("on_hand", sa.Integer, server_default="0", nullable=False),
        sa.Column("reserved", sa.Integer, server_default="0", nullable=False),
        sa.Column("allocated", sa.Integer, server_default="0", nullable=False),
        sa.Column("in_transit", sa.Integer, server_default="0", nullable=False),
        sa.Column("damaged", sa.Integer, server_default="0", nullable=False),
        sa.Column("quarantine", sa.Integer, server_default="0", nullable=False),
        sa.Column("version", sa.Integer, server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("warehouse_id", "sku_id", "location_id", name="uq_balance_location"),
    )
    op.create_index("ix_balance_warehouse_sku", "inventory_balances", ["warehouse_id", "sku_id"])

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_order_id", sa.String(128), unique=True, nullable=False),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), server_default="received", nullable=False),
        sa.Column("priority", sa.Integer, server_default="5"),
        sa.Column("ship_to_address", postgresql.JSONB, nullable=False),
        sa.Column("requested_ship_date", sa.DateTime(timezone=True)),
        sa.Column("routing_strategy", sa.String(32), server_default="cost_optimized"),
        sa.Column("allow_partial_fulfillment", sa.Boolean, server_default="true"),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("version", sa.Integer, server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_order_status_priority", "orders", ["status", "priority"])

    op.create_table(
        "domain_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_number", sa.BigInteger, nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("causation_id", sa.String(64)),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column("metadata", postgresql.JSONB, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("processing_status", sa.String(32), server_default="pending"),
        sa.Column("retry_count", sa.Integer, server_default="0"),
        sa.Column("error_message", sa.Text),
    )
    op.create_index("ix_domain_event_sequence", "domain_events", ["sequence_number"])

    op.create_table(
        "audit_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(64)),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("event_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("before_state", postgresql.JSONB),
        sa.Column("after_state", postgresql.JSONB),
        sa.Column("metadata", postgresql.JSONB, server_default="{}"),
        sa.Column("is_manual_override", sa.Boolean, server_default="false"),
        sa.Column("override_reason", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("audit_entries")
    op.drop_table("domain_events")
    op.drop_table("orders")
    op.drop_table("inventory_balances")
    op.drop_table("warehouse_locations")
    op.drop_table("carriers")
    op.drop_table("suppliers")
    op.drop_table("skus")
    op.drop_table("warehouses")
