"""Create tenant-bound production-order persistence.

Revision ID: 0052
Revises: 0051
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0052"
down_revision: str | None = "0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UOMS = "('EA', 'KG', 'G', 'L', 'ML', 'M', 'M2')"
_ORDER_STATUSES = "('DRAFT', 'RELEASED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')"
_OPERATION_STATUSES = "('PENDING', 'IN_PROGRESS', 'COMPLETED')"


def upgrade() -> None:
    op.create_table(
        "production_order",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("order_number", sa.String(40), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("planned_quantity", sa.Numeric(24, 6), nullable=False),
        sa.Column("planned_uom", sa.String(12), nullable=False),
        sa.Column("planned_start_on", sa.Date(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("bom_version_code", sa.String(32), nullable=False),
        sa.Column("bom_engineering_revision", sa.Integer(), nullable=False),
        sa.Column("bom_effective_from", sa.Date(), nullable=False),
        sa.Column("bom_effective_until", sa.Date(), nullable=True),
        sa.Column("bom_record_version", sa.Integer(), nullable=False),
        sa.Column("routing_version_code", sa.String(32), nullable=False),
        sa.Column("routing_engineering_revision", sa.Integer(), nullable=False),
        sa.Column("routing_effective_from", sa.Date(), nullable=False),
        sa.Column("routing_effective_until", sa.Date(), nullable=True),
        sa.Column("routing_record_version", sa.Integer(), nullable=False),
        sa.Column("engineering_output_quantity", sa.Numeric(24, 6), nullable=False),
        sa.Column("engineering_output_uom", sa.String(12), nullable=False),
        sa.Column("engineering_approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("engineering_approved_by", sa.Uuid(), nullable=False),
        sa.Column(
            "output_lots",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_by", sa.Uuid(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column("cancellation_reason", sa.String(500), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "order_number ~ '^[A-Z0-9][A-Z0-9._/-]{0,39}$'",
            name="ck_production_order_number",
        ),
        sa.CheckConstraint(f"status IN {_ORDER_STATUSES}", name="ck_production_order_status"),
        sa.CheckConstraint("planned_quantity > 0", name="ck_production_order_quantity"),
        sa.CheckConstraint(f"planned_uom IN {_UOMS}", name="ck_production_order_uom"),
        sa.CheckConstraint("due_on >= planned_start_on", name="ck_production_order_dates"),
        sa.CheckConstraint("bom_engineering_revision >= 1", name="ck_production_order_bom_revision"),
        sa.CheckConstraint("bom_record_version >= 1", name="ck_production_order_bom_record_version"),
        sa.CheckConstraint(
            "routing_engineering_revision >= 1",
            name="ck_production_order_routing_revision",
        ),
        sa.CheckConstraint(
            "routing_record_version >= 1",
            name="ck_production_order_routing_record_version",
        ),
        sa.CheckConstraint(
            "engineering_output_quantity > 0",
            name="ck_production_order_engineering_quantity",
        ),
        sa.CheckConstraint(
            f"engineering_output_uom IN {_UOMS}",
            name="ck_production_order_engineering_uom",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(output_lots) = 'array'",
            name="ck_production_order_output_lots",
        ),
        sa.CheckConstraint("version >= 1", name="ck_production_order_version"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_production_order_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_production_order_company_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id", "bom_version_code"],
            [
                "production.bom_header.company_id",
                "production.bom_header.product_id",
                "production.bom_header.version_code",
            ],
            name="fk_production_order_bom_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id", "routing_version_code"],
            [
                "production.routing_header.company_id",
                "production.routing_header.product_id",
                "production.routing_header.version_code",
            ],
            name="fk_production_order_routing_version",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_production_order"),
        sa.UniqueConstraint("company_id", "id", name="uq_production_order_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "order_number",
            name="uq_production_order_company_number",
        ),
        schema="production",
    )
    op.create_index(
        "ix_production_order_company_status_dates",
        "production_order",
        ["company_id", "status", "planned_start_on", "due_on"],
        schema="production",
    )
    op.create_index(
        "ix_production_order_company_product_status",
        "production_order",
        ["company_id", "product_id", "status"],
        schema="production",
    )

    op.create_table(
        "production_order_item_plan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("production_order_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("component_product_id", sa.Uuid(), nullable=False),
        sa.Column("planned_quantity", sa.Numeric(24, 6), nullable=False),
        sa.Column("uom", sa.String(12), nullable=False),
        sa.Column(
            "consumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_production_order_item_plan_sequence"),
        sa.CheckConstraint("planned_quantity > 0", name="ck_production_order_item_plan_quantity"),
        sa.CheckConstraint(f"uom IN {_UOMS}", name="ck_production_order_item_plan_uom"),
        sa.CheckConstraint(
            "jsonb_typeof(consumptions) = 'array'",
            name="ck_production_order_item_plan_consumptions",
        ),
        sa.CheckConstraint("version >= 1", name="ck_production_order_item_plan_version"),
        sa.ForeignKeyConstraint(
            ["company_id", "production_order_id"],
            ["production.production_order.company_id", "production.production_order.id"],
            name="fk_production_order_item_plan_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "component_product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_production_order_item_plan_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_production_order_item_plan"),
        sa.UniqueConstraint(
            "company_id",
            "production_order_id",
            "sequence",
            name="uq_production_order_item_plan_sequence",
        ),
        sa.UniqueConstraint(
            "company_id",
            "production_order_id",
            "component_product_id",
            name="uq_production_order_item_plan_product",
        ),
        schema="production",
    )
    op.create_index(
        "ix_production_order_item_plan_order",
        "production_order_item_plan",
        ["company_id", "production_order_id", "sequence"],
        schema="production",
    )

    op.create_table(
        "production_order_operation_execution",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("production_order_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("allowed_work_centers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("required_capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("assigned_work_center_code", sa.String(32), nullable=True),
        sa.Column(
            "assigned_work_center_capabilities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("assigned_work_center_version", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_by", sa.Uuid(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_production_order_operation_sequence"),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 120 AND name = btrim(name)",
            name="ck_production_order_operation_name",
        ),
        sa.CheckConstraint(
            f"status IN {_OPERATION_STATUSES}",
            name="ck_production_order_operation_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_work_centers) = 'array' "
            "AND jsonb_array_length(allowed_work_centers) > 0",
            name="ck_production_order_operation_centers",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(required_capabilities) = 'array'",
            name="ck_production_order_operation_capabilities",
        ),
        sa.CheckConstraint(
            "assigned_work_center_capabilities IS NULL "
            "OR jsonb_typeof(assigned_work_center_capabilities) = 'array'",
            name="ck_production_order_assigned_capabilities",
        ),
        sa.CheckConstraint(
            "assigned_work_center_version IS NULL OR assigned_work_center_version >= 1",
            name="ck_production_order_assigned_version",
        ),
        sa.CheckConstraint("version >= 1", name="ck_production_order_operation_version"),
        sa.ForeignKeyConstraint(
            ["company_id", "production_order_id"],
            ["production.production_order.company_id", "production.production_order.id"],
            name="fk_production_order_operation_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "assigned_work_center_code"],
            ["production.work_center.company_id", "production.work_center.code"],
            name="fk_production_order_operation_work_center",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_production_order_operation_execution"),
        sa.UniqueConstraint(
            "company_id",
            "production_order_id",
            "sequence",
            name="uq_production_order_operation_sequence",
        ),
        schema="production",
    )
    op.create_index(
        "ix_production_order_operation_order",
        "production_order_operation_execution",
        ["company_id", "production_order_id", "sequence", "status"],
        schema="production",
    )


def downgrade() -> None:
    op.drop_table("production_order_operation_execution", schema="production")
    op.drop_table("production_order_item_plan", schema="production")
    op.drop_table("production_order", schema="production")
