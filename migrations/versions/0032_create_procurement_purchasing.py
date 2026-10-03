"""Create M6 requisition and purchase order tables. Revision ID: 0032. Revises: 0031."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "purchase_requisition",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(64), nullable=False),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("cost_center_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("justification", sa.String(1000), nullable=False),
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
            "number ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'",
            name=op.f("ck_purchase_requisition_number_format"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'CANCELLED')",
            name=op.f("ck_purchase_requisition_status"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_purchase_requisition_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            ondelete="RESTRICT",
            name=op.f("fk_purchase_requisition_company_id_company"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_requisition")),
        sa.UniqueConstraint("company_id", "id", name="uq_purchase_requisition_company_id"),
        sa.UniqueConstraint("company_id", "number", name="uq_purchase_requisition_company_number"),
        schema="procurement",
    )
    op.create_index(
        "ix_purchase_requisition_company_status",
        "purchase_requisition",
        ["company_id", "status", "id"],
        schema="procurement",
    )
    op.create_table(
        "requisition_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("requisition_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_of_measure", sa.String(16), nullable=False),
        sa.Column("needed_by", sa.Date(), nullable=False),
        sa.Column("urgency", sa.String(16), nullable=False),
        sa.Column("specification", sa.String(1000), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_requisition_item_quantity_positive")),
        sa.CheckConstraint(
            "unit_of_measure ~ '^[A-Z0-9][A-Z0-9._-]{0,15}$'",
            name=op.f("ck_requisition_item_uom_format"),
        ),
        sa.CheckConstraint(
            "urgency IN ('LOW', 'NORMAL', 'HIGH', 'CRITICAL')",
            name=op.f("ck_requisition_item_urgency"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "requisition_id"],
            ["procurement.purchase_requisition.company_id", "procurement.purchase_requisition.id"],
            name="fk_requisition_item_company_requisition",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_requisition_item_company_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requisition_item")),
        sa.UniqueConstraint("company_id", "id", name="uq_requisition_item_company_id"),
        sa.UniqueConstraint(
            "company_id", "requisition_id", "product_id", name="uq_requisition_item_product"
        ),
        schema="procurement",
    )
    op.create_index(
        "ix_requisition_item_requisition",
        "requisition_item",
        ["company_id", "requisition_id", "id"],
        schema="procurement",
    )
    op.create_table(
        "purchase_order",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(64), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("source_requisition_id", sa.Uuid(), nullable=False),
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("payment_terms_code", sa.String(32), nullable=False),
        sa.Column("payment_terms_description", sa.String(200), nullable=False),
        sa.Column("payment_installment_days", sa.ARRAY(sa.Integer()), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("total_amount", sa.Numeric(18, 2), nullable=False),
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
            "number ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_purchase_order_number_format")
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name=op.f("ck_purchase_order_currency_format")
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'ISSUED', 'PARTIALLY_RECEIVED', 'COMPLETED', 'CANCELLED')",
            name=op.f("ck_purchase_order_status"),
        ),
        sa.CheckConstraint("total_amount >= 0", name=op.f("ck_purchase_order_total_non_negative")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_purchase_order_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            ondelete="RESTRICT",
            name=op.f("fk_purchase_order_company_id_company"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "supplier_id"],
            ["procurement.supplier.company_id", "procurement.supplier.id"],
            name="fk_purchase_order_company_supplier",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "source_requisition_id"],
            ["procurement.purchase_requisition.company_id", "procurement.purchase_requisition.id"],
            name="fk_purchase_order_company_requisition",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_order")),
        sa.UniqueConstraint("company_id", "id", name="uq_purchase_order_company_id"),
        sa.UniqueConstraint("company_id", "number", name="uq_purchase_order_company_number"),
        schema="procurement",
    )
    op.create_index(
        "ix_purchase_order_company_status",
        "purchase_order",
        ["company_id", "status", "id"],
        schema="procurement",
    )
    op.create_table(
        "purchase_order_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("requisition_item_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("received_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_purchase_order_item_quantity_positive")),
        sa.CheckConstraint(
            "unit_price >= 0", name=op.f("ck_purchase_order_item_unit_price_non_negative")
        ),
        sa.CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= quantity",
            name=op.f("ck_purchase_order_item_receipt_range"),
        ),
        sa.CheckConstraint(
            "currency ~ '^[A-Z]{3}$'", name=op.f("ck_purchase_order_item_currency_format")
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "purchase_order_id"],
            ["procurement.purchase_order.company_id", "procurement.purchase_order.id"],
            name="fk_purchase_order_item_company_order",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "requisition_item_id"],
            ["procurement.requisition_item.company_id", "procurement.requisition_item.id"],
            name="fk_purchase_order_item_company_requisition_item",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_purchase_order_item_company_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_order_item")),
        sa.UniqueConstraint("company_id", "id", name="uq_purchase_order_item_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "purchase_order_id",
            "requisition_item_id",
            name="uq_purchase_order_item_requisition_item",
        ),
        schema="procurement",
    )
    op.create_index(
        "ix_purchase_order_item_order",
        "purchase_order_item",
        ["company_id", "purchase_order_id", "id"],
        schema="procurement",
    )


def downgrade() -> None:
    op.drop_table("purchase_order_item", schema="procurement")
    op.drop_table("purchase_order", schema="procurement")
    op.drop_table("requisition_item", schema="procurement")
    op.drop_table("purchase_requisition", schema="procurement")
