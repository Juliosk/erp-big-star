"""Create M14 customer groups and memberships.

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add company-scoped customer segmentation structures."""
    op.create_table(
        "customer_group",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_group")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_customer_group_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_customer_group_company_id"),
        sa.UniqueConstraint("company_id", "code", name="uq_customer_group_code"),
        sa.CheckConstraint(
            "code ~ '^[A-Z0-9][A-Z0-9_-]{1,49}$'", name=op.f("ck_customer_group_code")
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 120 AND name = btrim(name)",
            name=op.f("ck_customer_group_name"),
        ),
        sa.CheckConstraint(
            "description IS NULL OR "
            "(char_length(description) BETWEEN 1 AND 500 AND description = btrim(description))",
            name=op.f("ck_customer_group_description"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_customer_group_version_positive")),
        schema="crm",
    )
    op.create_index(
        "ix_customer_group_company_name",
        "customer_group",
        ["company_id", "name", "id"],
        schema="crm",
    )
    op.create_table(
        "customer_group_member",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_group_member")),
        sa.ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_group_member_company_customer",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "customer_group_id"],
            ["crm.customer_group.company_id", "crm.customer_group.id"],
            name="fk_customer_group_member_company_group",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "company_id",
            "customer_id",
            "customer_group_id",
            name="uq_customer_group_member",
        ),
        schema="crm",
    )
    op.create_index(
        "ix_customer_group_member_customer",
        "customer_group_member",
        ["company_id", "customer_id", "id"],
        schema="crm",
    )
    op.create_index(
        "ix_customer_group_member_group",
        "customer_group_member",
        ["company_id", "customer_group_id", "id"],
        schema="crm",
    )


def downgrade() -> None:
    """Destructive for customer segmentation data; use only with explicit approval."""
    op.drop_table("customer_group_member", schema="crm")
    op.drop_table("customer_group", schema="crm")
