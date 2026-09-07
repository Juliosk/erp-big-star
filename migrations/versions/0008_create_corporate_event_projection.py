"""Create the first controlled M1 event projection.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create an immutable, event-keyed corporate projection."""
    op.create_table(
        "corporate_event_projection",
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_type", sa.String(length=150), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "projected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "aggregate_version >= 1",
            name=op.f("ck_corporate_event_projection_version_positive"),
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_corporate_event_projection")),
        schema="admin",
    )
    op.create_index(
        "ix_corporate_projection_company",
        "corporate_event_projection",
        ["company_id", "projected_at"],
        schema="admin",
    )
    op.create_index(
        "ix_corporate_projection_branch",
        "corporate_event_projection",
        ["branch_id", "projected_at"],
        schema="admin",
    )


def downgrade() -> None:
    """Remove the disposable first corporate read model."""
    op.drop_table("corporate_event_projection", schema="admin")
