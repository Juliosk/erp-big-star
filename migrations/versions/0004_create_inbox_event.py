"""Create the platform Inbox table.

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the consumer/message idempotency ledger."""
    op.create_table(
        "inbox_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("consumer_name", sa.String(length=150), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=150), nullable=False),
        sa.Column("event_version", sa.Integer(), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('PROCESSING', 'PROCESSED', 'FAILED')",
            name=op.f("ck_inbox_event_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inbox_event")),
        sa.UniqueConstraint("consumer_name", "event_id", name="uq_inbox_event_consumer_event"),
        schema="platform",
    )
    op.create_index(
        "ix_inbox_event_status_received",
        "inbox_event",
        ["status", "received_at"],
        schema="platform",
    )


def downgrade() -> None:
    """Remove the Inbox table owned by this revision."""
    op.drop_index("ix_inbox_event_status_received", table_name="inbox_event", schema="platform")
    op.drop_table("inbox_event", schema="platform")
