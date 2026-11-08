"""Durable event cursor and synchronization queue for Production."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base


class ProductionSourceCursorModel(Base):
    """Latest upstream aggregate version accepted for one tenant."""

    __tablename__ = "production_source_cursor"
    __table_args__ = (
        CheckConstraint("aggregate_version >= 1", name="version"),
        Index(
            "ix_production_source_cursor_company_event",
            "company_id",
            "event_occurred_at",
            "event_id",
        ),
        {"schema": "production"},
    )

    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), primary_key=True
    )
    producer_module: Mapped[str] = mapped_column(String(32), primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), primary_key=True)
    aggregate_id: Mapped[UUID] = mapped_column(primary_key=True)
    aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[UUID] = mapped_column(nullable=False)
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    event_occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProductionSynchronizationRequestModel(Base):
    """Coalesced work item requesting reevaluation of an affected production order."""

    __tablename__ = "production_synchronization_request"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "production_order_id"],
            ["production.production_order.company_id", "production.production_order.id"],
            name="fk_production_sync_request_order",
            ondelete="CASCADE",
        ),
        CheckConstraint("source_aggregate_version >= 1", name="source_version"),
        CheckConstraint("revision >= 1", name="revision"),
        CheckConstraint(
            "jsonb_typeof(affected_product_ids) = 'array'",
            name="affected_products",
        ),
        Index(
            "ix_production_sync_request_claim",
            "company_id",
            "requested_at",
            "production_order_id",
        ),
        {"schema": "production"},
    )

    company_id: Mapped[UUID] = mapped_column(primary_key=True)
    production_order_id: Mapped[UUID] = mapped_column(primary_key=True)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    affected_product_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    source_event_id: Mapped[UUID] = mapped_column(nullable=False)
    source_event_type: Mapped[str] = mapped_column(String(150), nullable=False)
    source_producer_module: Mapped[str] = mapped_column(String(32), nullable=False)
    source_aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_aggregate_id: Mapped[UUID] = mapped_column(nullable=False)
    source_aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


__all__ = ["ProductionSourceCursorModel", "ProductionSynchronizationRequestModel"]
