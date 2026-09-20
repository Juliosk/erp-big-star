"""Add M4 hold expiration projection. Revision ID: 0030. Revises: 0029."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sales_order_reservation",
        sa.Column("hold_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="sales_b2b",
    )
    op.drop_constraint(
        op.f("ck_sales_order_reservation_status"),
        "sales_order_reservation",
        schema="sales_b2b",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_sales_order_reservation_status"),
        "sales_order_reservation",
        "status IN ('REQUESTED', 'HELD', 'RELEASED', 'CANCELLED', 'EXPIRED')",
        schema="sales_b2b",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_sales_order_reservation_status"),
        "sales_order_reservation",
        schema="sales_b2b",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_sales_order_reservation_status"),
        "sales_order_reservation",
        "status IN ('REQUESTED', 'HELD', 'RELEASED', 'CANCELLED')",
        schema="sales_b2b",
    )
    op.drop_column(
        "sales_order_reservation", "hold_expires_at", schema="sales_b2b"
    )
