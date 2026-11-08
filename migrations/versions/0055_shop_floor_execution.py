"""Create tenant-bound shop-floor execution evidence.

Revision ID: 0055
Revises: 0054
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0055"
down_revision: str | None = "0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shop_floor_operation_log",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("production_order_id", sa.Uuid(), nullable=False),
        sa.Column("operation_sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("work_center_code", sa.String(32), nullable=False),
        sa.Column("good_quantity", sa.Numeric(24, 6), nullable=False),
        sa.Column(
            "material_consumptions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("order_version_before", sa.Integer(), nullable=False),
        sa.Column("order_version_after", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ('STARTED', 'PROGRESS', 'COMPLETED')",
            name="ck_shop_floor_log_event_type",
        ),
        sa.CheckConstraint(
            "operation_sequence >= 1", name="ck_shop_floor_log_sequence"
        ),
        sa.CheckConstraint("good_quantity >= 0", name="ck_shop_floor_log_good_qty"),
        sa.CheckConstraint(
            "jsonb_typeof(material_consumptions) = 'array'",
            name="ck_shop_floor_log_materials",
        ),
        sa.CheckConstraint(
            "order_version_before >= 1", name="ck_shop_floor_log_version_before"
        ),
        sa.CheckConstraint(
            "order_version_after >= order_version_before",
            name="ck_shop_floor_log_version_after",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "production_order_id"],
            ["production.production_order.company_id", "production.production_order.id"],
            name="fk_shop_floor_log_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "work_center_code"],
            ["production.work_center.company_id", "production.work_center.code"],
            name="fk_shop_floor_log_center",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_shop_floor_operation_log"),
        sa.UniqueConstraint("company_id", "id", name="uq_shop_floor_log_company_id"),
        sa.UniqueConstraint(
            "company_id", "request_id", name="uq_shop_floor_log_company_request"
        ),
        schema="production",
    )
    op.create_index(
        "ix_shop_floor_log_order_operation",
        "shop_floor_operation_log",
        ["company_id", "production_order_id", "operation_sequence", "occurred_at"],
        schema="production",
    )
    op.create_index(
        "uq_shop_floor_log_started",
        "shop_floor_operation_log",
        ["company_id", "production_order_id", "operation_sequence"],
        unique=True,
        schema="production",
        postgresql_where=sa.text("event_type = 'STARTED'"),
    )
    op.create_index(
        "uq_shop_floor_log_completed",
        "shop_floor_operation_log",
        ["company_id", "production_order_id", "operation_sequence"],
        unique=True,
        schema="production",
        postgresql_where=sa.text("event_type = 'COMPLETED'"),
    )

    op.create_table(
        "scrap_record",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("operation_log_id", sa.Uuid(), nullable=False),
        sa.Column("production_order_id", sa.Uuid(), nullable=False),
        sa.Column("operation_sequence", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 6), nullable=False),
        sa.Column("reason_code", sa.String(32), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "operation_sequence >= 1", name="ck_scrap_record_sequence"
        ),
        sa.CheckConstraint("quantity > 0", name="ck_scrap_record_quantity"),
        sa.CheckConstraint(
            "reason_code ~ '^[A-Z0-9][A-Z0-9_]{1,31}$'",
            name="ck_scrap_record_reason_code",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "operation_log_id"],
            [
                "production.shop_floor_operation_log.company_id",
                "production.shop_floor_operation_log.id",
            ],
            name="fk_scrap_record_log",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "production_order_id"],
            ["production.production_order.company_id", "production.production_order.id"],
            name="fk_scrap_record_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_scrap_record_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_scrap_record"),
        sa.UniqueConstraint("company_id", "id", name="uq_scrap_record_company_id"),
        schema="production",
    )
    op.create_index(
        "ix_scrap_record_order_operation",
        "scrap_record",
        ["company_id", "production_order_id", "operation_sequence", "occurred_at"],
        schema="production",
    )


def downgrade() -> None:
    op.drop_table("scrap_record", schema="production")
    op.drop_table("shop_floor_operation_log", schema="production")
