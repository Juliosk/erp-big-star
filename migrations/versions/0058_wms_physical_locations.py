"""Create tenant-bound WMS physical location hierarchy.

Revision ID: 0058
Revises: 0057
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0058"
down_revision: str | None = "0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STORAGE_TYPES = "('PICKING', 'RESERVE', 'DAMAGED', 'QUARANTINE')"


def upgrade() -> None:
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS wms"))
    op.create_table(
        "wms_zone",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("storage_type", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_]{0,15}$'", name=op.f("ck_wms_zone_code")),
        sa.CheckConstraint(f"storage_type IN {_STORAGE_TYPES}", name=op.f("ck_wms_zone_storage_type")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_wms_zone_version")),
        sa.ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_wms_zone_warehouse",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wms_zone")),
        sa.UniqueConstraint("company_id", "warehouse_id", "id", name="uq_wms_zone_scope_id"),
        sa.UniqueConstraint("company_id", "warehouse_id", "code", name="uq_wms_zone_address"),
        schema="wms",
    )
    op.create_index(
        "ix_wms_zone_company_warehouse_type",
        "wms_zone",
        ["company_id", "warehouse_id", "storage_type", "code"],
        schema="wms",
    )

    op.create_table(
        "wms_aisle",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("zone_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_]{0,15}$'", name=op.f("ck_wms_aisle_code")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_wms_aisle_version")),
        sa.ForeignKeyConstraint(
            ["company_id", "warehouse_id", "zone_id"],
            ["wms.wms_zone.company_id", "wms.wms_zone.warehouse_id", "wms.wms_zone.id"],
            name="fk_wms_aisle_zone",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wms_aisle")),
        sa.UniqueConstraint("company_id", "warehouse_id", "id", name="uq_wms_aisle_scope_id"),
        sa.UniqueConstraint(
            "company_id", "warehouse_id", "zone_id", "code", name="uq_wms_aisle_address"
        ),
        schema="wms",
    )
    op.create_index(
        "ix_wms_aisle_hierarchy",
        "wms_aisle",
        ["company_id", "warehouse_id", "zone_id", "code"],
        schema="wms",
    )

    op.create_table(
        "wms_bay",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aisle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_]{0,15}$'", name=op.f("ck_wms_bay_code")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_wms_bay_version")),
        sa.ForeignKeyConstraint(
            ["company_id", "warehouse_id", "aisle_id"],
            ["wms.wms_aisle.company_id", "wms.wms_aisle.warehouse_id", "wms.wms_aisle.id"],
            name="fk_wms_bay_aisle",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wms_bay")),
        sa.UniqueConstraint("company_id", "warehouse_id", "id", name="uq_wms_bay_scope_id"),
        sa.UniqueConstraint(
            "company_id", "warehouse_id", "aisle_id", "code", name="uq_wms_bay_address"
        ),
        schema="wms",
    )
    op.create_index(
        "ix_wms_bay_hierarchy",
        "wms_bay",
        ["company_id", "warehouse_id", "aisle_id", "code"],
        schema="wms",
    )

    op.create_table(
        "wms_level",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bay_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_]{0,15}$'", name=op.f("ck_wms_level_code")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_wms_level_version")),
        sa.ForeignKeyConstraint(
            ["company_id", "warehouse_id", "bay_id"],
            ["wms.wms_bay.company_id", "wms.wms_bay.warehouse_id", "wms.wms_bay.id"],
            name="fk_wms_level_bay",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wms_level")),
        sa.UniqueConstraint("company_id", "warehouse_id", "id", name="uq_wms_level_scope_id"),
        sa.UniqueConstraint(
            "company_id", "warehouse_id", "bay_id", "code", name="uq_wms_level_address"
        ),
        schema="wms",
    )
    op.create_index(
        "ix_wms_level_hierarchy",
        "wms_level",
        ["company_id", "warehouse_id", "bay_id", "code"],
        schema="wms",
    )

    op.create_table(
        "wms_bin",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("level_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(16), nullable=False),
        sa.Column("address_code", sa.String(84), nullable=False),
        sa.Column("occupied_units", sa.Integer(), server_default="0", nullable=False),
        sa.Column("used_weight", sa.Numeric(24, 6), server_default="0", nullable=False),
        sa.Column("used_volume", sa.Numeric(36, 18), server_default="0", nullable=False),
        sa.Column("blocked", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9_]{0,15}$'", name=op.f("ck_wms_bin_code")),
        sa.CheckConstraint(
            "address_code ~ '^[A-Z0-9_]{1,16}/[A-Z0-9_]{1,16}/[A-Z0-9_]{1,16}/"
            "[A-Z0-9_]{1,16}/[A-Z0-9_]{1,16}$'",
            name=op.f("ck_wms_bin_address_code"),
        ),
        sa.CheckConstraint("occupied_units >= 0", name=op.f("ck_wms_bin_occupied_units")),
        sa.CheckConstraint("used_weight >= 0", name=op.f("ck_wms_bin_used_weight")),
        sa.CheckConstraint("used_volume >= 0", name=op.f("ck_wms_bin_used_volume")),
        sa.CheckConstraint(
            "(occupied_units = 0 AND used_weight = 0 AND used_volume = 0) OR "
            "(occupied_units > 0 AND used_weight > 0 AND used_volume > 0)",
            name=op.f("ck_wms_bin_empty_consistency"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_wms_bin_version")),
        sa.ForeignKeyConstraint(
            ["company_id", "warehouse_id", "level_id"],
            ["wms.wms_level.company_id", "wms.wms_level.warehouse_id", "wms.wms_level.id"],
            name="fk_wms_bin_level",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "id"],
            ["inventory.location.company_id", "inventory.location.id"],
            name="fk_wms_bin_inventory_location",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wms_bin")),
        sa.UniqueConstraint("company_id", "id", name="uq_wms_bin_company_id"),
        sa.UniqueConstraint(
            "company_id", "warehouse_id", "address_code", name="uq_wms_bin_cartesian_address"
        ),
        schema="wms",
    )
    op.create_index(
        "ix_wms_bin_hierarchy",
        "wms_bin",
        ["company_id", "warehouse_id", "level_id", "code"],
        schema="wms",
    )
    op.create_index(
        "ix_wms_bin_spatial_address",
        "wms_bin",
        ["company_id", "warehouse_id", "address_code"],
        schema="wms",
    )
    op.create_index(
        "ix_wms_bin_occupancy",
        "wms_bin",
        ["company_id", "warehouse_id", "blocked", "occupied_units"],
        schema="wms",
    )

    op.create_table(
        "wms_bin_capacity",
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("width", sa.Numeric(18, 6), nullable=False),
        sa.Column("depth", sa.Numeric(18, 6), nullable=False),
        sa.Column("height", sa.Numeric(18, 6), nullable=False),
        sa.Column("max_weight", sa.Numeric(24, 6), nullable=False),
        sa.Column("max_units", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("width > 0 AND depth > 0 AND height > 0", name=op.f("ck_wms_bin_capacity_dimensions")),
        sa.CheckConstraint("max_weight > 0", name=op.f("ck_wms_bin_capacity_weight")),
        sa.CheckConstraint("max_units BETWEEN 1 AND 1000000", name=op.f("ck_wms_bin_capacity_units")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_wms_bin_capacity_version")),
        sa.ForeignKeyConstraint(
            ["company_id", "bin_id"],
            ["wms.wms_bin.company_id", "wms.wms_bin.id"],
            name="fk_wms_bin_capacity_bin",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("company_id", "bin_id", name=op.f("pk_wms_bin_capacity")),
        schema="wms",
    )
    op.create_index(
        "ix_wms_bin_capacity_search",
        "wms_bin_capacity",
        ["company_id", "max_units", "max_weight"],
        schema="wms",
    )


def downgrade() -> None:
    op.drop_table("wms_bin_capacity", schema="wms")
    op.drop_table("wms_bin", schema="wms")
    op.drop_table("wms_level", schema="wms")
    op.drop_table("wms_bay", schema="wms")
    op.drop_table("wms_aisle", schema="wms")
    op.drop_table("wms_zone", schema="wms")
