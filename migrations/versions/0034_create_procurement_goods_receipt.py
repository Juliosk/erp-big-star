"""Create M6 physical goods receipt persistence. Revision ID: 0034. Revises: 0033."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goods_receipt",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(64), nullable=False),
        sa.Column("purchase_order_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("received_by", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("physically_received_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("ck_goods_receipt_number_format"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'RECEIVED', 'INSPECTED', 'POSTED', 'REJECTED')",
            name=op.f("ck_goods_receipt_status"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_goods_receipt_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            ondelete="RESTRICT",
            name=op.f("fk_goods_receipt_company_id_company"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "purchase_order_id"],
            ["procurement.purchase_order.company_id", "procurement.purchase_order.id"],
            name="fk_goods_receipt_company_purchase_order",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_goods_receipt")),
        sa.UniqueConstraint("company_id", "id", name="uq_goods_receipt_company_id"),
        sa.UniqueConstraint("company_id", "number", name="uq_goods_receipt_company_number"),
        schema="procurement",
    )
    op.create_index(
        "ix_goods_receipt_company_status",
        "goods_receipt",
        ["company_id", "status", "id"],
        schema="procurement",
    )
    op.create_index(
        "ix_goods_receipt_company_order",
        "goods_receipt",
        ["company_id", "purchase_order_id", "id"],
        schema="procurement",
    )
    op.create_table(
        "receipt_item",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("goods_receipt_id", sa.Uuid(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("purchase_order_item_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("ordered_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("previously_received_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("expected_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("received_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("tolerance_percentage", sa.Numeric(7, 4), nullable=False),
        sa.Column("specification_conforms", sa.Boolean(), nullable=False),
        sa.Column("discrepancy_note", sa.String(1000), nullable=True),
        sa.Column("lot_reference", sa.String(64), nullable=True),
        sa.Column("inspection_id", sa.Uuid(), nullable=True),
        sa.Column("inspection_disposition", sa.String(24), nullable=True),
        sa.Column(
            "approved_quantity", sa.Numeric(18, 6), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "rejected_quantity", sa.Numeric(18, 6), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "quarantine_quantity", sa.Numeric(18, 6), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("inspection_reason_code", sa.String(64), nullable=True),
        sa.Column("available_posting_request_id", sa.Uuid(), nullable=True),
        sa.Column("quarantine_posting_request_id", sa.Uuid(), nullable=True),
        sa.Column("available_inventory_transaction_id", sa.Uuid(), nullable=True),
        sa.Column("quarantine_inventory_transaction_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("line_number >= 1", name=op.f("ck_receipt_item_line_number_positive")),
        sa.CheckConstraint(
            "ordered_quantity > 0", name=op.f("ck_receipt_item_ordered_quantity_positive")
        ),
        sa.CheckConstraint(
            "previously_received_quantity >= 0",
            name=op.f("ck_receipt_item_previously_received_non_negative"),
        ),
        sa.CheckConstraint(
            "expected_quantity > 0", name=op.f("ck_receipt_item_expected_quantity_positive")
        ),
        sa.CheckConstraint(
            "received_quantity > 0", name=op.f("ck_receipt_item_received_quantity_positive")
        ),
        sa.CheckConstraint(
            "tolerance_percentage >= 0 AND tolerance_percentage <= 100",
            name=op.f("ck_receipt_item_tolerance_range"),
        ),
        sa.CheckConstraint(
            "approved_quantity >= 0", name=op.f("ck_receipt_item_approved_quantity_non_negative")
        ),
        sa.CheckConstraint(
            "rejected_quantity >= 0", name=op.f("ck_receipt_item_rejected_quantity_non_negative")
        ),
        sa.CheckConstraint(
            "quarantine_quantity >= 0",
            name=op.f("ck_receipt_item_quarantine_quantity_non_negative"),
        ),
        sa.CheckConstraint(
            "inspection_disposition IS NULL OR inspection_disposition IN "
            "('APPROVE', 'PARTIAL_ACCEPTANCE', 'REJECT', 'QUARANTINE')",
            name=op.f("ck_receipt_item_inspection_disposition"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "goods_receipt_id"],
            ["procurement.goods_receipt.company_id", "procurement.goods_receipt.id"],
            name="fk_receipt_item_company_receipt",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "purchase_order_item_id"],
            ["procurement.purchase_order_item.company_id", "procurement.purchase_order_item.id"],
            name="fk_receipt_item_company_order_item",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_receipt_item")),
        sa.UniqueConstraint("company_id", "id", name="uq_receipt_item_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "goods_receipt_id",
            "purchase_order_item_id",
            name="uq_receipt_item_order_item",
        ),
        sa.UniqueConstraint(
            "company_id",
            "goods_receipt_id",
            "line_number",
            name="uq_receipt_item_line_number",
        ),
        schema="procurement",
    )
    op.create_index(
        "ix_receipt_item_receipt",
        "receipt_item",
        ["company_id", "goods_receipt_id", "id"],
        schema="procurement",
    )


def downgrade() -> None:
    op.drop_table("receipt_item", schema="procurement")
    op.drop_table("goods_receipt", schema="procurement")
