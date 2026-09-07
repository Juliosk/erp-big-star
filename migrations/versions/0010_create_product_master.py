"""Create the company-owned M2 product master.

Revision ID: 0010
Revises: 0009
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add M2 without modifying any existing business table."""
    op.execute(sa.schema.CreateSchema("product"))
    op.create_table(
        "product",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("sku", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("product_type", sa.String(3), nullable=False),
        sa.Column("uom", sa.String(12), nullable=False),
        sa.Column("lifecycle", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_product_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("sku", name="uq_product_sku"),
        sa.UniqueConstraint("company_id", "code", name="uq_product_company_code"),
        sa.CheckConstraint(
            "code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_product_code_format")
        ),
        sa.CheckConstraint(
            "sku ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_product_sku_format")
        ),
        sa.CheckConstraint(
            "uom ~ '^[A-Z0-9][A-Z0-9._-]{0,11}$'", name=op.f("ck_product_uom_format")
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 200 AND name = btrim(name)",
            name=op.f("ck_product_name_length"),
        ),
        sa.CheckConstraint(
            "product_type IN ('PA', 'PI', 'MA', 'AUX', 'EMB', 'KIT')", name=op.f("ck_product_type")
        ),
        sa.CheckConstraint(
            "lifecycle IN ('EM_DESENVOLVIMENTO', 'EM_HOMOLOGACAO', 'ATIVO', 'FORA_DE_LINHA')",
            name=op.f("ck_product_lifecycle"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_product_version_positive")),
        schema="product",
    )
    op.create_index(
        "ix_product_company_code", "product", ["company_id", "code", "id"], schema="product"
    )
    op.create_index(
        "ix_product_company_lifecycle", "product", ["company_id", "lifecycle"], schema="product"
    )


def downgrade() -> None:
    """Destructive for M2 data; use only with explicit approval and a backup."""
    op.drop_table("product", schema="product")
    op.execute(sa.schema.DropSchema("product"))
