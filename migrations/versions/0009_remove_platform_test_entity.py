"""Remove the disposable Sprint 1 acceptance entity.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Drop the temporary table after the corporate E2E replaces its purpose."""
    op.drop_table("test_entity", schema="platform")


def downgrade() -> None:
    """Restore the historical validation table for a reversible rollback."""
    op.create_table(
        "test_entity",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version >= 1", name=op.f("ck_test_entity_version_positive")),
        sa.CheckConstraint(
            "status IN ('CREATED', 'CONSUMED')",
            name=op.f("ck_test_entity_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_test_entity")),
        schema="platform",
    )
