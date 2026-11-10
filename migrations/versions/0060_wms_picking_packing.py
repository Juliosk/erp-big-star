"""Create route-aware WMS picking, packing verification and manifests.

Revision ID: 0060
Revises: 0059
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0060"
down_revision: str | None = "0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WAVE_STATUSES = "('DRAFT', 'PACKING', 'MANIFESTED')"
_ITEM_STATUSES = "('OPEN', 'PICKED', 'PACKED')"


def upgrade() -> None:
    op.create_table(
        "wms_picking_wave",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("manifest_number", sa.String(64), nullable=True),
        sa.Column("manifested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'",
            name=op.f("ck_wms_picking_wave_code"),
        ),
        sa.CheckConstraint(
            f"status IN {_WAVE_STATUSES}",
            name=op.f("ck_wms_picking_wave_status"),
        ),
        sa.CheckConstraint(
            "(status = 'MANIFESTED') = (manifest_number IS NOT NULL AND manifested_at IS NOT NULL)",
            name=op.f("ck_wms_picking_wave_manifest"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_wms_picking_wave_version")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name="fk_wms_picking_wave_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_wms_picking_wave_warehouse_0060",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wms_picking_wave")),
        sa.UniqueConstraint("company_id", "id", name="uq_wms_picking_wave_0060_scope"),
        sa.UniqueConstraint("company_id", "code", name="uq_wms_picking_wave_0060_code"),
        sa.UniqueConstraint(
            "company_id",
            "manifest_number",
            name="uq_wms_picking_wave_0060_manifest",
        ),
        schema="wms",
    )
    op.create_index(
        "ix_wms_picking_wave_0060_queue",
        "wms_picking_wave",
        ["company_id", "warehouse_id", "status", "created_at", "id"],
        schema="wms",
    )

    op.create_table(
        "wms_picking_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wave_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sales_order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shipment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("bin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pool_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("barcode", sa.String(64), nullable=False),
        sa.Column("required_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("picked_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("packed_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("unit_weight", sa.Numeric(24, 6), nullable=False),
        sa.Column("unit_volume", sa.Numeric(36, 18), nullable=False),
        sa.Column("route_address", sa.String(84), nullable=False),
        sa.Column("route_sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "barcode ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'",
            name=op.f("ck_wms_picking_item_barcode"),
        ),
        sa.CheckConstraint(
            "required_quantity > 0 AND picked_quantity >= 0 AND packed_quantity >= 0",
            name=op.f("ck_wms_picking_item_quantities"),
        ),
        sa.CheckConstraint(
            "packed_quantity <= picked_quantity AND picked_quantity <= required_quantity",
            name=op.f("ck_wms_picking_item_quantity_order"),
        ),
        sa.CheckConstraint(
            "units >= 1 AND required_quantity = units",
            name=op.f("ck_wms_picking_item_units"),
        ),
        sa.CheckConstraint(
            "unit_weight > 0 AND unit_volume > 0",
            name=op.f("ck_wms_picking_item_measures"),
        ),
        sa.CheckConstraint("route_sequence >= 1", name=op.f("ck_wms_picking_item_route_sequence")),
        sa.CheckConstraint(
            f"status IN {_ITEM_STATUSES}",
            name=op.f("ck_wms_picking_item_status"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_wms_picking_item_version")),
        sa.ForeignKeyConstraint(
            ["company_id", "wave_id"],
            ["wms.wms_picking_wave.company_id", "wms.wms_picking_wave.id"],
            name="fk_wms_picking_item_wave",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "sales_order_id"],
            ["sales.sales_order.company_id", "sales.sales_order.id"],
            name="fk_wms_picking_item_sales_order",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "shipment_id"],
            ["wms.shipment.company_id", "wms.shipment.id"],
            name="fk_wms_picking_item_shipment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_wms_picking_item_product",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_wms_picking_item_warehouse",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "bin_id"],
            ["wms.wms_bin.company_id", "wms.wms_bin.id"],
            name="fk_wms_picking_item_bin",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "lot_id"],
            ["inventory.inventory_lot.company_id", "inventory.inventory_lot.id"],
            name="fk_wms_picking_item_lot",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "pool_id"],
            ["inventory.inventory_pool.company_id", "inventory.inventory_pool.id"],
            name="fk_wms_picking_item_pool",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wms_picking_item")),
        sa.UniqueConstraint("company_id", "id", name="uq_wms_picking_item_scope"),
        sa.UniqueConstraint(
            "company_id",
            "wave_id",
            "route_sequence",
            name="uq_wms_picking_item_route",
        ),
        schema="wms",
    )
    op.create_index(
        "ix_wms_picking_item_cartesian_route",
        "wms_picking_item",
        ["company_id", "wave_id", "route_address", "route_sequence"],
        schema="wms",
    )
    op.create_index(
        "ix_wms_picking_item_order",
        "wms_picking_item",
        ["company_id", "sales_order_id", "status"],
        schema="wms",
    )
    op.create_index(
        "ix_wms_picking_item_barcode",
        "wms_picking_item",
        ["company_id", "wave_id", "barcode", "status"],
        schema="wms",
    )

    op.create_table(
        "wms_packing_verification",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wave_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_key", sa.String(128), nullable=False),
        sa.Column("scan_sequence", sa.Integer(), nullable=False),
        sa.Column("barcode", sa.String(64), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "length(btrim(scan_key)) BETWEEN 1 AND 128",
            name=op.f("ck_wms_packing_verification_scan_key"),
        ),
        sa.CheckConstraint(
            "scan_sequence >= 1 AND quantity > 0",
            name=op.f("ck_wms_packing_verification_values"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "wave_id"],
            ["wms.wms_picking_wave.company_id", "wms.wms_picking_wave.id"],
            name="fk_wms_packing_verification_wave",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "item_id"],
            ["wms.wms_picking_item.company_id", "wms.wms_picking_item.id"],
            name="fk_wms_packing_verification_item",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wms_packing_verification")),
        sa.UniqueConstraint("company_id", "id", name="uq_wms_packing_verification_scope"),
        sa.UniqueConstraint(
            "company_id",
            "wave_id",
            "scan_key",
            name="uq_wms_packing_verification_scan",
        ),
        sa.UniqueConstraint(
            "company_id",
            "item_id",
            "scan_sequence",
            name="uq_wms_packing_verification_sequence",
        ),
        schema="wms",
    )
    op.create_index(
        "ix_wms_packing_verification_timeline",
        "wms_packing_verification",
        ["company_id", "wave_id", "verified_at", "scan_sequence"],
        schema="wms",
    )


def downgrade() -> None:
    op.drop_table("wms_packing_verification", schema="wms")
    op.drop_table("wms_picking_item", schema="wms")
    op.drop_table("wms_picking_wave", schema="wms")
