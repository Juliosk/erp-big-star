"""Add monotonic Cash Flow cursors and durable recomposition work.

Revision ID: 0049
Revises: 0048
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0049"
down_revision: str | None = "0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cash_flow_source_cursor",
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
            "aggregate_version >= 1",
            name="ck_cash_flow_source_cursor_version",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_cash_flow_source_cursor_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "producer_module",
            "aggregate_type",
            "aggregate_id",
            name="pk_cash_flow_source_cursor",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_cash_flow_source_cursor_company_event",
        "cash_flow_source_cursor",
        ["company_id", "event_occurred_at", "event_id"],
        schema="finance",
    )

    op.create_table(
        "cash_flow_recomposition_request",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("projection_id", sa.Uuid(), nullable=False),
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
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "source_aggregate_version >= 1",
            name="ck_cash_flow_recomposition_request_source_version",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_cash_flow_recomposition_request_revision",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_cash_flow_recomposition_request_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "projection_id",
            name="pk_cash_flow_recomposition_request",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_cash_flow_recomposition_request_claim",
        "cash_flow_recomposition_request",
        ["company_id", "requested_at", "projection_id"],
        schema="finance",
    )


def downgrade() -> None:
    op.drop_table("cash_flow_recomposition_request", schema="finance")
    op.drop_table("cash_flow_source_cursor", schema="finance")
