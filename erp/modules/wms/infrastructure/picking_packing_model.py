"""SQLAlchemy mappings for route-aware WMS execution."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class WmsPickingWaveModel(OptimisticLockMixin, Base):
    __tablename__ = "wms_picking_wave"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_wms_picking_wave_0060_scope"),
        UniqueConstraint("company_id", "code", name="uq_wms_picking_wave_0060_code"),
        UniqueConstraint(
            "company_id",
            "manifest_number",
            name="uq_wms_picking_wave_0060_manifest",
        ),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="code"),
        CheckConstraint("status IN ('DRAFT', 'PACKING', 'MANIFESTED')", name="status"),
        CheckConstraint(
            "(status = 'MANIFESTED') = (manifest_number IS NOT NULL AND manifested_at IS NOT NULL)",
            name="manifest",
        ),
        CheckConstraint("version >= 1", name="version"),
        ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_wms_picking_wave_warehouse_0060",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_wms_picking_wave_0060_queue",
            "company_id",
            "warehouse_id",
            "status",
            "created_at",
            "id",
        ),
        {"schema": "wms"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    manifest_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    manifested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class WmsPickingItemModel(OptimisticLockMixin, Base):
    __tablename__ = "wms_picking_item"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_wms_picking_item_scope"),
        UniqueConstraint(
            "company_id",
            "wave_id",
            "route_sequence",
            name="uq_wms_picking_item_route",
        ),
        CheckConstraint("barcode ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="barcode"),
        CheckConstraint(
            "required_quantity > 0 AND picked_quantity >= 0 AND packed_quantity >= 0",
            name="quantities",
        ),
        CheckConstraint(
            "packed_quantity <= picked_quantity AND picked_quantity <= required_quantity",
            name="quantity_order",
        ),
        CheckConstraint("units >= 1 AND required_quantity = units", name="units"),
        CheckConstraint("unit_weight > 0 AND unit_volume > 0", name="measures"),
        CheckConstraint("route_sequence >= 1", name="route_sequence"),
        CheckConstraint("status IN ('OPEN', 'PICKED', 'PACKED')", name="status"),
        CheckConstraint("version >= 1", name="version"),
        ForeignKeyConstraint(
            ["company_id", "wave_id"],
            ["wms.wms_picking_wave.company_id", "wms.wms_picking_wave.id"],
            name="fk_wms_picking_item_wave",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "sales_order_id"],
            ["sales.sales_order.company_id", "sales.sales_order.id"],
            name="fk_wms_picking_item_sales_order",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "shipment_id"],
            ["wms.shipment.company_id", "wms.shipment.id"],
            name="fk_wms_picking_item_shipment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_wms_picking_item_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_wms_picking_item_warehouse",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "bin_id"],
            ["wms.wms_bin.company_id", "wms.wms_bin.id"],
            name="fk_wms_picking_item_bin",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "lot_id"],
            ["inventory.inventory_lot.company_id", "inventory.inventory_lot.id"],
            name="fk_wms_picking_item_lot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "pool_id"],
            ["inventory.inventory_pool.company_id", "inventory.inventory_pool.id"],
            name="fk_wms_picking_item_pool",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_wms_picking_item_cartesian_route",
            "company_id",
            "wave_id",
            "route_address",
            "route_sequence",
        ),
        Index("ix_wms_picking_item_order", "company_id", "sales_order_id", "status"),
        Index("ix_wms_picking_item_barcode", "company_id", "wave_id", "barcode", "status"),
        {"schema": "wms"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    wave_id: Mapped[UUID] = mapped_column(nullable=False)
    sales_order_id: Mapped[UUID] = mapped_column(nullable=False)
    shipment_id: Mapped[UUID] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    bin_id: Mapped[UUID] = mapped_column(nullable=False)
    lot_id: Mapped[UUID | None] = mapped_column(nullable=True)
    pool_id: Mapped[UUID | None] = mapped_column(nullable=True)
    barcode: Mapped[str] = mapped_column(String(64), nullable=False)
    required_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    picked_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    packed_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    units: Mapped[int] = mapped_column(nullable=False)
    unit_weight: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    unit_volume: Mapped[Decimal] = mapped_column(Numeric(36, 18), nullable=False)
    route_address: Mapped[str] = mapped_column(String(84), nullable=False)
    route_sequence: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class WmsPackingVerificationModel(Base):
    __tablename__ = "wms_packing_verification"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_wms_packing_verification_scope"),
        UniqueConstraint(
            "company_id",
            "wave_id",
            "scan_key",
            name="uq_wms_packing_verification_scan",
        ),
        UniqueConstraint(
            "company_id",
            "item_id",
            "scan_sequence",
            name="uq_wms_packing_verification_sequence",
        ),
        CheckConstraint("length(btrim(scan_key)) BETWEEN 1 AND 128", name="scan_key"),
        CheckConstraint("scan_sequence >= 1 AND quantity > 0", name="values"),
        ForeignKeyConstraint(
            ["company_id", "wave_id"],
            ["wms.wms_picking_wave.company_id", "wms.wms_picking_wave.id"],
            name="fk_wms_packing_verification_wave",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "item_id"],
            ["wms.wms_picking_item.company_id", "wms.wms_picking_item.id"],
            name="fk_wms_packing_verification_item",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_wms_packing_verification_timeline",
            "company_id",
            "wave_id",
            "verified_at",
            "scan_sequence",
        ),
        {"schema": "wms"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    wave_id: Mapped[UUID] = mapped_column(nullable=False)
    item_id: Mapped[UUID] = mapped_column(nullable=False)
    scan_key: Mapped[str] = mapped_column(String(128), nullable=False)
    scan_sequence: Mapped[int] = mapped_column(nullable=False)
    barcode: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = [
    "WmsPackingVerificationModel",
    "WmsPickingItemModel",
    "WmsPickingWaveModel",
]
