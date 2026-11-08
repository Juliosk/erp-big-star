"""Add Production event cursors and durable synchronization queue.

Revision ID: 0056
Revises: 0055
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0056"
down_revision: str | None = "0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "production_source_cursor",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("producer_module", sa.String(32), nullable=False),
        sa.Column("aggregate_type", sa.String(64), nullable=False),
        sa.Column("aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(150), nullable=False),
        sa.Column("event_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "aggregate_version >= 1", name="ck_production_source_cursor_version"
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_production_source_cursor_company_id_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "producer_module",
            "aggregate_type",
            "aggregate_id",
            name="pk_production_source_cursor",
        ),
        schema="production",
    )
    op.create_index(
        "ix_production_source_cursor_company_event",
        "production_source_cursor",
        ["company_id", "event_occurred_at", "event_id"],
        schema="production",
    )

    op.create_table(
        "production_synchronization_request",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("production_order_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.Column(
            "affected_product_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("source_event_id", sa.Uuid(), nullable=False),
        sa.Column("source_event_type", sa.String(150), nullable=False),
        sa.Column("source_producer_module", sa.String(32), nullable=False),
        sa.Column("source_aggregate_type", sa.String(64), nullable=False),
        sa.Column("source_aggregate_id", sa.Uuid(), nullable=False),
        sa.Column("source_aggregate_version", sa.Integer(), nullable=False),
        sa.Column("source_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("correlation_id", sa.Uuid(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "jsonb_typeof(affected_product_ids) = 'array'",
            name="ck_production_synchronization_request_affected_products",
        ),
        sa.CheckConstraint(
            "revision >= 1", name="ck_production_synchronization_request_revision"
        ),
        sa.CheckConstraint(
            "source_aggregate_version >= 1",
            name="ck_production_synchronization_request_source_version",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "production_order_id"],
            ["production.production_order.company_id", "production.production_order.id"],
            name="fk_production_sync_request_order",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "production_order_id",
            name="pk_production_synchronization_request",
        ),
        schema="production",
    )
    op.create_index(
        "ix_production_sync_request_claim",
        "production_synchronization_request",
        ["company_id", "requested_at", "production_order_id"],
        schema="production",
    )


def downgrade() -> None:
    op.drop_table("production_synchronization_request", schema="production")
    op.drop_table("production_source_cursor", schema="production")
