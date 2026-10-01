"""Create M6 procurement supplier schema. Revision ID: 0031. Revises: 0030."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS procurement")
    op.create_table(
        "supplier",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("identity_kind", sa.String(24), nullable=False),
        sa.Column("identity_value", sa.String(60), nullable=False),
        sa.Column("identity_country_code", sa.String(2), nullable=False),
        sa.Column("legal_name", sa.String(200), nullable=False),
        sa.Column("trade_name", sa.String(200), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "kind IN ('INDIVIDUAL', 'COMPANY', 'FOREIGN')", name=op.f("ck_supplier_kind")
        ),
        sa.CheckConstraint(
            "identity_kind IN ('CPF', 'CNPJ', 'FOREIGN_REGISTRATION')",
            name=op.f("ck_supplier_identity_kind"),
        ),
        sa.CheckConstraint(
            "(kind = 'INDIVIDUAL' AND identity_kind = 'CPF' AND identity_country_code = 'BR') OR (kind = 'COMPANY' AND identity_kind = 'CNPJ' AND identity_country_code = 'BR') OR (kind = 'FOREIGN' AND identity_kind = 'FOREIGN_REGISTRATION' AND identity_country_code <> 'BR')",
            name=op.f("ck_supplier_kind_identity_match"),
        ),
        sa.CheckConstraint(
            "identity_country_code ~ '^[A-Z]{2}$'", name=op.f("ck_supplier_identity_country_code")
        ),
        sa.CheckConstraint(
            "(identity_kind = 'CPF' AND identity_value ~ '^[0-9]{11}$') OR (identity_kind = 'CNPJ' AND identity_value ~ '^[0-9]{14}$') OR (identity_kind = 'FOREIGN_REGISTRATION' AND identity_value ~ '^[A-Z0-9][A-Z0-9 ._/-]{1,59}$')",
            name=op.f("ck_supplier_identity_value_format"),
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE', 'BLOCKED')", name=op.f("ck_supplier_status")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_supplier_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            ondelete="RESTRICT",
            name=op.f("fk_supplier_company_id_company"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier")),
        sa.UniqueConstraint("company_id", "id", name="uq_supplier_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "identity_kind",
            "identity_country_code",
            "identity_value",
            name="uq_supplier_fiscal_identity",
        ),
        schema="procurement",
    )
    op.create_index(
        "ix_supplier_company_legal_name",
        "supplier",
        ["company_id", "legal_name", "id"],
        schema="procurement",
    )
    op.create_index(
        "ix_supplier_company_status", "supplier", ["company_id", "status"], schema="procurement"
    )
    op.create_table(
        "supplier_site",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("line1", sa.String(180), nullable=False),
        sa.Column("line2", sa.String(180), nullable=True),
        sa.Column("district", sa.String(120), nullable=True),
        sa.Column("city", sa.String(120), nullable=False),
        sa.Column("state", sa.String(80), nullable=True),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("email", sa.String(180), nullable=True),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.CheckConstraint(
            "code ~ '^[A-Z0-9][A-Z0-9_-]{0,31}$'", name=op.f("ck_supplier_site_code_format")
        ),
        sa.CheckConstraint(
            "country_code ~ '^[A-Z]{2}$'", name=op.f("ck_supplier_site_country_code")
        ),
        sa.CheckConstraint(
            "(country_code = 'BR' AND state ~ '^[A-Z]{2}$' AND postal_code ~ '^[0-9]{8}$') OR country_code <> 'BR'",
            name=op.f("ck_supplier_site_brazilian_address"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_supplier_site_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["procurement.supplier.company_id", "procurement.supplier.id"],
            name="fk_supplier_site_company_supplier",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_site")),
        sa.UniqueConstraint("company_id", "id", name="uq_supplier_site_company_id"),
        sa.UniqueConstraint("company_id", "code", name="uq_supplier_site_company_code"),
        schema="procurement",
    )
    op.create_index(
        "ix_supplier_site_supplier",
        "supplier_site",
        ["company_id", "supplier_id", "code", "id"],
        schema="procurement",
    )
    op.create_index(
        "uq_supplier_site_primary",
        "supplier_site",
        ["company_id", "supplier_id"],
        unique=True,
        schema="procurement",
        postgresql_where=sa.text("is_primary"),
    )


def downgrade() -> None:
    op.drop_table("supplier_site", schema="procurement")
    op.drop_table("supplier", schema="procurement")
    op.execute("DROP SCHEMA IF EXISTS procurement")
