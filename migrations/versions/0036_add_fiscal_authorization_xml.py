"""Store final SEFAZ authorization and cancellation XML. Revision ID: 0036. Revises: 0035."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fiscal_document", sa.Column("authorized_xml", sa.Text(), nullable=True), schema="fiscal"
    )
    op.add_column(
        "fiscal_document",
        sa.Column("cancellation_xml", sa.Text(), nullable=True),
        schema="fiscal",
    )


def downgrade() -> None:
    op.drop_column("fiscal_document", "cancellation_xml", schema="fiscal")
    op.drop_column("fiscal_document", "authorized_xml", schema="fiscal")
