"""Create M5 inventory foundation structures.

Revision ID: 0018
Revises: 0017
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add M5 physical stock foundation without introducing reservation rules."""
    op.execute(sa.schema.CreateSchema("inventory"))
    op.create_table(
        "warehouse",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warehouse")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_warehouse_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["branch_id"],
            ["admin.branch.id"],
            name=op.f("fk_warehouse_branch_id_branch"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_inventory_warehouse_company_id"),
        sa.UniqueConstraint("company_id", "code", name="uq_inventory_warehouse_company_code"),
        sa.CheckConstraint(
            "code ~ '^[A-Z0-9][A-Z0-9_-]{1,49}$'",
            name=op.f("ck_warehouse_code_format"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 120 AND name = btrim(name)",
            name=op.f("ck_warehouse_name_length"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_warehouse_version_positive")),
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_warehouse_company_active",
        "warehouse",
        ["company_id", "active", "code"],
        schema="inventory",
    )
    op.create_table(
        "location",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_location")),
        sa.ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_inventory_location_company_warehouse",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "parent_location_id"],
            ["inventory.location.company_id", "inventory.location.id"],
            name="fk_inventory_location_parent",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_inventory_location_company_id"),
        sa.UniqueConstraint(
            "company_id",
            "warehouse_id",
            "code",
            name="uq_inventory_location_company_warehouse_code",
        ),
        sa.CheckConstraint(
            "code ~ '^[A-Z0-9][A-Z0-9_-]{1,49}$'",
            name=op.f("ck_location_code_format"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 120 AND name = btrim(name)",
            name=op.f("ck_location_name_length"),
        ),
        sa.CheckConstraint(
            "parent_location_id IS NULL OR parent_location_id <> id",
            name=op.f("ck_location_not_own_parent"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_location_version_positive")),
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_location_company_warehouse",
        "location",
        ["company_id", "warehouse_id", "code"],
        schema="inventory",
    )
    op.create_table(
        "inventory_pool",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_pool")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_inventory_pool_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_inventory_pool_company_id"),
        sa.UniqueConstraint("company_id", "code", name="uq_inventory_pool_company_code"),
        sa.CheckConstraint(
            "code ~ '^[A-Z0-9][A-Z0-9_-]{1,49}$'",
            name=op.f("ck_inventory_pool_code_format"),
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 120 AND name = btrim(name)",
            name=op.f("ck_inventory_pool_name_length"),
        ),
        sa.CheckConstraint(
            "kind IN ('MARKETPLACE', 'B2B', 'STORE')",
            name=op.f("ck_inventory_pool_kind"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_inventory_pool_version_positive")),
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_pool_company_kind",
        "inventory_pool",
        ["company_id", "kind", "code"],
        schema="inventory",
    )
    op.create_table(
        "inventory_lot",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory_lot")),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_inventory_lot_company_product",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("company_id", "id", name="uq_inventory_lot_company_id"),
        sa.UniqueConstraint(
            "company_id", "product_id", "code", name="uq_inventory_lot_product_code"
        ),
        sa.CheckConstraint(
            "code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'",
            name=op.f("ck_inventory_lot_code_format"),
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'QUARANTINED', 'BLOCKED', 'CLOSED')",
            name=op.f("ck_inventory_lot_status"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_inventory_lot_version_positive")),
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_lot_company_product",
        "inventory_lot",
        ["company_id", "product_id", "status"],
        schema="inventory",
    )


def downgrade() -> None:
    """Destructive for M5 foundation data; use only with explicit approval and a backup."""
    op.drop_table("inventory_lot", schema="inventory")
    op.drop_table("inventory_pool", schema="inventory")
    op.drop_table("location", schema="inventory")
    op.drop_table("warehouse", schema="inventory")
    op.execute(sa.schema.DropSchema("inventory"))
