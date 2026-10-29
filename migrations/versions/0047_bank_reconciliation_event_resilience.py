"""Add bank-reconciliation source cursors and projected candidates.

Revision ID: 0047
Revises: 0046
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0047"
down_revision: str | None = "0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bank_reconciliation_source_cursor",
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
            name="ck_bank_reconciliation_source_cursor_version",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_bank_reconciliation_source_cursor_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "company_id",
            "producer_module",
            "aggregate_type",
            "aggregate_id",
            name="pk_bank_reconciliation_source_cursor",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_bank_reconciliation_source_cursor_company_event",
        "bank_reconciliation_source_cursor",
        ["company_id", "event_occurred_at", "event_id"],
        schema="finance",
    )

    op.create_table(
        "bank_reconciliation_candidate",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("expected_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(19, 4), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("document_number", sa.String(120), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("source_event_id", sa.Uuid(), nullable=False),
        sa.Column("source_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('RECEIVABLE_M13', 'TREASURY_M12')",
            name="ck_bank_reconciliation_candidate_source",
        ),
        sa.CheckConstraint(
            "direction IN ('CREDIT', 'DEBIT')",
            name="ck_bank_reconciliation_candidate_direction",
        ),
        sa.CheckConstraint("amount > 0", name="ck_bank_reconciliation_candidate_amount"),
        sa.CheckConstraint(
            "source_version >= 1",
            name="ck_bank_reconciliation_candidate_version",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_bank_reconciliation_candidate_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bank_reconciliation_candidate"),
        sa.UniqueConstraint(
            "company_id",
            "id",
            name="uq_bank_reconciliation_candidate_company_id",
        ),
        schema="finance",
    )
    op.create_index(
        "ix_bank_reconciliation_candidate_lookup",
        "bank_reconciliation_candidate",
        ["company_id", "active", "direction", "expected_on", "amount"],
        schema="finance",
    )


def downgrade() -> None:
    op.drop_table("bank_reconciliation_candidate", schema="finance")
    op.drop_table("bank_reconciliation_source_cursor", schema="finance")
