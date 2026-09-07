"""Create the M1 corporate hierarchy foundation.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _mutable_columns() -> tuple[sa.Column[Any], ...]:
    return (
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
    )


def _common_checks(table: str) -> tuple[sa.CheckConstraint, ...]:
    return (
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE')",
            name=op.f(f"ck_{table}_status"),
        ),
        sa.CheckConstraint(
            "version >= 1",
            name=op.f(f"ck_{table}_version_positive"),
        ),
    )


def upgrade() -> None:
    """Create group, company and branch in parent-to-child order."""
    op.create_table(
        "economic_group",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        *_mutable_columns(),
        sa.CheckConstraint(
            "char_length(btrim(code)) BETWEEN 2 AND 30",
            name=op.f("ck_economic_group_code_length"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 200",
            name=op.f("ck_economic_group_name_length"),
        ),
        *_common_checks("economic_group"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_economic_group")),
        sa.UniqueConstraint("code", name=op.f("uq_economic_group_code")),
        schema="admin",
    )
    op.create_index(
        "ix_economic_group_status",
        "economic_group",
        ["status"],
        schema="admin",
    )

    op.create_table(
        "company",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("legal_name", sa.String(length=200), nullable=False),
        sa.Column("trade_name", sa.String(length=200), nullable=True),
        sa.Column("tax_id", sa.String(length=14), nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        *_mutable_columns(),
        sa.CheckConstraint(
            "char_length(btrim(code)) BETWEEN 2 AND 30",
            name=op.f("ck_company_code_length"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(legal_name)) BETWEEN 1 AND 200",
            name=op.f("ck_company_legal_name_length"),
        ),
        sa.CheckConstraint(
            "tax_id ~ '^[0-9]{14}$'",
            name=op.f("ck_company_tax_id_digits"),
        ),
        *_common_checks("company"),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["admin.economic_group.id"],
            name=op.f("fk_company_group_id_economic_group"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_company")),
        sa.UniqueConstraint("group_id", "code", name="uq_company_group_code"),
        sa.UniqueConstraint("tax_id", name="uq_company_tax_id"),
        schema="admin",
    )
    op.create_index("ix_company_group_id", "company", ["group_id"], schema="admin")
    op.create_index(
        "ix_company_group_status",
        "company",
        ["group_id", "status"],
        schema="admin",
    )

    op.create_table(
        "branch",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tax_id", sa.String(length=14), nullable=False),
        sa.Column("timezone", sa.String(length=100), nullable=False),
        *_mutable_columns(),
        sa.CheckConstraint(
            "char_length(btrim(code)) BETWEEN 2 AND 30",
            name=op.f("ck_branch_code_length"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 200",
            name=op.f("ck_branch_name_length"),
        ),
        sa.CheckConstraint(
            "tax_id ~ '^[0-9]{14}$'",
            name=op.f("ck_branch_tax_id_digits"),
        ),
        *_common_checks("branch"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_branch_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_branch")),
        sa.UniqueConstraint("company_id", "code", name="uq_branch_company_code"),
        sa.UniqueConstraint("tax_id", name="uq_branch_tax_id"),
        schema="admin",
    )
    op.create_index("ix_branch_company_id", "branch", ["company_id"], schema="admin")
    op.create_index(
        "ix_branch_company_status",
        "branch",
        ["company_id", "status"],
        schema="admin",
    )


def downgrade() -> None:
    """Remove the hierarchy in child-to-parent order."""
    op.drop_table("branch", schema="admin")
    op.drop_table("company", schema="admin")
    op.drop_table("economic_group", schema="admin")
