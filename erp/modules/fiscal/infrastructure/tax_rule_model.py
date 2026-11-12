"""Tenant-bound SQLAlchemy mapping for M11 tax rules."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class TaxRuleModel(OptimisticLockMixin, Base):
    __tablename__ = "tax_rule"
    __table_args__ = (
        CheckConstraint("flow IN ('INBOUND', 'OUTBOUND')", name="ck_tax_rule_flow"),
        CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')",
            name="ck_tax_rule_status",
        ),
        CheckConstraint("ncm ~ '^[0-9]{8}$'", name="ck_tax_rule_ncm"),
        CheckConstraint("cfop ~ '^[0-9]{4}$'", name="ck_tax_rule_cfop"),
        CheckConstraint(
            "origin_country_code ~ '^[A-Z]{2}$' AND destination_country_code ~ '^[A-Z]{2}$'",
            name="ck_tax_rule_countries",
        ),
        CheckConstraint(
            "origin_municipality_code IS NULL OR "
            "(origin_state_code IS NOT NULL AND "
            "origin_municipality_code ~ '^[0-9]{7}$')",
            name="ck_tax_rule_origin_jurisdiction",
        ),
        CheckConstraint(
            "destination_municipality_code IS NULL OR "
            "(destination_state_code IS NOT NULL AND "
            "destination_municipality_code ~ '^[0-9]{7}$')",
            name="ck_tax_rule_destination_jurisdiction",
        ),
        CheckConstraint(
            "icms_rate BETWEEN 0 AND 1 AND pis_rate BETWEEN 0 AND 1 AND "
            "cofins_rate BETWEEN 0 AND 1 AND ipi_rate BETWEEN 0 AND 1",
            name="ck_tax_rule_rates",
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_tax_rule_effective_period",
        ),
        CheckConstraint(
            "(status = 'DRAFT' AND activated_by IS NULL AND activated_at IS NULL "
            "AND retired_at IS NULL) OR "
            "(status = 'ACTIVE' AND activated_by IS NOT NULL "
            "AND activated_at IS NOT NULL AND retired_at IS NULL) OR "
            "(status = 'RETIRED' AND activated_by IS NOT NULL "
            "AND activated_at IS NOT NULL AND retired_at IS NOT NULL "
            "AND retired_at >= activated_at)",
            name="ck_tax_rule_lifecycle_evidence",
        ),
        CheckConstraint("version >= 1", name="ck_tax_rule_version"),
        UniqueConstraint("company_id", "id", name="uq_tax_rule_company_id"),
        UniqueConstraint(
            "company_id",
            "code",
            "version_code",
            name="uq_tax_rule_company_code_version",
        ),
        Index(
            "ix_tax_rule_company_status_effective",
            "company_id",
            "status",
            "effective_from",
            "effective_until",
            "id",
        ),
        Index("ix_tax_rule_resolution", "company_id", "flow", "ncm", "cfop", "status"),
        {"schema": "fiscal"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    version_code: Mapped[str] = mapped_column(String(32), nullable=False)
    flow: Mapped[str] = mapped_column(String(16), nullable=False)
    ncm: Mapped[str] = mapped_column(String(8), nullable=False)
    cfop: Mapped[str] = mapped_column(String(4), nullable=False)
    origin_country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    origin_state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    origin_municipality_code: Mapped[str | None] = mapped_column(String(7), nullable=True)
    destination_country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    destination_state_code: Mapped[str | None] = mapped_column(String(2), nullable=True)
    destination_municipality_code: Mapped[str | None] = mapped_column(String(7), nullable=True)
    icms_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    pis_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    cofins_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    ipi_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    activated_by: Mapped[UUID | None] = mapped_column(nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["TaxRuleModel"]
