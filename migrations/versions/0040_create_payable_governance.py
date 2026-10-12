"""Create M12 payable governance projection.

Revision ID: 0040
Revises: 0039
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040"
down_revision: str | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payable_governance",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("payable_id", sa.Uuid(), nullable=False),
        sa.Column("fiscal_blocked", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("purchasing_blocked", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("approval_status", sa.String(24), nullable=False),
        sa.Column("workflow_instance_id", sa.Uuid(), nullable=True),
        sa.Column("authority_limit", sa.Numeric(18, 2), nullable=True),
        sa.Column("sod_threshold", sa.Numeric(18, 2), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "approval_status IN ('NOT_REQUESTED', 'PENDING', 'APPROVED', 'REJECTED')",
            name="ck_payable_governance_approval_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_payable_governance_version"),
        sa.ForeignKeyConstraint(
            ["company_id", "payable_id"],
            ["finance.payable.company_id", "finance.payable.id"],
            name="fk_payable_governance_company_payable",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("company_id", "payable_id", name="pk_payable_governance"),
        schema="finance",
    )
    op.create_index(
        "ix_payable_governance_company_status",
        "payable_governance",
        ["company_id", "approval_status", "payable_id"],
        schema="finance",
    )


def downgrade() -> None:
    op.drop_table("payable_governance", schema="finance")
