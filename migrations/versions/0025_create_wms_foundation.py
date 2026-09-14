"""Create M10 WMS foundation tables.

Revision ID: 0025
Revises: 0024
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add company-scoped WMS waves, tasks, packages and shipments."""
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS wms"))
    op.create_table(
        "picking_wave",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_picking_wave_code_format")),
        sa.CheckConstraint(
            "source_type ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'",
            name=op.f("ck_picking_wave_source_type_format"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'RELEASED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')",
            name=op.f("ck_picking_wave_status"),
        ),
        sa.CheckConstraint(
            "status != 'RELEASED' OR released_at IS NOT NULL",
            name=op.f("ck_picking_wave_released_requires_timestamp"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_picking_wave_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_picking_wave_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name=op.f("fk_wms_picking_wave_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_picking_wave")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_wms_picking_wave_company_id")),
        sa.UniqueConstraint("company_id", "code", name=op.f("uq_wms_picking_wave_company_code")),
        schema="wms",
    )
    op.create_index(
        "ix_wms_picking_wave_company_status",
        "picking_wave",
        ["company_id", "status", "code"],
        schema="wms",
    )
    op.create_table(
        "picking_task",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("wave_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("warehouse_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("pool_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("requested_quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("picked_quantity", sa.Numeric(18, 6), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_picking_task_sequence_positive")),
        sa.CheckConstraint("requested_quantity > 0", name=op.f("ck_picking_task_requested_quantity_positive")),
        sa.CheckConstraint("picked_quantity >= 0", name=op.f("ck_picking_task_picked_quantity_non_negative")),
        sa.CheckConstraint(
            "picked_quantity <= requested_quantity",
            name=op.f("ck_picking_task_picked_not_above_requested"),
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'IN_PROGRESS', 'COMPLETED', 'SHORTED', 'CANCELLED')",
            name=op.f("ck_picking_task_status"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_picking_task_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id", "wave_id"],
            ["wms.picking_wave.company_id", "wms.picking_wave.id"],
            name=op.f("fk_wms_picking_task_wave"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name=op.f("fk_wms_picking_task_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name=op.f("fk_wms_picking_task_warehouse"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "lot_id"],
            ["inventory.inventory_lot.company_id", "inventory.inventory_lot.id"],
            name=op.f("fk_wms_picking_task_lot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "pool_id"],
            ["inventory.inventory_pool.company_id", "inventory.inventory_pool.id"],
            name=op.f("fk_wms_picking_task_pool"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_picking_task")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_wms_picking_task_company_id")),
        sa.UniqueConstraint(
            "company_id",
            "wave_id",
            "sequence",
            name=op.f("uq_wms_picking_task_wave_sequence"),
        ),
        schema="wms",
    )
    op.create_index(
        "ix_wms_picking_task_company_status",
        "picking_task",
        ["company_id", "status", "wave_id"],
        schema="wms",
    )
    op.create_index(
        "ix_wms_picking_task_product",
        "picking_task",
        ["company_id", "product_id", "status"],
        schema="wms",
    )
    op.create_table(
        "shipment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shipment_code", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("carrier_code", sa.String(length=32), nullable=True),
        sa.Column("tracking_code", sa.String(length=80), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "shipment_code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'",
            name=op.f("ck_shipment_shipment_code_format"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'READY_TO_DISPATCH', 'DISPATCHED', 'DELIVERED', 'CANCELLED')",
            name=op.f("ck_shipment_status"),
        ),
        sa.CheckConstraint(
            "dispatched_at IS NULL OR status IN ('DISPATCHED', 'DELIVERED')",
            name=op.f("ck_shipment_dispatch_timestamp_status"),
        ),
        sa.CheckConstraint(
            "delivered_at IS NULL OR status = 'DELIVERED'",
            name=op.f("ck_shipment_delivery_timestamp_status"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_shipment_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_shipment_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shipment")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_wms_shipment_company_id")),
        sa.UniqueConstraint("company_id", "shipment_code", name=op.f("uq_wms_shipment_company_code")),
        schema="wms",
    )
    op.create_index(
        "ix_wms_shipment_company_status",
        "shipment",
        ["company_id", "status", "shipment_code"],
        schema="wms",
    )
    op.create_table(
        "package",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("package_code", sa.String(length=64), nullable=False),
        sa.Column("package_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("wave_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("shipment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("weight_grams", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint(
            "package_code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'",
            name=op.f("ck_package_package_code_format"),
        ),
        sa.CheckConstraint(
            "package_type IN ('CARTON', 'BAG', 'PALLET', 'OTHER')",
            name=op.f("ck_package_package_type"),
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'VERIFIED', 'FINALIZED', 'DISPATCHED')",
            name=op.f("ck_package_status"),
        ),
        sa.CheckConstraint(
            "weight_grams IS NULL OR weight_grams > 0",
            name=op.f("ck_package_weight_positive"),
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_package_version_positive")),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["admin.company.id"],
            name=op.f("fk_package_company_id_company"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "wave_id"],
            ["wms.picking_wave.company_id", "wms.picking_wave.id"],
            name=op.f("fk_wms_package_wave"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "shipment_id"],
            ["wms.shipment.company_id", "wms.shipment.id"],
            name=op.f("fk_wms_package_shipment"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_package")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_wms_package_company_id")),
        sa.UniqueConstraint("company_id", "package_code", name=op.f("uq_wms_package_company_code")),
        schema="wms",
    )
    op.create_index(
        "ix_wms_package_company_status",
        "package",
        ["company_id", "status", "package_code"],
        schema="wms",
    )
    op.create_table(
        "package_item",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_package_item_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["company_id", "package_id"],
            ["wms.package.company_id", "wms.package.id"],
            name=op.f("fk_wms_package_item_package"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "task_id"],
            ["wms.picking_task.company_id", "wms.picking_task.id"],
            name=op.f("fk_wms_package_item_task"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name=op.f("fk_wms_package_item_product"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "lot_id"],
            ["inventory.inventory_lot.company_id", "inventory.inventory_lot.id"],
            name=op.f("fk_wms_package_item_lot"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_package_item")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_wms_package_item_company_id")),
        sa.UniqueConstraint(
            "company_id",
            "package_id",
            "product_id",
            "lot_id",
            name=op.f("uq_wms_package_item_dimensions"),
        ),
        schema="wms",
    )
    op.create_index(
        "ix_wms_package_item_product",
        "package_item",
        ["company_id", "product_id"],
        schema="wms",
    )


def downgrade() -> None:
    """Destructive for WMS data; use only with explicit approval."""
    op.drop_table("package_item", schema="wms")
    op.drop_table("package", schema="wms")
    op.drop_table("shipment", schema="wms")
    op.drop_table("picking_task", schema="wms")
    op.drop_table("picking_wave", schema="wms")
    op.execute(sa.text("DROP SCHEMA IF EXISTS wms"))

