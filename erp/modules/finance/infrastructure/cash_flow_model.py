"""Tenant-bound SQLAlchemy mappings for immutable Cash Flow snapshots."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base


class CashFlowScenarioDefinitionModel(Base):
    __tablename__ = "cash_flow_scenario_definition"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_cash_flow_scenario_company_id"),
        UniqueConstraint("company_id", "name", name="uq_cash_flow_scenario_company_name"),
        CheckConstraint("receivable_delay_days BETWEEN 0 AND 365", name="delay"),
        CheckConstraint("cost_variation_rate BETWEEN -1 AND 10", name="cost_rate"),
        CheckConstraint(
            "business_day_convention IN ('FOLLOWING', 'PRECEDING', 'UNADJUSTED')",
            name="business_day",
        ),
        CheckConstraint("version >= 1", name="version"),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    receivable_delay_days: Mapped[int] = mapped_column(nullable=False)
    cost_variation_rate: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False)
    business_day_convention: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)


class CashFlowProjectionSnapshotModel(Base):
    __tablename__ = "cash_flow_projection_snapshot"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "scenario_id"],
            [
                "finance.cash_flow_scenario_definition.company_id",
                "finance.cash_flow_scenario_definition.id",
            ],
            name="fk_cash_flow_snapshot_company_scenario",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "company_id",
            "id",
            "version",
            name="uq_cash_flow_snapshot_company_id_version",
        ),
        CheckConstraint("version >= 1", name="version"),
        CheckConstraint("as_of = horizon_start AND horizon_start <= horizon_end", name="horizon"),
        CheckConstraint("granularity IN ('DAILY', 'WEEKLY', 'MONTHLY')", name="granularity"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
        CheckConstraint("minimum_reserve >= 0", name="reserve"),
        CheckConstraint(
            "liquidity_state IN ('HEALTHY', 'ATTENTION', 'CRITICAL', 'INCOMPLETE')",
            name="liquidity",
        ),
        Index(
            "ix_cash_flow_snapshot_company_as_of_horizon",
            "company_id",
            "as_of",
            "horizon_end",
            "id",
            "version",
        ),
        Index(
            "ix_cash_flow_snapshot_company_calculated",
            "company_id",
            "calculated_at",
            "id",
            "version",
        ),
        {"schema": "finance"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    scenario_id: Mapped[UUID] = mapped_column(nullable=False)
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_start: Mapped[date] = mapped_column(Date, nullable=False)
    horizon_end: Mapped[date] = mapped_column(Date, nullable=False)
    granularity: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    minimum_reserve: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    operational_closing_balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    scenario_closing_balance: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    liquidity_state: Mapped[str] = mapped_column(String(16), nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[UUID] = mapped_column(nullable=False)


class CashFlowAuditLogModel(Base):
    __tablename__ = "cash_flow_audit_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "projection_id", "projection_version"],
            [
                "finance.cash_flow_projection_snapshot.company_id",
                "finance.cash_flow_projection_snapshot.id",
                "finance.cash_flow_projection_snapshot.version",
            ],
            name="fk_cash_flow_audit_company_snapshot",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "company_id",
            "projection_id",
            "projection_version",
            name="uq_cash_flow_audit_company_projection_version",
        ),
        CheckConstraint("action IN ('CREATED', 'RECALCULATED')", name="action"),
        CheckConstraint("projection_version >= 1", name="version"),
        Index(
            "ix_cash_flow_audit_company_projection",
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
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_id: Mapped[UUID] = mapped_column(nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


__all__ = [
    "CashFlowAuditLogModel",
    "CashFlowProjectionSnapshotModel",
    "CashFlowScenarioDefinitionModel",
]
