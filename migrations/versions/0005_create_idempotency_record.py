"""Create the platform idempotency record table.

Revision ID: 0005
Revises: 0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create durable command fingerprints and replayable response storage."""
    op.create_table(
        "idempotency_record",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scope", sa.String(length=150), nullable=False),
        sa.Column("operation", sa.String(length=150), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('PROCESSING', 'COMPLETED')",
            name=op.f("ck_idempotency_record_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_record")),
        sa.UniqueConstraint(
            "scope",
            "operation",
            "idempotency_key",
            name="uq_idempotency_scope_operation_key",
        ),
        schema="platform",
    )
    op.create_index(
        "ix_idempotency_record_expires_at",
        "idempotency_record",
        ["expires_at"],
        schema="platform",
    )


def downgrade() -> None:
    """Remove the idempotency table owned by this revision."""
    op.drop_index(
        "ix_idempotency_record_expires_at",
        table_name="idempotency_record",
        schema="platform",
    )
    op.drop_table("idempotency_record", schema="platform")
