"""Create tenant-bound multichannel sales persistence.

Revision ID: 0057
Revises: 0056
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0057"
down_revision: str | None = "0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MARKETPLACES = "('MERCADO_LIVRE', 'SHOPEE', 'NUVEMSHOP')"
_ORDER_STATUSES = "('PENDING', 'PAID', 'SHIPPED', 'CANCELLED')"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS sales")

    op.create_table(
        "sales_channel_config",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marketplace", sa.String(24), nullable=False),
        sa.Column("display_name", sa.String(128), nullable=False),
        sa.Column("credential_reference", sa.String(255), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            f"marketplace IN {_MARKETPLACES}",
            name=op.f("ck_sales_channel_config_marketplace"),
        ),
        sa.CheckConstraint(
            "length(btrim(display_name)) BETWEEN 1 AND 128 "
            "AND display_name = btrim(display_name)",
            name=op.f("ck_sales_channel_config_display_name"),
        ),
        sa.CheckConstraint(
            "length(btrim(credential_reference)) BETWEEN 1 AND 255 "
            "AND credential_reference = btrim(credential_reference)",
            name=op.f("ck_sales_channel_config_credential_reference"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_sales_channel_config_version")
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_sales_channel_config_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_channel_config")),
        sa.UniqueConstraint(
            "company_id", "id", name=op.f("uq_sales_channel_config_company_id")
        ),
        sa.UniqueConstraint(
            "company_id",
            "marketplace",
            "account_id",
            name=op.f("uq_sales_channel_config_account"),
        ),
        schema="sales",
    )
    op.create_index(
        "ix_sales_channel_config_company_active",
        "sales_channel_config",
        ["company_id", "active", "marketplace"],
        schema="sales",
    )

    op.create_table(
        "external_order_mapping",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marketplace", sa.String(24), nullable=False),
        sa.Column("listing_id", sa.String(128), nullable=False),
        sa.Column("variation_id", sa.String(128), nullable=False),
        sa.Column("external_sku", sa.String(128), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            f"marketplace IN {_MARKETPLACES}",
            name=op.f("ck_external_order_mapping_marketplace"),
        ),
        sa.CheckConstraint(
            "length(btrim(listing_id)) BETWEEN 1 AND 128 "
            "AND listing_id = btrim(listing_id)",
            name=op.f("ck_external_order_mapping_listing_id"),
        ),
        sa.CheckConstraint(
            "length(btrim(variation_id)) BETWEEN 1 AND 128 "
            "AND variation_id = btrim(variation_id)",
            name=op.f("ck_external_order_mapping_variation_id"),
        ),
        sa.CheckConstraint(
            "length(btrim(external_sku)) BETWEEN 1 AND 128 "
            "AND external_sku = btrim(external_sku)",
            name=op.f("ck_external_order_mapping_external_sku"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_external_order_mapping_version")
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "channel_config_id"],
            ["sales.sales_channel_config.company_id", "sales.sales_channel_config.id"],
            name="fk_external_order_mapping_channel_config",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_external_order_mapping_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_order_mapping")),
        sa.UniqueConstraint(
            "company_id", "id", name=op.f("uq_external_order_mapping_company_id")
        ),
        sa.UniqueConstraint(
            "company_id",
            "channel_config_id",
            "listing_id",
            "variation_id",
            name=op.f("uq_external_order_mapping_listing"),
        ),
        schema="sales",
    )
    op.create_index(
        "ix_external_order_mapping_company_sku",
        "external_order_mapping",
        ["company_id", "channel_config_id", "external_sku"],
        schema="sales",
    )
    op.create_index(
        "ix_external_order_mapping_company_product",
        "external_order_mapping",
        ["company_id", "product_id"],
        schema="sales",
    )

    op.create_table(
        "sales_order",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel_config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("marketplace", sa.String(24), nullable=False),
        sa.Column("external_order_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("merchandise_amount", sa.Numeric(24, 2), nullable=False),
        sa.Column("freight_amount", sa.Numeric(24, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(24, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(24, 2), nullable=False),
        sa.Column(
            "items", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("source_payload_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            f"marketplace IN {_MARKETPLACES}",
            name=op.f("ck_sales_order_marketplace"),
        ),
        sa.CheckConstraint(
            f"status IN {_ORDER_STATUSES}", name=op.f("ck_sales_order_channel_status")
        ),
        sa.CheckConstraint("currency = 'BRL'", name=op.f("ck_sales_order_channel_currency")),
        sa.CheckConstraint(
            "length(btrim(external_order_id)) BETWEEN 1 AND 128 "
            "AND external_order_id = btrim(external_order_id)",
            name=op.f("ck_sales_order_external_order_id"),
        ),
        sa.CheckConstraint(
            "merchandise_amount >= 0 AND freight_amount >= 0 "
            "AND discount_amount >= 0 AND total_amount >= 0",
            name=op.f("ck_sales_order_channel_amounts"),
        ),
        sa.CheckConstraint(
            "total_amount = merchandise_amount - discount_amount + freight_amount",
            name=op.f("ck_sales_order_channel_total"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(items) = 'array' AND jsonb_array_length(items) > 0",
            name=op.f("ck_sales_order_channel_items"),
        ),
        sa.CheckConstraint(
            "source_payload_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_sales_order_source_payload_hash"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_sales_order_channel_version")),
        sa.ForeignKeyConstraint(
            ["company_id", "channel_config_id"],
            ["sales.sales_channel_config.company_id", "sales.sales_channel_config.id"],
            name="fk_sales_order_channel_config",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_order")),
        sa.UniqueConstraint(
            "company_id", "id", name=op.f("uq_sales_order_channel_company_id")
        ),
        sa.UniqueConstraint(
            "company_id",
            "marketplace",
            "account_id",
            "external_order_id",
            name="uq_sales_order_external_identity",
        ),
        schema="sales",
    )
    op.create_index(
        "ix_sales_order_channel_company_status",
        "sales_order",
        ["company_id", "status", "created_at"],
        schema="sales",
    )
    op.create_index(
        "ix_sales_order_channel_company_external",
        "sales_order",
        ["company_id", "marketplace", "account_id", "external_order_id"],
        schema="sales",
    )


def downgrade() -> None:
    op.drop_table("sales_order", schema="sales")
    op.drop_table("external_order_mapping", schema="sales")
    op.drop_table("sales_channel_config", schema="sales")
    op.execute("DROP SCHEMA IF EXISTS sales")
