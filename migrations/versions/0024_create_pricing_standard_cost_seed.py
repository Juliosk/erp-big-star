"""Create provisional M9 standard cost seed.

Revision ID: 0024
Revises: 0023
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add transient LEGACY_OPENING costs until M8 Costing is available."""
    op.create_table(
        "standard_cost_seed",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cost_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("cost_amount >= 0", name=op.f("ck_standard_cost_seed_cost_non_negative")),
        sa.CheckConstraint("currency = 'BRL'", name=op.f("ck_standard_cost_seed_currency_brl")),
        sa.CheckConstraint(
            "source = 'LEGACY_OPENING'",
            name=op.f("ck_standard_cost_seed_source_legacy_opening"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_standard_cost_seed_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_standard_cost_seed_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name=op.f("fk_standard_cost_seed_product"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_standard_cost_seed")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_standard_cost_seed_company_id")),
        sa.UniqueConstraint(
            "company_id", "product_id", name=op.f("uq_standard_cost_seed_product")
        ),
        schema="pricing",
    )
    op.create_index(
        "ix_standard_cost_seed_product",
        "standard_cost_seed",
        ["company_id", "product_id"],
        schema="pricing",
    )


def downgrade() -> None:
    """Drop the provisional cost seed table."""
    op.drop_index("ix_standard_cost_seed_product", table_name="standard_cost_seed", schema="pricing")
    op.drop_table("standard_cost_seed", schema="pricing")
