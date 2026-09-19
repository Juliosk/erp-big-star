"""Create M4 order reservation projection. Revision ID: 0029. Revises: 0028."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales_order_reservation",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("inventory_reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("order_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("status IN ('REQUESTED', 'HELD', 'RELEASED', 'CANCELLED')", name=op.f("ck_sales_order_reservation_status")),
        sa.CheckConstraint("order_version >= 1", name=op.f("ck_sales_order_reservation_order_version_positive")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_sales_order_reservation_version_positive")),
        sa.ForeignKeyConstraint(["company_id"], ["admin.company.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "order_id"], ["sales_b2b.sales_order.company_id", "sales_b2b.sales_order.id"], name="fk_sales_order_reservation_order", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "inventory_reservation_id"], ["inventory.inventory_reservation.company_id", "inventory.inventory_reservation.id"], name="fk_sales_order_reservation_inventory", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_order_reservation")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_sales_order_reservation_company_id")),
        sa.UniqueConstraint("company_id", "order_id", name=op.f("uq_sales_order_reservation_order")),
        sa.UniqueConstraint("company_id", "inventory_reservation_id", name=op.f("uq_sales_order_reservation_inventory")),
        schema="sales_b2b",
    )
    op.create_index("ix_sales_order_reservation_status", "sales_order_reservation", ["company_id", "status", "created_at"], schema="sales_b2b")
    op.create_table(
        "sales_order_reservation_line",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("pricing_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_sales_order_reservation_line_quantity_positive")),
        sa.ForeignKeyConstraint(["company_id", "reservation_id"], ["sales_b2b.sales_order_reservation.company_id", "sales_b2b.sales_order_reservation.id"], name="fk_sales_order_reservation_line_parent", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "order_item_id"], ["sales_b2b.sales_order_item.company_id", "sales_b2b.sales_order_item.id"], name="fk_sales_order_reservation_line_order_item", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "product_id"], ["product.product.company_id", "product.product.id"], name="fk_sales_order_reservation_line_product", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "pricing_snapshot_id"], ["pricing.pricing_snapshot.company_id", "pricing.pricing_snapshot.id"], name="fk_sales_order_reservation_line_pricing_snapshot", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_order_reservation_line")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_sales_order_reservation_line_company_id")),
        sa.UniqueConstraint("company_id", "reservation_id", "order_item_id", name=op.f("uq_sales_order_reservation_line_item")),
        schema="sales_b2b",
    )
    op.create_index("ix_sales_order_reservation_line_parent", "sales_order_reservation_line", ["company_id", "reservation_id"], schema="sales_b2b")


def downgrade() -> None:
    op.drop_table("sales_order_reservation_line", schema="sales_b2b")
    op.drop_table("sales_order_reservation", schema="sales_b2b")
