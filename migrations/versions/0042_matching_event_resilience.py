"""Add source cursors and matching re-evaluation queue.

Revision ID: 0042
Revises: 0041
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0042"
down_revision: str | None = "0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "matching_source_cursor",
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
        sa.Column("invalidates_snapshot", sa.Boolean(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "aggregate_version >= 1",
            name="ck_matching_source_cursor_version",
        ),
        sa.CheckConstraint(
            "producer_module IN ('procurement', 'fiscal', 'finance')",
            name="ck_matching_source_cursor_producer_module",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_matching_source_cursor_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "producer_module",
            "aggregate_type",
            "aggregate_id",
            name="pk_matching_source_cursor",
        ),
        schema="procurement",
    )
    op.create_index(
        "ix_matching_source_cursor_company_source",
        "matching_source_cursor",
        ["company_id", "producer_module", "aggregate_type", "aggregate_id"],
        schema="procurement",
    )

    op.create_table(
        "matching_reevaluation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("matching_session_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), server_default="PENDING", nullable=False),
        sa.Column("required_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "source_watermarks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "reasons",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSED')",
            name="ck_matching_reevaluation_status",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_matching_reevaluation_revision"),
        sa.ForeignKeyConstraint(
            ["company_id", "matching_session_id"],
            ["procurement.matching_session.company_id", "procurement.matching_session.id"],
            name="fk_matching_reevaluation_company_session",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_matching_reevaluation"),
        sa.UniqueConstraint(
            "company_id",
            "matching_session_id",
            name="uq_matching_reevaluation_company_session",
        ),
        schema="procurement",
    )
    op.create_index(
        "ix_matching_reevaluation_company_status",
        "matching_reevaluation",
        ["company_id", "status", "last_event_at"],
        schema="procurement",
    )


def downgrade() -> None:
    op.drop_table("matching_reevaluation", schema="procurement")
    op.drop_table("matching_source_cursor", schema="procurement")
