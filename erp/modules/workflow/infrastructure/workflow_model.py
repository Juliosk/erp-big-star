"""SQLAlchemy mappings for the M22 Workflow Core foundation."""

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from erp.platform.concurrency import OptimisticLockMixin
from erp.platform.database import Base


class WorkflowDefinitionModel(OptimisticLockMixin, Base):
    """Company-scoped approval policy definition for one source aggregate type."""

    __tablename__ = "workflow_definition"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_workflow_definition_company_id"),
        UniqueConstraint("company_id", "code", name="uq_workflow_definition_company_code"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="code_format"),
        CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 160 AND name = btrim(name)",
            name="name_length",
        ),
        CheckConstraint(
            "source_module ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'",
            name="source_module_format",
        ),
        CheckConstraint(
            "source_type ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'",
            name="source_type_format",
        ),
        CheckConstraint(
            "approval_mode IN ('SEQUENTIAL', 'HIGHEST_LEVEL', 'CUMULATIVE')",
            name="approval_mode",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        Index(
            "ix_workflow_definition_company_source",
            "company_id",
            "active",
            "source_module",
            "source_type",
        ),
        {"schema": "workflow"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(
        ForeignKey("admin.company.id", ondelete="RESTRICT"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    source_module: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_mode: Mapped[str] = mapped_column(String(24), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class WorkflowStepDefinitionModel(Base):
    """Ordered approval step inside one workflow definition."""

    __tablename__ = "workflow_step_definition"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_workflow_step_definition_company_id"),
        UniqueConstraint(
            "company_id",
            "definition_id",
            "sequence",
            name="uq_workflow_step_definition_sequence",
        ),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="code_format"),
        CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 160 AND name = btrim(name)",
            name="name_length",
        ),
        CheckConstraint(
            "required_permission ~ '^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$'",
            name="required_permission_format",
        ),
        CheckConstraint(
            "threshold_amount IS NULL OR threshold_amount >= 0",
            name="threshold_non_negative",
        ),
        ForeignKeyConstraint(
            ["company_id", "definition_id"],
            ["workflow.workflow_definition.company_id", "workflow.workflow_definition.id"],
            name="fk_workflow_step_definition_definition",
            ondelete="RESTRICT",
        ),
        Index("ix_workflow_step_definition_parent", "company_id", "definition_id", "sequence"),
        {"schema": "workflow"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    definition_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    required_permission: Mapped[str] = mapped_column(String(120), nullable=False)
    threshold_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID] = mapped_column(nullable=False)


class WorkflowInstanceModel(OptimisticLockMixin, Base):
    """One approval workflow opened for a source aggregate instance."""

    __tablename__ = "workflow_instance"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_workflow_instance_company_id"),
        UniqueConstraint(
            "company_id",
            "source_module",
            "source_type",
            "source_id",
            "source_fingerprint",
            name="uq_workflow_instance_source_fingerprint",
        ),
        CheckConstraint(
            "source_module ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'",
            name="source_module_format",
        ),
        CheckConstraint(
            "source_type ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'",
            name="source_type_format",
        ),
        CheckConstraint(
            "char_length(btrim(source_fingerprint)) BETWEEN 1 AND 128 "
            "AND source_fingerprint = btrim(source_fingerprint)",
            name="source_fingerprint_length",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')",
            name="status",
        ),
        CheckConstraint(
            "current_step_sequence IS NULL OR current_step_sequence >= 1",
            name="current_step_sequence_positive",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        ForeignKeyConstraint(
            ["company_id", "definition_id"],
            ["workflow.workflow_definition.company_id", "workflow.workflow_definition.id"],
            name="fk_workflow_instance_definition",
            ondelete="RESTRICT",
        ),
        Index("ix_workflow_instance_company_status", "company_id", "status", "created_at"),
        Index("ix_workflow_instance_requester", "company_id", "requested_by", "status"),
        {"schema": "workflow"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    definition_id: Mapped[UUID] = mapped_column(nullable=False)
    source_module: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_id: Mapped[UUID] = mapped_column(nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    current_step_sequence: Mapped[int | None] = mapped_column(nullable=True)
    requested_by: Mapped[UUID] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class WorkflowStepInstanceModel(OptimisticLockMixin, Base):
    """Executable step state for one workflow instance."""

    __tablename__ = "workflow_step_instance"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_workflow_step_instance_company_id"),
        UniqueConstraint(
            "company_id",
            "workflow_instance_id",
            "sequence",
            name="uq_workflow_step_instance_sequence",
        ),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
        CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name="code_format"),
        CheckConstraint(
            "char_length(btrim(name)) BETWEEN 1 AND 160 AND name = btrim(name)",
            name="name_length",
        ),
        CheckConstraint(
            "required_permission ~ '^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$'",
            name="required_permission_format",
        ),
        CheckConstraint(
            "status IN ('WAITING', 'ACTIVE', 'APPROVED', 'REJECTED', 'SKIPPED')",
            name="status",
        ),
        CheckConstraint(
            "status != 'ACTIVE' OR activated_at IS NOT NULL",
            name="active_requires_activation",
        ),
        CheckConstraint(
            "status NOT IN ('APPROVED', 'REJECTED') "
            "OR (decided_at IS NOT NULL AND decided_by IS NOT NULL)",
            name="decision_requires_actor_timestamp",
        ),
        CheckConstraint("version >= 1", name="version_positive"),
        ForeignKeyConstraint(
            ["company_id", "workflow_instance_id"],
            ["workflow.workflow_instance.company_id", "workflow.workflow_instance.id"],
            name="fk_workflow_step_instance_instance",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_workflow_step_instance_pending",
            "company_id",
            "status",
            "required_permission",
        ),
        {"schema": "workflow"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    workflow_instance_id: Mapped[UUID] = mapped_column(nullable=False)
    sequence: Mapped[int] = mapped_column(nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    required_permission: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[UUID] = mapped_column(nullable=False)


class ApprovalDecisionModel(Base):
    """Immutable approval or rejection decision audit trail owned by M22."""

    __tablename__ = "approval_decision"
    __table_args__ = (
        UniqueConstraint("company_id", "id", name="uq_approval_decision_company_id"),
        CheckConstraint("decision IN ('APPROVED', 'REJECTED')", name="decision"),
        CheckConstraint(
            "reason_code IS NULL OR reason_code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'",
            name="reason_code_format",
        ),
        CheckConstraint(
            "comment IS NULL OR char_length(comment) <= 500",
            name="comment_length",
        ),
        ForeignKeyConstraint(
            ["company_id", "workflow_instance_id"],
            ["workflow.workflow_instance.company_id", "workflow.workflow_instance.id"],
            name="fk_approval_decision_instance",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["company_id", "step_instance_id"],
            ["workflow.workflow_step_instance.company_id", "workflow.workflow_step_instance.id"],
            name="fk_approval_decision_step",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_approval_decision_instance",
            "company_id",
            "workflow_instance_id",
            "decided_at",
        ),
        {"schema": "workflow"},
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    company_id: Mapped[UUID] = mapped_column(nullable=False)
    workflow_instance_id: Mapped[UUID] = mapped_column(nullable=False)
    step_instance_id: Mapped[UUID] = mapped_column(nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_by: Mapped[UUID] = mapped_column(nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(500), nullable=True)


__all__ = [
    "ApprovalDecisionModel",
    "WorkflowDefinitionModel",
    "WorkflowInstanceModel",
    "WorkflowStepDefinitionModel",
    "WorkflowStepInstanceModel",
]
