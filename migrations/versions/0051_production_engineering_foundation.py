"""Create tenant-bound Production engineering structures.

Revision ID: 0051
Revises: 0050
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0051"
down_revision: str | None = "0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UOM_CHECK = "uom IN ('EA', 'KG', 'G', 'L', 'ML', 'M', 'M2')"


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema("production"))
    op.create_table(
        "work_center",
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'", name="ck_work_center_code"),
        sa.CheckConstraint("jsonb_typeof(capabilities) = 'array'", name="ck_work_center_capabilities"),
        sa.CheckConstraint("version >= 1", name="ck_work_center_version"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_work_center_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("company_id", "code", name="pk_work_center"),
        schema="production",
    )

    op.create_table(
        "bom_header",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("version_code", sa.String(32), nullable=False),
        sa.Column("engineering_revision", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("output_quantity", sa.Numeric(24, 6), nullable=False),
        sa.Column("output_uom", sa.String(12), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "version_code ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'",
            name="ck_bom_header_version_code",
        ),
        sa.CheckConstraint("engineering_revision >= 1", name="ck_bom_header_revision"),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_bom_header_effective_range",
        ),
        sa.CheckConstraint("output_quantity > 0", name="ck_bom_header_output_quantity"),
        sa.CheckConstraint(_UOM_CHECK.replace("uom", "output_uom"), name="ck_bom_header_output_uom"),
        sa.CheckConstraint("version >= 1", name="ck_bom_header_version"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_bom_header_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_bom_header_company_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bom_header"),
        sa.UniqueConstraint("company_id", "id", name="uq_bom_header_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "product_id",
            "version_code",
            name="uq_bom_header_company_product_version",
        ),
        schema="production",
    )
    op.create_index(
        "ix_bom_header_company_product",
        "bom_header",
        ["company_id", "product_id", "version_code"],
        schema="production",
    )

    op.create_table(
        "bom_component",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("bom_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("component_product_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_per_output", sa.Numeric(24, 6), nullable=False),
        sa.Column("uom", sa.String(12), nullable=False),
        sa.Column("scrap_rate", sa.Numeric(9, 6), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_bom_component_sequence"),
        sa.CheckConstraint("quantity_per_output > 0", name="ck_bom_component_quantity"),
        sa.CheckConstraint(_UOM_CHECK, name="ck_bom_component_uom"),
        sa.CheckConstraint("scrap_rate >= 0 AND scrap_rate < 1", name="ck_bom_component_scrap"),
        sa.CheckConstraint("version >= 1", name="ck_bom_component_version"),
        sa.ForeignKeyConstraint(
            ["company_id", "bom_id"],
            ["production.bom_header.company_id", "production.bom_header.id"],
            name="fk_bom_component_company_header",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "component_product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_bom_component_company_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_bom_component"),
        sa.UniqueConstraint(
            "company_id", "bom_id", "sequence", name="uq_bom_component_sequence"
        ),
        sa.UniqueConstraint(
            "company_id",
            "bom_id",
            "component_product_id",
            name="uq_bom_component_product",
        ),
        schema="production",
    )
    op.create_index(
        "ix_bom_component_company_product",
        "bom_component",
        ["company_id", "component_product_id", "bom_id"],
        schema="production",
    )
    op.create_index(
        "ix_bom_component_company_header",
        "bom_component",
        ["company_id", "bom_id", "sequence"],
        schema="production",
    )

    op.create_table(
        "routing_header",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("version_code", sa.String(32), nullable=False),
        sa.Column("engineering_revision", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "version_code ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'",
            name="ck_routing_header_version_code",
        ),
        sa.CheckConstraint("engineering_revision >= 1", name="ck_routing_header_revision"),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_routing_header_effective_range",
        ),
        sa.CheckConstraint("version >= 1", name="ck_routing_header_version"),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_routing_header_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_routing_header_company_product",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_routing_header"),
        sa.UniqueConstraint("company_id", "id", name="uq_routing_header_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "product_id",
            "version_code",
            name="uq_routing_header_company_product_version",
        ),
        schema="production",
    )
    op.create_index(
        "ix_routing_header_company_product",
        "routing_header",
        ["company_id", "product_id", "version_code"],
        schema="production",
    )

    op.create_table(
        "routing_operation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("routing_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("setup_minutes", sa.Numeric(18, 6), nullable=False),
        sa.Column("run_minutes_per_unit", sa.Numeric(18, 6), nullable=False),
        sa.Column("allowed_work_centers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("required_capabilities", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_routing_operation_sequence"),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 120 AND name = btrim(name)",
            name="ck_routing_operation_name",
        ),
        sa.CheckConstraint("setup_minutes >= 0", name="ck_routing_operation_setup"),
        sa.CheckConstraint("run_minutes_per_unit > 0", name="ck_routing_operation_run"),
        sa.CheckConstraint(
            "jsonb_typeof(allowed_work_centers) = 'array' "
            "AND jsonb_array_length(allowed_work_centers) > 0",
            name="ck_routing_operation_centers",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(required_capabilities) = 'array'",
            name="ck_routing_operation_capabilities",
        ),
        sa.CheckConstraint("version >= 1", name="ck_routing_operation_version"),
        sa.ForeignKeyConstraint(
            ["company_id", "routing_id"],
            ["production.routing_header.company_id", "production.routing_header.id"],
            name="fk_routing_operation_company_header",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_routing_operation"),
        sa.UniqueConstraint(
            "company_id", "routing_id", "sequence", name="uq_routing_operation_sequence"
        ),
        schema="production",
    )
    op.create_index(
        "ix_routing_operation_company_header",
        "routing_operation",
        ["company_id", "routing_id", "sequence"],
        schema="production",
    )


def downgrade() -> None:
    op.drop_table("routing_operation", schema="production")
    op.drop_table("routing_header", schema="production")
    op.drop_table("bom_component", schema="production")
    op.drop_table("bom_header", schema="production")
    op.drop_table("work_center", schema="production")
    op.execute(sa.schema.DropSchema("production"))

