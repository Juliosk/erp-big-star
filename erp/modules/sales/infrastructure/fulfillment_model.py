"""Tenant-bound SQLAlchemy mappings for sales fulfillment and tracking."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base

_MARKETPLACES = "('MERCADO_LIVRE', 'SHOPEE', 'NUVEMSHOP')"
_STATUSES = "('LABEL_CREATED', 'DISPATCHED')"
_LOG_EVENTS = (
    "('SEPARATION_CONFIRMED', 'LABEL_CREATED', 'DISPATCHED', "
    "'CHANNEL_SYNC_REQUESTED')"
)


class SalesShipmentModel(OptimisticLockMixin, Base):
    __tablename__ = "sales_shipment"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "sales_order_id"],
            ["sales.sales_order.company_id", "sales.sales_order.id"],
            name="fk_sales_shipment_sales_order",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "wms_shipment_id"],
            ["wms.shipment.company_id", "wms.shipment.id"],
            name="fk_sales_shipment_wms_shipment",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "channel_config_id"],
            ["sales.sales_channel_config.company_id", "sales.sales_channel_config.id"],
            name="fk_sales_shipment_channel_config",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_sales_shipment_company_id"),
        UniqueConstraint(
            "company_id", "sales_order_id", name="uq_sales_shipment_order"
        ),
        UniqueConstraint(
            "company_id", "wms_shipment_id", name="uq_sales_shipment_wms_shipment"
        ),
        UniqueConstraint(
            "company_id",
            "carrier_code",
            "tracking_code",
            name="uq_sales_shipment_tracking",
        ),
        CheckConstraint(f"marketplace IN {_MARKETPLACES}", name="marketplace"),
        CheckConstraint(f"status IN {_STATUSES}", name="status"),
        CheckConstraint(
            "status != 'DISPATCHED' OR dispatched_at IS NOT NULL",
            name="dispatch_timestamp",
        ),
        CheckConstraint(
            "length(btrim(external_order_id)) BETWEEN 1 AND 128",
            name="external_order_id",
        ),
        CheckConstraint(
            "length(btrim(carrier_code)) BETWEEN 1 AND 32 "
            "AND length(btrim(service_code)) BETWEEN 1 AND 32",
            name="carrier_service",
        ),
        CheckConstraint(
            "tracking_code ~ '^[A-Z0-9][A-Z0-9._-]{0,79}$'",
            name="tracking_code",
        ),
        CheckConstraint(
            "length(btrim(label_reference)) BETWEEN 1 AND 255",
            name="label_reference",
        ),
        CheckConstraint("version >= 1", name="version"),
        Index(
            "ix_sales_shipment_company_status_time",
            "company_id",
            "status",
            "dispatched_at",
            "id",
        ),
        Index(
            "ix_sales_shipment_company_external",
            "company_id",
            "marketplace",
            "account_id",
            "external_order_id",
        ),
        {"schema": "sales"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    sales_order_id: Mapped[UUID] = mapped_column(nullable=False)
    wms_shipment_id: Mapped[UUID] = mapped_column(nullable=False)
    channel_config_id: Mapped[UUID] = mapped_column(nullable=False)
    account_id: Mapped[UUID] = mapped_column(nullable=False)
    marketplace: Mapped[str] = mapped_column(String(24), nullable=False)
    external_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    carrier_code: Mapped[str] = mapped_column(String(32), nullable=False)
    service_code: Mapped[str] = mapped_column(String(32), nullable=False)
    tracking_code: Mapped[str] = mapped_column(String(80), nullable=False)
    label_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class SalesFulfillmentLogModel(Base):
    __tablename__ = "sales_fulfillment_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "shipment_id"],
            ["sales.sales_shipment.company_id", "sales.sales_shipment.id"],
            name="fk_sales_fulfillment_log_shipment",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "company_id", "id", name="uq_sales_fulfillment_log_company_id"
        ),
        UniqueConstraint(
            "company_id",
            "shipment_id",
            "sequence",
            name="uq_sales_fulfillment_log_sequence",
        ),
        CheckConstraint("sequence >= 1", name="sequence"),
        CheckConstraint(f"event_type IN {_LOG_EVENTS}", name="event_type"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload"),
        Index(
            "ix_sales_fulfillment_log_company_time",
            "company_id",
            "occurred_at",
            "id",
        ),
        Index(
            "ix_sales_fulfillment_log_shipment_event",
            "company_id",
            "shipment_id",
            "event_type",
            "sequence",
        ),
        {"schema": "sales"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    shipment_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor_id: Mapped[UUID] = mapped_column(nullable=False)
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


__all__ = ["SalesFulfillmentLogModel", "SalesShipmentModel"]
