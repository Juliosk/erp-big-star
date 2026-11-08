"""Tenant-bound shop-floor execution evidence mappings."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base


class ShopFloorOperationLogModel(Base):
    __tablename__ = "shop_floor_operation_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "production_order_id"],
            ["production.production_order.company_id", "production.production_order.id"],
            name="fk_shop_floor_log_order",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "work_center_code"],
            ["production.work_center.company_id", "production.work_center.code"],
            name="fk_shop_floor_log_center",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_shop_floor_log_company_id"),
        UniqueConstraint(
            "company_id", "request_id", name="uq_shop_floor_log_company_request"
        ),
        CheckConstraint(
            "event_type IN ('STARTED', 'PROGRESS', 'COMPLETED')",
            name="event_type",
        ),
        CheckConstraint("operation_sequence >= 1", name="operation_sequence"),
        CheckConstraint("good_quantity >= 0", name="good_quantity"),
        CheckConstraint(
            "jsonb_typeof(material_consumptions) = 'array'",
            name="material_consumptions",
        ),
        CheckConstraint("order_version_before >= 1", name="version_before"),
        CheckConstraint(
            "order_version_after >= order_version_before", name="version_after"
        ),
        Index(
            "ix_shop_floor_log_order_operation",
            "company_id",
            "production_order_id",
            "operation_sequence",
            "occurred_at",
        ),
        Index(
            "uq_shop_floor_log_started",
            "company_id",
            "production_order_id",
            "operation_sequence",
            unique=True,
            postgresql_where="event_type = 'STARTED'",
        ),
        Index(
            "uq_shop_floor_log_completed",
            "company_id",
            "production_order_id",
            "operation_sequence",
            unique=True,
            postgresql_where="event_type = 'COMPLETED'",
        ),
        {"schema": "production"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    production_order_id: Mapped[UUID] = mapped_column(nullable=False)
    operation_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    work_center_code: Mapped[str] = mapped_column(String(32), nullable=False)
    good_quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    material_consumptions: Mapped[list[dict[str, str]]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(nullable=False)
    order_version_before: Mapped[int] = mapped_column(Integer, nullable=False)
    order_version_after: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False)


class ScrapRecordModel(Base):
    __tablename__ = "scrap_record"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "operation_log_id"],
            [
                "production.shop_floor_operation_log.company_id",
                "production.shop_floor_operation_log.id",
            ],
            name="fk_scrap_record_log",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "production_order_id"],
            ["production.production_order.company_id", "production.production_order.id"],
            name="fk_scrap_record_order",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["company_id", "product_id"],
            ["product.product.company_id", "product.product.id"],
            name="fk_scrap_record_product",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_scrap_record_company_id"),
        CheckConstraint("operation_sequence >= 1", name="operation_sequence"),
        CheckConstraint("quantity > 0", name="quantity"),
        CheckConstraint(
            "reason_code ~ '^[A-Z0-9][A-Z0-9_]{1,31}$'", name="reason_code"
        ),
        Index(
            "ix_scrap_record_order_operation",
            "company_id",
            "production_order_id",
            "operation_sequence",
            "occurred_at",
        ),
        {"schema": "production"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    operation_log_id: Mapped[UUID] = mapped_column(nullable=False)
    production_order_id: Mapped[UUID] = mapped_column(nullable=False)
    operation_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[UUID] = mapped_column(nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["ScrapRecordModel", "ShopFloorOperationLogModel"]
