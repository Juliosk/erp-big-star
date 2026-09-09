"""Create M14 customer contacts and addresses.

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add customer child records scoped by company and parent customer."""
    op.create_table(
        "customer_contact",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("value", sa.String(180), nullable=False),
        sa.Column("name", sa.String(120), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_contact")),
        sa.ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_contact_company_customer",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "company_id",
            "customer_id",
            "role",
            "kind",
            "value",
            name="uq_customer_contact_value",
        ),
        sa.CheckConstraint(
            "role IN ('BILLING', 'SHIPPING', 'COMMERCIAL', 'FISCAL')",
            name=op.f("ck_customer_contact_role"),
        ),
        sa.CheckConstraint("kind IN ('EMAIL', 'PHONE')", name=op.f("ck_customer_contact_kind")),
        sa.CheckConstraint(
            "char_length(value) BETWEEN 3 AND 180 AND value = btrim(value)",
            name=op.f("ck_customer_contact_value"),
        ),
        sa.CheckConstraint(
            "name IS NULL OR (char_length(name) BETWEEN 1 AND 120 AND name = btrim(name))",
            name=op.f("ck_customer_contact_name"),
        ),
        schema="crm",
    )
    op.create_index(
        "ix_customer_contact_customer",
        "customer_contact",
        ["company_id", "customer_id", "role", "id"],
        schema="crm",
    )
    op.create_table(
        "customer_address",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("line1", sa.String(180), nullable=False),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("postal_code", sa.String(8), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("line2", sa.String(180), nullable=True),
        sa.Column("district", sa.String(120), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customer_address")),
        sa.ForeignKeyConstraint(
            ["company_id", "customer_id"],
            ["crm.customer.company_id", "crm.customer.id"],
            name="fk_customer_address_company_customer",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "role IN ('BILLING', 'SHIPPING', 'COMMERCIAL', 'FISCAL')",
            name=op.f("ck_customer_address_role"),
        ),
        sa.CheckConstraint(
            "char_length(line1) BETWEEN 1 AND 180 AND line1 = btrim(line1)",
            name=op.f("ck_customer_address_line1"),
        ),
        sa.CheckConstraint(
            "line2 IS NULL OR (char_length(line2) BETWEEN 1 AND 180 AND line2 = btrim(line2))",
            name=op.f("ck_customer_address_line2"),
        ),
        sa.CheckConstraint(
            "district IS NULL OR "
            "(char_length(district) BETWEEN 1 AND 120 AND district = btrim(district))",
            name=op.f("ck_customer_address_district"),
        ),
        sa.CheckConstraint(
            "char_length(city) BETWEEN 1 AND 120 AND city = btrim(city)",
            name=op.f("ck_customer_address_city"),
        ),
        sa.CheckConstraint("state ~ '^[A-Z]{2}$'", name=op.f("ck_customer_address_state")),
        sa.CheckConstraint(
            "postal_code ~ '^[0-9]{8}$'", name=op.f("ck_customer_address_postal_code")
        ),
        sa.CheckConstraint(
            "country_code ~ '^[A-Z]{2}$'", name=op.f("ck_customer_address_country_code")
        ),
        schema="crm",
    )
    op.create_index(
        "ix_customer_address_customer",
        "customer_address",
        ["company_id", "customer_id", "role", "id"],
        schema="crm",
    )


def downgrade() -> None:
    """Destructive for M14 child data; use only with explicit approval and a backup."""
    op.drop_table("customer_address", schema="crm")
    op.drop_table("customer_contact", schema="crm")
