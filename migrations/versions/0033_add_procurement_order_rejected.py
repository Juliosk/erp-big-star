"""Allow rejected purchase orders. Revision ID: 0033. Revises: 0032."""

from collections.abc import Sequence

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = "status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'ISSUED', 'PARTIALLY_RECEIVED', 'COMPLETED', 'CANCELLED')"
_NEW = "status IN ('DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'ISSUED', 'PARTIALLY_RECEIVED', 'COMPLETED', 'CANCELLED')"


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_purchase_order_status"), "purchase_order", schema="procurement", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_purchase_order_status"), "purchase_order", _NEW, schema="procurement"
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_purchase_order_status"), "purchase_order", schema="procurement", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_purchase_order_status"), "purchase_order", _OLD, schema="procurement"
    )
