"""Tenant-bound SQLAlchemy mappings for the WMS physical hierarchy."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base

_STORAGE_TYPES = "('PICKING', 'RESERVE', 'DAMAGED', 'QUARANTINE')"
_CODE_CHECK = "code ~ '^[A-Z0-9][A-Z0-9_]{0,15}$'"


class WmsZoneModel(OptimisticLockMixin, Base):
    __tablename__ = "wms_zone"
    __table_args__ = (
        UniqueConstraint("company_id", "warehouse_id", "id", name="uq_wms_zone_scope_id"),
        UniqueConstraint(
            "company_id", "warehouse_id", "code", name="uq_wms_zone_address"
        ),
        ForeignKeyConstraint(
            ["company_id", "warehouse_id"],
            ["inventory.warehouse.company_id", "inventory.warehouse.id"],
            name="fk_wms_zone_warehouse",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_CODE_CHECK, name="code"),
        CheckConstraint(f"storage_type IN {_STORAGE_TYPES}", name="storage_type"),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_wms_zone_company_warehouse_type",
            "company_id",
            "warehouse_id",
            "storage_type",
            "code",
        ),
        {"schema": "wms"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    storage_type: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class WmsAisleModel(OptimisticLockMixin, Base):
    __tablename__ = "wms_aisle"
    __table_args__ = (
        UniqueConstraint("company_id", "warehouse_id", "id", name="uq_wms_aisle_scope_id"),
        UniqueConstraint(
            "company_id",
            "warehouse_id",
            "zone_id",
            "code",
            name="uq_wms_aisle_address",
        ),
        ForeignKeyConstraint(
            ["company_id", "warehouse_id", "zone_id"],
            ["wms.wms_zone.company_id", "wms.wms_zone.warehouse_id", "wms.wms_zone.id"],
            name="fk_wms_aisle_zone",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_CODE_CHECK, name="code"),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_wms_aisle_hierarchy",
            "company_id",
            "warehouse_id",
            "zone_id",
            "code",
        ),
        {"schema": "wms"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    zone_id: Mapped[UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class WmsBayModel(OptimisticLockMixin, Base):
    __tablename__ = "wms_bay"
    __table_args__ = (
        UniqueConstraint("company_id", "warehouse_id", "id", name="uq_wms_bay_scope_id"),
        UniqueConstraint(
            "company_id",
            "warehouse_id",
            "aisle_id",
            "code",
            name="uq_wms_bay_address",
        ),
        ForeignKeyConstraint(
            ["company_id", "warehouse_id", "aisle_id"],
            ["wms.wms_aisle.company_id", "wms.wms_aisle.warehouse_id", "wms.wms_aisle.id"],
            name="fk_wms_bay_aisle",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_CODE_CHECK, name="code"),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_wms_bay_hierarchy",
            "company_id",
            "warehouse_id",
            "aisle_id",
            "code",
        ),
        {"schema": "wms"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    aisle_id: Mapped[UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class WmsLevelModel(OptimisticLockMixin, Base):
    __tablename__ = "wms_level"
    __table_args__ = (
        UniqueConstraint("company_id", "warehouse_id", "id", name="uq_wms_level_scope_id"),
        UniqueConstraint(
            "company_id",
            "warehouse_id",
            "bay_id",
            "code",
            name="uq_wms_level_address",
        ),
        ForeignKeyConstraint(
            ["company_id", "warehouse_id", "bay_id"],
            ["wms.wms_bay.company_id", "wms.wms_bay.warehouse_id", "wms.wms_bay.id"],
            name="fk_wms_level_bay",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_CODE_CHECK, name="code"),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_wms_level_hierarchy",
            "company_id",
            "warehouse_id",
            "bay_id",
            "code",
        ),
        {"schema": "wms"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    bay_id: Mapped[UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class WmsBinModel(OptimisticLockMixin, Base):
    """The bin UUID is the linked M5 inventory.location UUID."""

    __tablename__ = "wms_bin"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_wms_bin_company_id"),
        UniqueConstraint(
            "company_id",
            "warehouse_id",
            "address_code",
            name="uq_wms_bin_cartesian_address",
        ),
        ForeignKeyConstraint(
            ["company_id", "warehouse_id", "level_id"],
            ["wms.wms_level.company_id", "wms.wms_level.warehouse_id", "wms.wms_level.id"],
            name="fk_wms_bin_level",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "id"],
            ["inventory.location.company_id", "inventory.location.id"],
            name="fk_wms_bin_inventory_location",
            ondelete="RESTRICT",
        ),
        CheckConstraint(_CODE_CHECK, name="code"),
        CheckConstraint(
            "address_code ~ '^[A-Z0-9_]{1,16}/[A-Z0-9_]{1,16}/[A-Z0-9_]{1,16}/"
            "[A-Z0-9_]{1,16}/[A-Z0-9_]{1,16}$'",
            name="address_code",
        ),
        CheckConstraint("occupied_units >= 0", name="occupied_units"),
        CheckConstraint("used_weight >= 0", name="used_weight"),
        CheckConstraint("used_volume >= 0", name="used_volume"),
        CheckConstraint(
            "(occupied_units = 0 AND used_weight = 0 AND used_volume = 0) OR "
            "(occupied_units > 0 AND used_weight > 0 AND used_volume > 0)",
            name="empty_consistency",
        ),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_wms_bin_hierarchy", "company_id", "warehouse_id", "level_id", "code"
        ),
        Index(
            "ix_wms_bin_spatial_address",
            "company_id",
            "warehouse_id",
            "address_code",
        ),
        Index(
            "ix_wms_bin_occupancy",
            "company_id",
            "warehouse_id",
            "blocked",
            "occupied_units",
        ),
        {"schema": "wms"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    warehouse_id: Mapped[UUID] = mapped_column(nullable=False)
    level_id: Mapped[UUID] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    address_code: Mapped[str] = mapped_column(String(84), nullable=False)
    occupied_units: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    used_weight: Mapped[Decimal] = mapped_column(
        Numeric(24, 6), nullable=False, server_default="0"
    )
    used_volume: Mapped[Decimal] = mapped_column(
        Numeric(36, 18), nullable=False, server_default="0"
    )
    blocked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class WmsBinCapacityModel(OptimisticLockMixin, Base):
    __tablename__ = "wms_bin_capacity"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "bin_id"],
            ["wms.wms_bin.company_id", "wms.wms_bin.id"],
            name="fk_wms_bin_capacity_bin",
            ondelete="CASCADE",
        ),
        CheckConstraint("width > 0 AND depth > 0 AND height > 0", name="dimensions"),
        CheckConstraint("max_weight > 0", name="weight"),
        CheckConstraint("max_units BETWEEN 1 AND 1000000", name="units"),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_wms_bin_capacity_search",
            "company_id",
            "max_units",
            "max_weight",
        ),
        {"schema": "wms"},
    )

    company_id: Mapped[UUID] = mapped_column(primary_key=True)
    bin_id: Mapped[UUID] = mapped_column(primary_key=True)
    width: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    depth: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    height: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    max_weight: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    max_units: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = [
    "WmsAisleModel",
    "WmsBayModel",
    "WmsBinCapacityModel",
    "WmsBinModel",
    "WmsLevelModel",
    "WmsZoneModel",
]
