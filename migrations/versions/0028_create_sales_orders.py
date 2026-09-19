"""Create M4 sales orders. Revision ID: 0028. Revises: 0027."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales_order",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("number", sa.String(64), nullable=False),
        sa.Column("source_quote_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_quote_revision_number", sa.Integer(), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seller_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("gross_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("net_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("number ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_sales_order_number_format")),
        sa.CheckConstraint("currency = 'BRL'", name=op.f("ck_sales_order_currency")),
        sa.CheckConstraint("status IN ('DRAFT', 'APPROVED', 'CANCELLED', 'COMPLETED')", name=op.f("ck_sales_order_status")),
        sa.CheckConstraint("source_quote_revision_number >= 1", name=op.f("ck_sales_order_revision_positive")),
        sa.CheckConstraint("gross_amount >= 0", name=op.f("ck_sales_order_gross_non_negative")),
        sa.CheckConstraint("discount_amount >= 0", name=op.f("ck_sales_order_discount_non_negative")),
        sa.CheckConstraint("net_amount = gross_amount - discount_amount", name=op.f("ck_sales_order_net_total")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_sales_order_version_positive")),
        sa.ForeignKeyConstraint(["company_id"], ["admin.company.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "source_quote_id"], ["sales_b2b.sales_quote.company_id", "sales_b2b.sales_quote.id"], name="fk_sales_order_quote", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "customer_id"], ["crm.customer.company_id", "crm.customer.id"], name="fk_sales_order_customer", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_order")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_sales_order_company_id")),
        sa.UniqueConstraint("company_id", "number", name=op.f("uq_sales_order_company_number")),
        sa.UniqueConstraint("company_id", "source_quote_id", name=op.f("uq_sales_order_source_quote")),
        schema="sales_b2b",
    )
    op.create_index("ix_sales_order_company_status", "sales_order", ["company_id", "status", "created_at"], schema="sales_b2b")
    op.create_index("ix_sales_order_customer", "sales_order", ["company_id", "customer_id", "created_at"], schema="sales_b2b")
    op.create_table(
        "sales_order_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quote_revision_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("pricing_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_sales_order_item_quantity_positive")),
        sa.CheckConstraint("unit_price >= 0", name=op.f("ck_sales_order_item_unit_price_non_negative")),
        sa.CheckConstraint("discount_amount >= 0", name=op.f("ck_sales_order_item_discount_non_negative")),
        sa.ForeignKeyConstraint(["company_id", "order_id"], ["sales_b2b.sales_order.company_id", "sales_b2b.sales_order.id"], name="fk_sales_order_item_order", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "quote_revision_item_id"], ["sales_b2b.quote_revision_item.company_id", "sales_b2b.quote_revision_item.id"], name="fk_sales_order_item_quote_item", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "product_id"], ["product.product.company_id", "product.product.id"], name="fk_sales_order_item_product", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "pricing_snapshot_id"], ["pricing.pricing_snapshot.company_id", "pricing.pricing_snapshot.id"], name="fk_sales_order_item_snapshot", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_order_item")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_sales_order_item_company_id")),
        sa.UniqueConstraint("company_id", "order_id", "product_id", name=op.f("uq_sales_order_item_product")),
        schema="sales_b2b",
    )
    op.create_index("ix_sales_order_item_parent", "sales_order_item", ["company_id", "order_id"], schema="sales_b2b")


def downgrade() -> None:
    op.drop_table("sales_order_item", schema="sales_b2b")
    op.drop_table("sales_order", schema="sales_b2b")
