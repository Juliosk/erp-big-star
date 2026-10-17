"""Add Treasury source cursors and payment-batch reassessment state.

Revision ID: 0045
Revises: 0044
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0045"
down_revision: str | None = "0044"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "treasury_source_cursor",
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
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "aggregate_version >= 1",
            name="ck_treasury_source_cursor_version",
        ),
        sa.CheckConstraint(
            "producer_module IN ('finance', 'procurement', 'fiscal', 'workflow')",
            name="ck_treasury_source_cursor_producer_module",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_treasury_source_cursor_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "producer_module",
            "aggregate_type",
            "aggregate_id",
            name="pk_treasury_source_cursor",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_treasury_source_cursor_company_source",
        "treasury_source_cursor",
        ["company_id", "producer_module", "aggregate_type", "aggregate_id"],
        schema="finance",
    )

    op.create_table(
        "payment_batch_review",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("payment_batch_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("required_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_states", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('BLOCKED', 'REVIEW_REQUIRED', 'CLEARED')",
            name="ck_payment_batch_review_status",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_payment_batch_review_revision",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "payment_batch_id"],
            ["finance.payment_batch.company_id", "finance.payment_batch.id"],
            name="fk_payment_batch_review_company_batch",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_payment_batch_review"),
        sa.UniqueConstraint(
            "company_id",
            "payment_batch_id",
            name="uq_payment_batch_review_company_batch",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_payment_batch_review_company_status",
        "payment_batch_review",
        ["company_id", "status", "last_event_at"],
        schema="finance",
    )


def downgrade() -> None:
    op.drop_table("payment_batch_review", schema="finance")
    op.drop_table("treasury_source_cursor", schema="finance")
