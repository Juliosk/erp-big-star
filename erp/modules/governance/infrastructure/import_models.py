"""M23 metadata only; source XLSX belongs in private object storage."""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class ImportTemplateModel(Base):
    __tablename__ = "import_template"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_import_template_company_id"),
        UniqueConstraint("company_id", "code", name="uq_import_template_company_code"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="code_format"),
        CheckConstraint("char_length(name) BETWEEN 1 AND 200 AND name = btrim(name)", name="name"),
        CheckConstraint("target_domain = 'product'", name="target_domain"),
        Index("ix_import_template_company_code", "company_id", "code", "id"),
        {"schema": "governance"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(ForeignKey("admin.company.id", ondelete="RESTRICT"))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    target_domain: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID]


class ImportTemplateVersionModel(Base):
    __tablename__ = "import_template_version"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "template_id", "number", name="uq_import_version_company_template_number"
        ),
        ForeignKeyConstraint(
            ["company_id", "template_id"],
            ["governance.import_template.company_id", "governance.import_template.id"],
            name="fk_import_version_company_template",
            ondelete="RESTRICT",
        ),
        CheckConstraint("number >= 1", name="number"),
        CheckConstraint("schema_fingerprint ~ '^[a-f0-9]{64}$'", name="fingerprint"),
        CheckConstraint(
            "jsonb_typeof(field_definitions) = 'array' AND jsonb_array_length(field_definitions) BETWEEN 1 AND 100",
            name="fields",
        ),
        CheckConstraint(
            "cardinality(allowed_modes) BETWEEN 1 AND 3 AND array_position(allowed_modes, NULL) IS NULL AND allowed_modes <@ ARRAY['ALL_OR_NOTHING', 'VALID_ROWS_ONLY', 'BATCH_ATOMIC']::varchar[]",
            name="modes",
        ),
        {"schema": "governance"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID]
    template_id: Mapped[UUID]
    number: Mapped[int] = mapped_column(Integer)
    field_definitions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    allowed_modes: Mapped[list[str]] = mapped_column(ARRAY(String(20)))
    schema_fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID]


class ImportJobModel(OptimisticLockMixin, Base):
    __tablename__ = "import_job"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_import_job_company_id"),
        ForeignKeyConstraint(
            ["company_id", "template_id", "template_version"],
            [
                "governance.import_template_version.company_id",
                "governance.import_template_version.template_id",
                "governance.import_template_version.number",
            ],
            name="fk_import_job_company_template_version",
            ondelete="RESTRICT",
        ),
        CheckConstraint("template_version >= 1 AND version >= 1", name="versions"),
        CheckConstraint(
            "commit_mode IN ('ALL_OR_NOTHING', 'VALID_ROWS_ONLY', 'BATCH_ATOMIC')", name="mode"
        ),
        CheckConstraint(
            "status IN ('UPLOADED', 'CANCELLED', 'VALIDATED', 'REJECTED', 'PREVIEWED', 'CONFIRMED', 'COMMITTED')",
            name="status",
        ),
        CheckConstraint("source_sha256 ~ '^[a-f0-9]{64}$'", name="checksum"),
        CheckConstraint("source_size_bytes BETWEEN 1 AND 10485760", name="size"),
        CheckConstraint(
            "char_length(original_filename) BETWEEN 6 AND 255 AND original_filename = btrim(original_filename) AND lower(right(original_filename, 5)) = '.xlsx' AND original_filename !~ '[/:[:cntrl:]]' AND position(chr(92) in original_filename) = 0",
            name="filename",
        ),
        CheckConstraint(
            "storage_key = 'governance/' || company_id::text || '/imports/' || id::text || '/source.xlsx'",
            name="storage_scope",
        ),
        Index("ix_import_job_company_created", "company_id", "created_at", "id"),
        Index("ix_import_job_company_status", "company_id", "status"),
        {"schema": "governance"},
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID]
    template_id: Mapped[UUID]
    template_version: Mapped[int] = mapped_column(Integer)
    commit_mode: Mapped[str] = mapped_column(String(20))
    original_filename: Mapped[str] = mapped_column(String(255))
    source_sha256: Mapped[str] = mapped_column(String(64))
    source_size_bytes: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[UUID]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[UUID]


__all__ = ["ImportJobModel", "ImportTemplateModel", "ImportTemplateVersionModel"]
