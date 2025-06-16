"""Additional alembic migration for fulfillment and transportation tables."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_fulfillment_transport"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "order_lines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("quantity_ordered", sa.Integer, nullable=False),
        sa.Column("quantity_allocated", sa.Integer, server_default="0"),
        sa.Column("quantity_shipped", sa.Integer, server_default="0"),
        sa.Column("unit_price", sa.Numeric(12, 4), nullable=False),
        sa.Column("backorder_quantity", sa.Integer, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "fulfillment_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("status", sa.String(32), server_default="planned"),
        sa.Column("planned_ship_date", sa.DateTime(timezone=True)),
        sa.Column("estimated_cost", sa.Numeric(12, 4)),
        sa.Column("routing_score", sa.Numeric(8, 4)),
        sa.Column("plan_details", postgresql.JSONB, server_default="{}"),
        sa.Column("is_partial", sa.Boolean, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "shipments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("shipment_number", sa.String(64), unique=True, nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id")),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("carrier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("carriers.id")),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("origin_address", postgresql.JSONB, nullable=False),
        sa.Column("destination_address", postgresql.JSONB, nullable=False),
        sa.Column("total_weight_kg", sa.Numeric(12, 4)),
        sa.Column("total_packages", sa.Integer, server_default="1"),
        sa.Column("scheduled_pickup", sa.DateTime(timezone=True)),
        sa.Column("scheduled_delivery", sa.DateTime(timezone=True)),
        sa.Column("actual_delivery", sa.DateTime(timezone=True)),
        sa.Column("tracking_number", sa.String(128)),
        sa.Column("consolidation_group_id", postgresql.UUID(as_uuid=True)),
        sa.Column("state_history", postgresql.JSONB, server_default="[]"),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "inventory_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_line_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skus.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("status", sa.String(32), server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "purchase_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("po_number", sa.String(64), unique=True, nullable=False),
        sa.Column("supplier_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("suppliers.id"), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("status", sa.String(32), server_default="draft", nullable=False),
        sa.Column("order_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_delivery", sa.DateTime(timezone=True)),
        sa.Column("total_amount", sa.Numeric(14, 4), server_default="0"),
        sa.Column("currency", sa.String(3), server_default="USD"),
        sa.Column("replenishment_run_id", postgresql.UUID(as_uuid=True)),
        sa.Column("notes", sa.String(1024)),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "warehouse_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("warehouses.id"), nullable=False),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("priority", sa.Integer, server_default="5"),
        sa.Column("assigned_to", sa.String(64)),
        sa.Column("source_location_id", postgresql.UUID(as_uuid=True)),
        sa.Column("target_location_id", postgresql.UUID(as_uuid=True)),
        sa.Column("sku_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skus.id")),
        sa.Column("quantity", sa.Integer),
        sa.Column("reference_type", sa.String(32)),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("task_data", postgresql.JSONB, server_default="{}"),
        sa.Column("version", sa.Integer, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "planning_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("decision_type", sa.String(64), nullable=False),
        sa.Column("reference_type", sa.String(64), nullable=False),
        sa.Column("reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("algorithm", sa.String(64), nullable=False),
        sa.Column("algorithm_version", sa.String(32), server_default="1.0"),
        sa.Column("input_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("output_snapshot", postgresql.JSONB, nullable=False),
        sa.Column("score", sa.Float),
        sa.Column("alternatives_considered", sa.Integer, server_default="0"),
        sa.Column("correlation_id", sa.String(64)),
        sa.Column("execution_time_ms", sa.Integer),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("planning_decisions")
    op.drop_table("warehouse_tasks")
    op.drop_table("purchase_orders")
    op.drop_table("inventory_reservations")
    op.drop_table("shipments")
    op.drop_table("fulfillment_plans")
    op.drop_table("order_lines")
