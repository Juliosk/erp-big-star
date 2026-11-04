"""Append-only SQLAlchemy mapping for Cash Flow risk alerts."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base


class CashFlowAlertModel(Base):
    __tablename__ = "cash_flow_alert"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "projection_id", "projection_version"],
            [
                "finance.cash_flow_projection_snapshot.company_id",
                "finance.cash_flow_projection_snapshot.id",
                "finance.cash_flow_projection_snapshot.version",
            ],
            name="fk_cash_flow_alert_company_projection",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("company_id", "id", name="uq_cash_flow_alert_company_id"),
        CheckConstraint("projection_version >= 1", name="version"),
        CheckConstraint("source IN ('PROJECTION', 'SCENARIO')", name="source"),
        CheckConstraint(
            "alert_type IN ('CASH_RUPTURE', 'SAFETY_THRESHOLD', "
            "'DATE_CONCENTRATION', 'CATEGORY_CONCENTRATION', "
            "'EXPOSURE_CONCENTRATION', 'DAILY_OUTLIER', "
            "'SCENARIO_SENSITIVITY')",
            name="type",
        ),
        CheckConstraint("severity IN ('WARNING', 'CRITICAL')", name="severity"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
        Index(
            "ix_cash_flow_alert_company_detected",
            "company_id",
            "detected_at",
            "severity",
            "alert_type",
        ),
        Index(
            "ix_cash_flow_alert_company_projection",
            "company_id",
            "projection_id",
            "projection_version",
        ),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    projection_id: Mapped[UUID] = mapped_column(nullable=False)
    projection_version: Mapped[int] = mapped_column(nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    dimension: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_key: Mapped[str] = mapped_column(String(300), nullable=False)
    breach_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_value: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    threshold_value: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(nullable=True)
    request_id: Mapped[UUID] = mapped_column(nullable=False)
    correlation_id: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["CashFlowAlertModel"]
