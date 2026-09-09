"""Create the company-owned M14 customer master.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add M14 customer core without modifying any existing business table."""
    op.execute(sa.schema.CreateSchema("crm"))
    op.create_table(
        "customer",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_type", sa.String(10), nullable=False),
        sa.Column("identity_type", sa.String(4), nullable=False),
        sa.Column("identity_value", sa.String(14), nullable=False),
        sa.Column("legal_name", sa.String(200), nullable=False),
        sa.Column("trade_name", sa.String(200), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_customer_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_customer_company_id"),
        sa.UniqueConstraint(
            "company_id", "identity_type", "identity_value", name="uq_customer_identity"
        ),
        sa.CheckConstraint(
            "customer_type IN ('INDIVIDUAL', 'COMPANY')", name=op.f("ck_customer_type")
        ),
        sa.CheckConstraint(
            "identity_type IN ('CPF', 'CNPJ')", name=op.f("ck_customer_identity_type")
        ),
        sa.CheckConstraint(
            "(customer_type = 'INDIVIDUAL' AND identity_type = 'CPF') OR "
            "(customer_type = 'COMPANY' AND identity_type = 'CNPJ')",
            name=op.f("ck_customer_type_identity_match"),
        ),
        sa.CheckConstraint(
            "(identity_type = 'CPF' AND identity_value ~ '^[0-9]{11}$') OR "
            "(identity_type = 'CNPJ' AND identity_value ~ '^[0-9]{14}$')",
            name=op.f("ck_customer_identity_value_format"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(legal_name)) BETWEEN 1 AND 200 AND legal_name = btrim(legal_name)",
            name=op.f("ck_customer_legal_name_length"),
        ),
        sa.CheckConstraint(
            "trade_name IS NULL OR "
            "(char_length(btrim(trade_name)) BETWEEN 1 AND 200 AND trade_name = btrim(trade_name))",
            name=op.f("ck_customer_trade_name_length"),
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'BLOCKED')", name=op.f("ck_customer_status")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_customer_version_positive")),
        schema="crm",
    )
    op.create_index(
        "ix_customer_company_legal_name",
        "customer",
        ["company_id", "legal_name", "id"],
        schema="crm",
    )
    op.create_index(
        "ix_customer_company_status", "customer", ["company_id", "status"], schema="crm"
    )


def downgrade() -> None:
    """Destructive for M14 data; use only with explicit approval and a backup."""
    op.drop_table("customer", schema="crm")
    op.execute(sa.schema.DropSchema("crm"))
