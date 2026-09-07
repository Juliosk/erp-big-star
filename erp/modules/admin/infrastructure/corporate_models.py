"""SQLAlchemy mappings for M1 corporate foundation aggregate roots."""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class EconomicGroupModel(OptimisticLockMixin, Base):
    """Top-level authorized consolidation boundary."""

    __tablename__ = "economic_group"
    __table_args__ = (
        Index("ix_economic_group_status", "status"),
        {"schema": "admin"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class CompanyModel(OptimisticLockMixin, Base):
    """Legal company belonging to one economic group."""

    __tablename__ = "company"
    __table_args__ = (
        UniqueConstraint("group_id", "code", name="uq_company_group_code"),
        UniqueConstraint("tax_id", name="uq_company_tax_id"),
        Index("ix_company_group_id", "group_id"),
        Index("ix_company_group_status", "group_id", "status"),
        {"schema": "admin"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    group_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("admin.economic_group.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tax_id: Mapped[str] = mapped_column(String(14), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class BranchModel(OptimisticLockMixin, Base):
    """Operational/fiscal branch belonging to one company."""

    __tablename__ = "branch"
    __table_args__ = (
        UniqueConstraint("company_id", "code", name="uq_branch_company_code"),
        UniqueConstraint("tax_id", name="uq_branch_tax_id"),
        Index("ix_branch_company_id", "company_id"),
        Index("ix_branch_company_status", "company_id", "status"),
        {"schema": "admin"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("admin.company.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    tax_id: Mapped[str] = mapped_column(String(14), nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


__all__ = ["BranchModel", "CompanyModel", "EconomicGroupModel"]
