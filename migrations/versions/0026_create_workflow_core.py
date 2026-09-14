"""Create M22 Workflow Core tables.

Revision ID: 0026
Revises: 0025
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add company-scoped workflow definitions, instances and decisions."""
    op.execute(sa.text("CREATE SCHEMA IF NOT EXISTS workflow"))
    op.create_table(
        "workflow_definition",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("source_module", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("approval_mode", sa.String(length=24), nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("approval_mode IN ('SEQUENTIAL', 'HIGHEST_LEVEL', 'CUMULATIVE')", name=op.f("ck_workflow_definition_approval_mode")),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_workflow_definition_code_format")),
        sa.CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 160 AND name = btrim(name)", name=op.f("ck_workflow_definition_name_length")),
        sa.CheckConstraint("source_module ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'", name=op.f("ck_workflow_definition_source_module_format")),
        sa.CheckConstraint("source_type ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_workflow_definition_source_type_format")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_workflow_definition_version_positive")),
        sa.ForeignKeyConstraint(["company_id"], ["admin.company.id"], name=op.f("fk_workflow_definition_company_id_company"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_definition")),
        sa.UniqueConstraint("company_id", "code", name=op.f("uq_workflow_definition_company_code")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_workflow_definition_company_id")),
        schema="workflow",
    )
    op.create_index(
        "ix_workflow_definition_company_source",
        "workflow_definition",
        ["company_id", "active", "source_module", "source_type"],
        schema="workflow",
    )
    op.create_table(
        "workflow_step_definition",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("required_permission", sa.String(length=120), nullable=False),
        sa.Column("threshold_amount", sa.Numeric(18, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_workflow_step_definition_code_format")),
        sa.CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 160 AND name = btrim(name)", name=op.f("ck_workflow_step_definition_name_length")),
        sa.CheckConstraint("required_permission ~ '^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$'", name=op.f("ck_workflow_step_definition_required_permission_format")),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_workflow_step_definition_sequence_positive")),
        sa.CheckConstraint("threshold_amount IS NULL OR threshold_amount >= 0", name=op.f("ck_workflow_step_definition_threshold_non_negative")),
        sa.ForeignKeyConstraint(["company_id", "definition_id"], ["workflow.workflow_definition.company_id", "workflow.workflow_definition.id"], name=op.f("fk_workflow_step_definition_definition"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_step_definition")),
        sa.UniqueConstraint("company_id", "definition_id", "sequence", name=op.f("uq_workflow_step_definition_sequence")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_workflow_step_definition_company_id")),
        schema="workflow",
    )
    op.create_index(
        "ix_workflow_step_definition_parent",
        "workflow_step_definition",
        ["company_id", "definition_id", "sequence"],
        schema="workflow",
    )
    op.create_table(
        "workflow_instance",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_module", sa.String(length=32), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("current_step_sequence", sa.Integer(), nullable=True),
        sa.Column("requested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("char_length(btrim(source_fingerprint)) BETWEEN 1 AND 128 AND source_fingerprint = btrim(source_fingerprint)", name=op.f("ck_workflow_instance_source_fingerprint_length")),
        sa.CheckConstraint("current_step_sequence IS NULL OR current_step_sequence >= 1", name=op.f("ck_workflow_instance_current_step_sequence_positive")),
        sa.CheckConstraint("source_module ~ '^[A-Z0-9][A-Z0-9._-]{0,31}$'", name=op.f("ck_workflow_instance_source_module_format")),
        sa.CheckConstraint("source_type ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_workflow_instance_source_type_format")),
        sa.CheckConstraint("status IN ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED')", name=op.f("ck_workflow_instance_status")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_workflow_instance_version_positive")),
        sa.ForeignKeyConstraint(["company_id", "definition_id"], ["workflow.workflow_definition.company_id", "workflow.workflow_definition.id"], name=op.f("fk_workflow_instance_definition"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_instance")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_workflow_instance_company_id")),
        sa.UniqueConstraint("company_id", "source_module", "source_type", "source_id", "source_fingerprint", name=op.f("uq_workflow_instance_source_fingerprint")),
        schema="workflow",
    )
    op.create_index(
        "ix_workflow_instance_company_status",
        "workflow_instance",
        ["company_id", "status", "created_at"],
        schema="workflow",
    )
    op.create_index(
        "ix_workflow_instance_requester",
        "workflow_instance",
        ["company_id", "requested_by", "status"],
        schema="workflow",
    )
    op.create_table(
        "workflow_step_instance",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("required_permission", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.CheckConstraint("code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_workflow_step_instance_code_format")),
        sa.CheckConstraint("char_length(btrim(name)) BETWEEN 1 AND 160 AND name = btrim(name)", name=op.f("ck_workflow_step_instance_name_length")),
        sa.CheckConstraint("required_permission ~ '^[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*\\.[a-z][a-z0-9_]*$'", name=op.f("ck_workflow_step_instance_required_permission_format")),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_workflow_step_instance_sequence_positive")),
        sa.CheckConstraint("status != 'ACTIVE' OR activated_at IS NOT NULL", name=op.f("ck_workflow_step_instance_active_requires_activation")),
        sa.CheckConstraint("status IN ('WAITING', 'ACTIVE', 'APPROVED', 'REJECTED', 'SKIPPED')", name=op.f("ck_workflow_step_instance_status")),
        sa.CheckConstraint("status NOT IN ('APPROVED', 'REJECTED') OR (decided_at IS NOT NULL AND decided_by IS NOT NULL)", name=op.f("ck_workflow_step_instance_decision_requires_actor_timestamp")),
        sa.CheckConstraint("version >= 1", name=op.f("ck_workflow_step_instance_version_positive")),
        sa.ForeignKeyConstraint(["company_id", "workflow_instance_id"], ["workflow.workflow_instance.company_id", "workflow.workflow_instance.id"], name=op.f("fk_workflow_step_instance_instance"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workflow_step_instance")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_workflow_step_instance_company_id")),
        sa.UniqueConstraint("company_id", "workflow_instance_id", "sequence", name=op.f("uq_workflow_step_instance_sequence")),
        schema="workflow",
    )
    op.create_index(
        "ix_workflow_step_instance_pending",
        "workflow_step_instance",
        ["company_id", "status", "required_permission"],
        schema="workflow",
    )
    op.create_table(
        "approval_decision",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("step_instance_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("decided_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.CheckConstraint("comment IS NULL OR char_length(comment) <= 500", name=op.f("ck_approval_decision_comment_length")),
        sa.CheckConstraint("decision IN ('APPROVED', 'REJECTED')", name=op.f("ck_approval_decision_decision")),
        sa.CheckConstraint("reason_code IS NULL OR reason_code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_approval_decision_reason_code_format")),
        sa.ForeignKeyConstraint(["company_id", "step_instance_id"], ["workflow.workflow_step_instance.company_id", "workflow.workflow_step_instance.id"], name=op.f("fk_approval_decision_step"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id", "workflow_instance_id"], ["workflow.workflow_instance.company_id", "workflow.workflow_instance.id"], name=op.f("fk_approval_decision_instance"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_decision")),
        sa.UniqueConstraint("company_id", "id", name=op.f("uq_approval_decision_company_id")),
        schema="workflow",
    )
    op.create_index(
        "ix_approval_decision_instance",
        "approval_decision",
        ["company_id", "workflow_instance_id", "decided_at"],
        schema="workflow",
    )


def downgrade() -> None:
    """Destructive for Workflow data; use only with explicit approval."""
    op.drop_table("approval_decision", schema="workflow")
    op.drop_table("workflow_step_instance", schema="workflow")
    op.drop_table("workflow_instance", schema="workflow")
    op.drop_table("workflow_step_definition", schema="workflow")
    op.drop_table("workflow_definition", schema="workflow")
    op.execute(sa.text("DROP SCHEMA IF EXISTS workflow"))
