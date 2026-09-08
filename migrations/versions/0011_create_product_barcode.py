"""Create tenant-unique product barcodes with a composite ownership FK."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_product_company_id", "product", ["company_id", "id"], schema="product"
    )
    op.create_table(
        "product_barcode",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("barcode_type", sa.String(8), nullable=False),
        sa.Column("barcode", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.UniqueConstraint("company_id", "barcode", name="uq_product_barcode_company_value"),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_product_barcode_company_product",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "barcode_type IN ('EAN', 'DUN', 'INTERNAL')", name=op.f("ck_product_barcode_type")
        ),
        sa.CheckConstraint(
            "barcode ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_product_barcode_value")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_product_barcode_version_positive")),
        schema="product",
    )
    op.create_index(
        "ix_product_barcode_company_product",
        "product_barcode",
        ["company_id", "product_id"],
        schema="product",
    )


def downgrade() -> None:
    op.drop_table("product_barcode", schema="product")
    op.drop_constraint("uq_product_company_id", "product", schema="product", type_="unique")
