"""Tenant-owned staging, validation snapshots and durable commit receipts."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKeyConstraint, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.database import Base


class ImportStagingRowModel(Base):
    __tablename__ = "import_staging_row"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "job_id"],
            ["governance.import_job.company_id", "governance.import_job.id"],
            ondelete="RESTRICT",
        ),
        {"schema": "governance"},
    )
    company_id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    row_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    values: Mapped[dict[str, str]] = mapped_column(JSONB)
    errors: Mapped[list[str]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID]


class ImportValidationResultModel(Base):
    __tablename__ = "import_validation_result"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "job_id"],
            ["governance.import_job.company_id", "governance.import_job.id"],
            ondelete="RESTRICT",
        ),
        {"schema": "governance"},
    )
    company_id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    plans: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID]


class ImportCommitBatchModel(Base):
    __tablename__ = "import_commit_batch"
    __table_args__ = (
        ForeignKeyConstraint(
            ["company_id", "job_id"],
            ["governance.import_job.company_id", "governance.import_job.id"],
            ondelete="RESTRICT",
        ),
        {"schema": "governance"},
    )
    company_id: Mapped[UUID] = mapped_column(primary_key=True)
    job_id: Mapped[UUID] = mapped_column(primary_key=True)
    affected_count: Mapped[int] = mapped_column(Integer)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID]


__all__ = ["ImportCommitBatchModel", "ImportStagingRowModel", "ImportValidationResultModel"]
