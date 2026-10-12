"""Tenant-bound persistence model for M12 payable governance."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class PayableGovernanceModel(OptimisticLockMixin, Base):
    __tablename__ = "payable_governance"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "payable_id"],
            ["finance.payable.company_id", "finance.payable.id"],
            name="fk_payable_governance_company_payable",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "approval_status IN ('NOT_REQUESTED', 'PENDING', 'APPROVED', 'REJECTED')",
            name="approval_status",
        ),
        CheckConstraint("version >= 1", name="version"),
        {"schema": "finance"},
    )

    company_id: Mapped[UUID] = mapped_column(primary_key=True)
    payable_id: Mapped[UUID] = mapped_column(primary_key=True)
    fiscal_blocked: Mapped[bool] = mapped_column(nullable=False, default=False)
    purchasing_blocked: Mapped[bool] = mapped_column(nullable=False, default=False)
    approval_status: Mapped[str] = mapped_column(String(24), nullable=False)
    workflow_instance_id: Mapped[UUID | None] = mapped_column(nullable=True)
    authority_limit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    sod_threshold: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


__all__ = ["PayableGovernanceModel"]
