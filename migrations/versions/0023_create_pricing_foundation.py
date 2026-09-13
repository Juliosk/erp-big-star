"""Create M9 pricing foundation tables.

Revision ID: 0023
Revises: 0022
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add company-scoped pricing lists, versions, items and initial snapshots."""
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS pricing"))
    op.create_table(
        "price_list",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("price_type", sa.String(length=32), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_price_list_code_format")),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 160 AND name = btrim(name)",
            name=op.f("ck_price_list_name_length"),
        ),
        sa.CheckConstraint(
            "price_type IN ('BASE', 'CHANNEL', 'CUSTOMER_GROUP')",
            name=op.f("ck_price_list_price_type"),
        ),
        sa.CheckConstraint("currency = 'BRL'", name=op.f("ck_price_list_currency_brl")),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name=op.f("ck_price_list_status")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_price_list_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_price_list_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_list")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_price_list_company_id")),
        sa.UniqueConstraint("company_id", "code", name=op.f("uq_price_list_company_code")),
        schema="pricing",
    )
    op.create_index(
        "ix_price_list_company_status",
        "price_list",
        ["company_id", "status", "code"],
        schema="pricing",
    )
    op.create_table(
        "price_list_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_list_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("version_number >= 1", name=op.f("ck_price_list_version_number_positive")),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'SUPERSEDED', 'EXPIRED')",
            name=op.f("ck_price_list_version_status"),
        ),
        sa.CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name=op.f("ck_price_list_version_valid_range")),
        sa.CheckConstraint("source ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'", name=op.f("ck_price_list_version_source_format")),
        sa.CheckConstraint(
            "status != 'ACTIVE' OR activated_at IS NOT NULL",
            name=op.f("ck_price_list_version_active_requires_activation"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_price_list_version_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id", "price_list_id"],
            ["pricing.price_list.company_id", "pricing.price_list.id"],
            name=op.f("fk_price_list_version_price_list"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_list_version")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_price_list_version_company_id")),
        sa.UniqueConstraint(
            "company_id",
            "price_list_id",
            "version_number",
            name=op.f("uq_price_list_version_number"),
        ),
        schema="pricing",
    )
    op.create_index(
        "ix_price_list_version_company_status",
        "price_list_version",
        ["company_id", "status", "valid_from"],
        schema="pricing",
    )
    op.create_table(
        "price_list_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_list_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("minimum_price_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("target_margin", sa.Numeric(8, 4), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("price_amount >= 0", name=op.f("ck_price_list_item_price_non_negative")),
        sa.CheckConstraint(
            "minimum_price_amount IS NULL OR minimum_price_amount >= 0",
            name=op.f("ck_price_list_item_min_non_negative"),
        ),
        sa.CheckConstraint(
            "minimum_price_amount IS NULL OR minimum_price_amount <= price_amount",
            name=op.f("ck_price_list_item_min_not_above_price"),
        ),
        sa.CheckConstraint(
            "target_margin IS NULL OR (target_margin >= 0 AND target_margin <= 1)",
            name=op.f("ck_price_list_item_target_margin_range"),
        ),
        sa.CheckConstraint("currency = 'BRL'", name=op.f("ck_price_list_item_currency_brl")),
        sa.ForeignKeyConstraint(
            ["company_id", "price_list_version_id"],
            ["pricing.price_list_version.company_id", "pricing.price_list_version.id"],
            name=op.f("fk_price_list_item_version"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name=op.f("fk_price_list_item_product"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_price_list_item")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_price_list_item_company_id")),
        sa.UniqueConstraint(
            "company_id",
            "price_list_version_id",
            "product_id",
            name=op.f("uq_price_list_item_product"),
        ),
        schema="pricing",
    )
    op.create_index(
        "ix_price_list_item_product",
        "price_list_item",
        ["company_id", "product_id"],
        schema="pricing",
    )
    op.create_table(
        "minimum_margin_policy",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("minimum_margin", sa.Numeric(8, 4), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_minimum_margin_policy_code_format")),
        sa.CheckConstraint(
            "minimum_margin >= 0 AND minimum_margin <= 1",
            name=op.f("ck_minimum_margin_policy_minimum_margin_range"),
        ),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name=op.f("ck_minimum_margin_policy_status")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_minimum_margin_policy_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_minimum_margin_policy_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_minimum_margin_policy")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_minimum_margin_policy_company_id")),
        sa.UniqueConstraint("company_id", "code", name=op.f("uq_minimum_margin_policy_code")),
        schema="pricing",
    )
    op.create_table(
        "pricing_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("price_list_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("price_list_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cost_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tax_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("commission_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("fee_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("freight_reference", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("target_margin", sa.Numeric(8, 4), nullable=True),
        sa.Column("minimum_margin", sa.Numeric(8, 4), nullable=True),
        sa.Column("calculated_price_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("rounded_price_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("calculated_price_amount >= 0", name=op.f("ck_pricing_snapshot_calculated_price_non_negative")),
        sa.CheckConstraint("rounded_price_amount >= 0", name=op.f("ck_pricing_snapshot_rounded_price_non_negative")),
        sa.CheckConstraint("currency = 'BRL'", name=op.f("ck_pricing_snapshot_currency_brl")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_pricing_snapshot_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name=op.f("fk_pricing_snapshot_product"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_snapshot")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_pricing_snapshot_company_id")),
        schema="pricing",
    )
    op.create_index(
        "ix_pricing_snapshot_product",
        "pricing_snapshot",
        ["company_id", "product_id", "created_at"],
        schema="pricing",
    )


def downgrade() -> None:
    """Destructive for pricing data; use only with explicit approval."""
    op.drop_table("pricing_snapshot", schema="pricing")
    op.drop_table("minimum_margin_policy", schema="pricing")
    op.drop_table("price_list_item", schema="pricing")
    op.drop_table("price_list_version", schema="pricing")
    op.drop_table("price_list", schema="pricing")
    op.execute(sa.text("DROP SCHEMA IF EXISTS pricing"))
