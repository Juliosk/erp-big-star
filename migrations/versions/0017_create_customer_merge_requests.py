"""Create M14 duplicate candidates and merge requests.

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add traceable duplicate detection and merge-approval request structures."""
    op.create_table(
        "customer_duplicate_candidate",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence", sa.Integer(), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_duplicate_candidate")),
        sa.ForeignKeyConstraint(
            ["company_id", "source_customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_duplicate_source",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "candidate_customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_duplicate_candidate",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "company_id",
            "source_customer_id",
            "candidate_customer_id",
            name="uq_customer_duplicate_candidate_pair",
        ),
        sa.CheckConstraint(
            "source_customer_id <> candidate_customer_id",
            name=op.f("ck_customer_duplicate_candidate_different_customers"),
        ),
        sa.CheckConstraint(
            "confidence BETWEEN 0 AND 100",
            name=op.f("ck_customer_duplicate_candidate_confidence"),
        ),
        sa.CheckConstraint(
            "status IN ('SUGGESTED', 'MERGE_REQUESTED')",
            name=op.f("ck_customer_duplicate_candidate_status"),
        ),
        schema="crm",
    )
    op.create_index(
        "ix_customer_duplicate_source",
        "customer_duplicate_candidate",
        ["company_id", "source_customer_id", "confidence"],
        schema="crm",
    )
    op.create_table(
        "customer_merge",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("surviving_customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_merge")),
        sa.ForeignKeyConstraint(
            ["company_id", "source_customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_merge_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "candidate_customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_merge_candidate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "surviving_customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_merge_survivor",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "company_id",
            "source_customer_id",
            "candidate_customer_id",
            "status",
            name="uq_customer_merge_pending_pair",
        ),
        sa.CheckConstraint(
            "source_customer_id <> candidate_customer_id",
            name=op.f("ck_customer_merge_different_customers"),
        ),
        sa.CheckConstraint(
            "surviving_customer_id IN (source_customer_id, candidate_customer_id)",
            name=op.f("ck_customer_merge_survivor_in_pair"),
        ),
        sa.CheckConstraint("status IN ('PENDING_APPROVAL')", name=op.f("ck_customer_merge_status")),
        sa.CheckConstraint(
            "char_length(reason) BETWEEN 1 AND 500 AND reason = btrim(reason)",
            name=op.f("ck_customer_merge_reason"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_customer_merge_version_positive")),
        schema="crm",
    )
    op.create_index(
        "ix_customer_merge_source",
        "customer_merge",
        ["company_id", "source_customer_id", "id"],
        schema="crm",
    )


def downgrade() -> None:
    """Destructive for M14 duplicate governance data; use only with explicit approval."""
    op.drop_table("customer_merge", schema="crm")
    op.drop_table("customer_duplicate_candidate", schema="crm")
