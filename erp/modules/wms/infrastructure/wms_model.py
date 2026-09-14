"""SQLAlchemy mappings for the M10 WMS foundation."""

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


class PickingWaveModel(OptimisticLockMixin, Base):
    """Company-scoped picking wave, released into executable tasks."""

    __tablename__ = "picking_wave"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_wms_picking_wave_company_id"),
        UniqueConstraint("company_id", "code", name="uq_wms_picking_wave_company_code"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="code_format"),
        CheckConstraint("source_type ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'", name="source_type_format"),
        CheckConstraint(
            "status IN ('DRAFT', 'RELEASED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')",
            name="status",
        ),
        CheckConstraint(
            "status != 'RELEASED' OR released_at IS NOT NULL",
            name="released_requires_timestamp",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_wms_picking_wave_warehouse",
            ondelete="RESTRICT",
        ),
        Index("ix_wms_picking_wave_company_status", "company_id", "status", "code"),
        {"schema": "wms"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[UUID | None] = mapped_column(nullable=True)
    warehouse_id: Mapped[UUID | None] = mapped_column(nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class PickingTaskModel(OptimisticLockMixin, Base):
    """Executable pick instruction inside a wave."""

    __tablename__ = "picking_task"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_wms_picking_task_company_id"),
        UniqueConstraint(
            "company_id",
            "wave_id",
            "sequence",
            name="uq_wms_picking_task_wave_sequence",
        ),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint("requested_quantity > 0", name="requested_quantity_positive"),
        CheckConstraint("picked_quantity >= 0", name="picked_quantity_non_negative"),
        CheckConstraint(
            "picked_quantity <= requested_quantity",
            name="picked_not_above_requested",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'IN_PROGRESS', 'COMPLETED', 'SHORTED', 'CANCELLED')",
            name="status",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        ForeignKeyConstraint(
            ["company_id", "wave_id"],
            ["wms.picking_wave.company_id", "wms.picking_wave.id"],
            name="fk_wms_picking_task_wave",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_wms_picking_task_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_wms_picking_task_warehouse",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "lot_id"],
            ["inventory.inventory_lot.company_id", "inventory.inventory_lot.id"],
            name="fk_wms_picking_task_lot",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "pool_id"],
            ["inventory.inventory_pool.company_id", "inventory.inventory_pool.id"],
            name="fk_wms_picking_task_pool",
            ondelete="RESTRICT",
        ),
        Index("ix_wms_picking_task_company_status", "company_id", "status", "wave_id"),
        Index("ix_wms_picking_task_product", "company_id", "product_id", "status"),
        {"schema": "wms"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    wave_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    warehouse_id: Mapped[UUID | None] = mapped_column(nullable=True)
    lot_id: Mapped[UUID | None] = mapped_column(nullable=True)
    pool_id: Mapped[UUID | None] = mapped_column(nullable=True)
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    picked_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 6), nullable=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class ShipmentModel(OptimisticLockMixin, Base):
    """Outbound shipment grouping finalized packages for dispatch."""

    __tablename__ = "shipment"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_wms_shipment_company_id"),
        UniqueConstraint("company_id", "shipment_code", name="uq_wms_shipment_company_code"),
        CheckConstraint(
            "shipment_code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'",
            name="shipment_code_format",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'READY_TO_DISPATCH', 'DISPATCHED', 'DELIVERED', 'CANCELLED')",
            name="status",
        ),
        CheckConstraint(
            "dispatched_at IS NULL OR status IN ('DISPATCHED', 'DELIVERED')",
            name="dispatch_timestamp_status",
        ),
        CheckConstraint(
            "delivered_at IS NULL OR status = 'DELIVERED'",
            name="delivery_timestamp_status",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index("ix_wms_shipment_company_status", "company_id", "status", "shipment_code"),
        {"schema": "wms"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    shipment_code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    carrier_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tracking_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class PackageModel(OptimisticLockMixin, Base):
    """Physical package created by packing and optionally attached to a shipment."""

    __tablename__ = "package"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_wms_package_company_id"),
        UniqueConstraint("company_id", "package_code", name="uq_wms_package_company_code"),
        CheckConstraint(
            "package_code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'",
            name="package_code_format",
        ),
        CheckConstraint("package_type IN ('CARTON', 'BAG', 'PALLET', 'OTHER')", name="package_type"),
        CheckConstraint(
            "status IN ('DRAFT', 'VERIFIED', 'FINALIZED', 'DISPATCHED')",
            name="status",
        ),
        CheckConstraint(
            "weight_grams IS NULL OR weight_grams > 0",
            name="weight_positive",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        ForeignKeyConstraint(
            ["company_id", "wave_id"],
            ["wms.picking_wave.company_id", "wms.picking_wave.id"],
            name="fk_wms_package_wave",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "shipment_id"],
            ["wms.shipment.company_id", "wms.shipment.id"],
            name="fk_wms_package_shipment",
            ondelete="RESTRICT",
        ),
        Index("ix_wms_package_company_status", "company_id", "status", "package_code"),
        {"schema": "wms"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    package_code: Mapped[str] = mapped_column(String(64), nullable=False)
    package_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    wave_id: Mapped[UUID | None] = mapped_column(nullable=True)
    shipment_id: Mapped[UUID | None] = mapped_column(nullable=True)
    weight_grams: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class PackageItemModel(Base):
    """Product quantity packed into one package."""

    __tablename__ = "package_item"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_wms_package_item_company_id"),
        UniqueConstraint(
            "company_id",
            "package_id",
            "product_id",
            "lot_id",
            name="uq_wms_package_item_dimensions",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        ForeignKeyConstraint(
            ["company_id", "package_id"],
            ["wms.package.company_id", "wms.package.id"],
            name="fk_wms_package_item_package",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "task_id"],
            ["wms.picking_task.company_id", "wms.picking_task.id"],
            name="fk_wms_package_item_task",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_wms_package_item_product",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "lot_id"],
            ["inventory.inventory_lot.company_id", "inventory.inventory_lot.id"],
            name="fk_wms_package_item_lot",
            ondelete="RESTRICT",
        ),
        Index("ix_wms_package_item_product", "company_id", "product_id"),
        {"schema": "wms"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    package_id: Mapped[UUID] = mapped_column(nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(nullable=True)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    lot_id: Mapped[UUID | None] = mapped_column(nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = [
    "PackageItemModel",
    "PackageModel",
    "PickingTaskModel",
    "PickingWaveModel",
    "ShipmentModel",
]

