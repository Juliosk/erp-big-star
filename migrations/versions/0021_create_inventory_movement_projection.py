"""Create M5 asynchronous movement projection.

Revision ID: 0021
Revises: 0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add event-keyed projection proving idempotent M5 async consumption."""
    op.create_table(
        "inventory_movement_projection",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_type", sa.String(length=150), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("transaction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("posting_count", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "projected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "aggregate_version >= 1",
            name=op.f("ck_inventory_movement_projection_version_positive"),
        ),
        sa.CheckConstraint(
            "posting_count >= 1",
            name=op.f("ck_inventory_movement_projection_posting_count_positive"),
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_inventory_movement_projection")),
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_movement_projection_company",
        "inventory_movement_projection",
        ["company_id", "projected_at"],
        schema="inventory",
    )
    op.create_index(
        "ix_inventory_movement_projection_transaction",
        "inventory_movement_projection",
        ["company_id", "transaction_id"],
        schema="inventory",
    )


def downgrade() -> None:
    """Destructive for M5 projection data; use only with explicit approval."""
    op.drop_table("inventory_movement_projection", schema="inventory")
