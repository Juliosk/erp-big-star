"""Create the append-only platform audit event table.

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the durable audit table and its lookup indexes."""
    op.create_table(
        "audit_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("module", sa.String(length=32), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("before_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_ip", sa.String(length=45), nullable=True),
        sa.Column("device_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_event")),
        schema="platform",
    )
    op.create_index(
        "ix_audit_event_entity",
        "audit_event",
        ["module", "entity_type", "entity_id"],
        schema="platform",
    )
    op.create_index(
        "ix_audit_event_correlation_id",
        "audit_event",
        ["correlation_id"],
        schema="platform",
    )


def downgrade() -> None:
    """Remove the audit table owned by this revision."""
    op.drop_index("ix_audit_event_correlation_id", table_name="audit_event", schema="platform")
    op.drop_index("ix_audit_event_entity", table_name="audit_event", schema="platform")
    op.drop_table("audit_event", schema="platform")
