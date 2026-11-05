"""Create tenant-bound MRP run history and planned orders.

Revision ID: 0053
Revises: 0052
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0053"
down_revision: str | None = "0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UOMS = "('EA', 'KG', 'G', 'L', 'ML', 'M', 'M2')"


def upgrade() -> None:
    op.create_table(
        "mrp_run_history",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("as_of", sa.Date(), nullable=False),
        sa.Column("horizon_end", sa.Date(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.Column("demand_count", sa.Integer(), nullable=False),
        sa.Column("requirement_count", sa.Integer(), nullable=False),
        sa.Column("planned_order_count", sa.Integer(), nullable=False),
        sa.Column("alert_count", sa.Integer(), nullable=False),
        sa.Column("input_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("horizon_end >= as_of", name="ck_mrp_run_history_horizon"),
        sa.CheckConstraint(
            "completed_at >= started_at",
            name="ck_mrp_run_history_execution_dates",
        ),
        sa.CheckConstraint("status = 'COMPLETED'", name="ck_mrp_run_history_status"),
        sa.CheckConstraint(
            "char_length(engine_version) BETWEEN 1 AND 32",
            name="ck_mrp_run_history_engine_version",
        ),
        sa.CheckConstraint("demand_count >= 1", name="ck_mrp_run_history_demand_count"),
        sa.CheckConstraint(
            "requirement_count >= 1",
            name="ck_mrp_run_history_requirement_count",
        ),
        sa.CheckConstraint(
            "planned_order_count >= 0",
            name="ck_mrp_run_history_planned_order_count",
        ),
        sa.CheckConstraint("alert_count >= 0", name="ck_mrp_run_history_alert_count"),
        sa.CheckConstraint(
            "jsonb_typeof(input_snapshot) = 'object'",
            name="ck_mrp_run_history_input_snapshot",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(result_snapshot) = 'object'",
            name="ck_mrp_run_history_result_snapshot",
        ),
        sa.CheckConstraint("version >= 1", name="ck_mrp_run_history_version"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_mrp_run_history_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_mrp_run_history"),
        sa.UniqueConstraint("company_id", "id", name="uq_mrp_run_company_id"),
        schema="production",
    )
    op.create_index(
        "ix_mrp_run_company_as_of_horizon",
        "mrp_run_history",
        ["company_id", "as_of", "horizon_end", "completed_at"],
        schema="production",
    )
    op.create_index(
        "ix_mrp_run_company_completed",
        "mrp_run_history",
        ["company_id", "completed_at", "id"],
        schema="production",
    )

    op.create_table(
        "planned_order",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("mrp_run_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("order_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 6), nullable=False),
        sa.Column("uom", sa.String(12), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=False),
        sa.Column("release_on", sa.Date(), nullable=False),
        sa.Column("source_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_planned_order_sequence"),
        sa.CheckConstraint(
            "order_type IN ('MANUFACTURE', 'PURCHASE')",
            name="ck_planned_order_order_type",
        ),
        sa.CheckConstraint(
            "status IN ('PLANNED', 'CONVERTED', 'CANCELLED')",
            name="ck_planned_order_status",
        ),
        sa.CheckConstraint("quantity > 0", name="ck_planned_order_quantity"),
        sa.CheckConstraint(f"uom IN {_UOMS}", name="ck_planned_order_uom"),
        sa.CheckConstraint("release_on <= due_on", name="ck_planned_order_dates"),
        sa.CheckConstraint(
            "jsonb_typeof(source_ids) = 'array' AND jsonb_array_length(source_ids) > 0",
            name="ck_planned_order_source_ids",
        ),
        sa.CheckConstraint("version >= 1", name="ck_planned_order_version"),
        sa.ForeignKeyConstraint(
            ["company_id", "mrp_run_id"],
            ["production.mrp_run_history.company_id", "production.mrp_run_history.id"],
            name="fk_planned_order_company_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_planned_order_company_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", "mrp_run_id", name="pk_planned_order"),
        sa.UniqueConstraint(
            "company_id",
            "mrp_run_id",
            "id",
            name="uq_planned_order_company_run_id",
        ),
        sa.UniqueConstraint(
            "company_id",
            "mrp_run_id",
            "sequence",
            name="uq_planned_order_run_sequence",
        ),
        schema="production",
    )
    op.create_index(
        "ix_planned_order_company_status_dates",
        "planned_order",
        ["company_id", "status", "release_on", "due_on"],
        schema="production",
    )
    op.create_index(
        "ix_planned_order_company_product_due",
        "planned_order",
        ["company_id", "product_id", "due_on"],
        schema="production",
    )


def downgrade() -> None:
    op.drop_table("planned_order", schema="production")
    op.drop_table("mrp_run_history", schema="production")
