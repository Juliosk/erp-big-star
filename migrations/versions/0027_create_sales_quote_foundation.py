"""Create M15 B2B sales quote foundation.

Revision ID: 0027
Revises: 0026
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS sales_b2b"))
    op.create_table(
        "sales_quote",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.String(64), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("current_revision_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("workflow_instance_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("converted_order_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("number ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_sales_quote_number_format")),
        sa.CheckConstraint("currency = 'BRL'", name=op.f("ck_sales_quote_currency")),
        sa.CheckConstraint("status IN ('DRAFT', 'SENT', 'ACCEPTED', 'PARTIALLY_ACCEPTED', 'LOST', 'CONVERTED')", name=op.f("ck_sales_quote_status")),
        sa.CheckConstraint("current_revision_number >= 0", name=op.f("ck_sales_quote_revision_non_negative")),
        sa.CheckConstraint("status != 'CONVERTED' OR converted_order_id IS NOT NULL", name=op.f("ck_sales_quote_converted_requires_order")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_sales_quote_version_positive")),
        sa.ForeignKeyConstraint(["company_id"], ["admin.company.id"], name=op.f("fk_sales_quote_company_id_company"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "customer_id"], ["crm.customer.company_id", "crm.customer.id"], name="fk_sales_quote_customer", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_quote")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_sales_quote_company_id")),
        sa.UniqueConstraint("company_id", "number", name=op.f("uq_sales_quote_company_number")),
        schema="sales_b2b",
    )
    op.create_index("ix_sales_quote_company_status", "sales_quote", ["company_id", "status", "created_at"], schema="sales_b2b")
    op.create_index("ix_sales_quote_customer", "sales_quote", ["company_id", "customer_id", "created_at"], schema="sales_b2b")
    op.create_table(
        "quote_revision",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("revision_number >= 1", name=op.f("ck_quote_revision_revision_positive")),
        sa.CheckConstraint("gross_amount >= 0", name=op.f("ck_quote_revision_gross_non_negative")),
        sa.CheckConstraint("discount_amount >= 0", name=op.f("ck_quote_revision_discount_non_negative")),
        sa.CheckConstraint("net_amount = gross_amount - discount_amount", name=op.f("ck_quote_revision_net_total")),
        sa.ForeignKeyConstraint(["company_id", "quote_id"], ["sales_b2b.sales_quote.company_id", "sales_b2b.sales_quote.id"], name="fk_quote_revision_quote", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_revision")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_quote_revision_company_id")),
        sa.UniqueConstraint("company_id", "quote_id", "revision_number", name=op.f("uq_quote_revision_number")),
        schema="sales_b2b",
    )
    op.create_index("ix_quote_revision_parent", "quote_revision", ["company_id", "quote_id", "revision_number"], schema="sales_b2b")
    op.create_table(
        "quote_revision_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("pricing_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_quote_revision_item_quantity_positive")),
        sa.CheckConstraint("unit_price >= 0", name=op.f("ck_quote_revision_item_unit_price_non_negative")),
        sa.CheckConstraint("discount_amount >= 0", name=op.f("ck_quote_revision_item_discount_non_negative")),
        sa.CheckConstraint("discount_amount <= round(quantity * unit_price, 2)", name=op.f("ck_quote_revision_item_discount_not_above_gross")),
        sa.ForeignKeyConstraint(["company_id", "revision_id"], ["sales_b2b.quote_revision.company_id", "sales_b2b.quote_revision.id"], name="fk_quote_revision_item_revision", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "product_id"], ["product.product.company_id", "product.product.id"], name="fk_quote_revision_item_product", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "pricing_snapshot_id"], ["pricing.pricing_snapshot.company_id", "pricing.pricing_snapshot.id"], name="fk_quote_revision_item_pricing_snapshot", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quote_revision_item")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_quote_revision_item_company_id")),
        sa.UniqueConstraint("company_id", "revision_id", "product_id", name=op.f("uq_quote_revision_item_product")),
        schema="sales_b2b",
    )
    op.create_index("ix_quote_revision_item_parent", "quote_revision_item", ["company_id", "revision_id"], schema="sales_b2b")


def downgrade() -> None:
    op.drop_table("quote_revision_item", schema="sales_b2b")
    op.drop_table("quote_revision", schema="sales_b2b")
    op.drop_table("sales_quote", schema="sales_b2b")
    op.execute(sa.text("DROP SCHEMA IF EXISTS sales_b2b"))
