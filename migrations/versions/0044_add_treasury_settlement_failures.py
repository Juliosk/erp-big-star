"""Add bank-settlement failure evidence to M12 Treasury.

Revision ID: 0044
Revises: 0043
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0044"
down_revision: str | None = "0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_STATUSES = (
    "DRAFT",
    "PENDING_APPROVAL",
    "APPROVED",
    "RELEASED",
    "SUBMITTED",
    "CONFIRMED",
    "REJECTED",
    "CANCELLED",
)
_NEW_STATUSES = (*_OLD_STATUSES[:-1], "FAILED", "CANCELLED")


def _status_sql(column: str, statuses: tuple[str, ...]) -> str:
    values = ", ".join(f"'{value}'" for value in statuses)
    return f"{column} IN ({values})"


def upgrade() -> None:
    op.add_column(
        "payment_batch",
        sa.Column("bank_failure_kind", sa.String(16), nullable=True),
        schema="finance",
    )
    op.add_column(
        "payment_batch",
        sa.Column("bank_failure_protocol", sa.String(120), nullable=True),
        schema="finance",
    )
    op.add_column(
        "payment_batch",
        sa.Column("bank_failure_status", sa.String(40), nullable=True),
        schema="finance",
    )
    op.add_column(
        "payment_batch",
        sa.Column("bank_failed_at", sa.DateTime(timezone=True), nullable=True),
        schema="finance",
    )
    op.add_column(
        "payment_batch",
        sa.Column("bank_failure_reason", sa.String(500), nullable=True),
        schema="finance",
    )
    for name in (
        "ck_payment_batch_status",
        "ck_payment_batch_approval_evidence",
        "ck_payment_batch_release_evidence",
        "ck_payment_batch_submission_evidence",
    ):
        op.drop_constraint(name, "payment_batch", schema="finance", type_="check")
    op.create_check_constraint(
        "ck_payment_batch_status",
        "payment_batch",
        _status_sql("status", _NEW_STATUSES),
        schema="finance",
    )
    op.create_check_constraint(
        "ck_payment_batch_approval_evidence",
        "payment_batch",
        "status NOT IN ('APPROVED', 'RELEASED', 'SUBMITTED', 'CONFIRMED', 'FAILED') "
        "OR approved_by IS NOT NULL",
        schema="finance",
    )
    op.create_check_constraint(
        "ck_payment_batch_release_evidence",
        "payment_batch",
        "status NOT IN ('RELEASED', 'SUBMITTED', 'CONFIRMED', 'FAILED') OR released_by IS NOT NULL",
        schema="finance",
    )
    op.create_check_constraint(
        "ck_payment_batch_submission_evidence",
        "payment_batch",
        "status NOT IN ('SUBMITTED', 'CONFIRMED', 'FAILED') OR "
        "(submission_protocol IS NOT NULL AND submitted_at IS NOT NULL)",
        schema="finance",
    )
    op.create_check_constraint(
        "ck_payment_batch_bank_failure",
        "payment_batch",
        "(status = 'FAILED' AND bank_failure_kind IS NOT NULL "
        "AND bank_failure_protocol IS NOT NULL AND bank_failure_status IS NOT NULL "
        "AND bank_failed_at IS NOT NULL AND bank_failure_reason IS NOT NULL) OR "
        "(status <> 'FAILED' AND bank_failure_kind IS NULL "
        "AND bank_failure_protocol IS NULL AND bank_failure_status IS NULL "
        "AND bank_failed_at IS NULL AND bank_failure_reason IS NULL)",
        schema="finance",
    )
    for name in ("ck_batch_audit_to_status", "ck_batch_audit_from_status"):
        op.drop_constraint(name, "batch_audit_log", schema="finance", type_="check")
    op.create_check_constraint(
        "ck_batch_audit_to_status",
        "batch_audit_log",
        _status_sql("to_status", _NEW_STATUSES),
        schema="finance",
    )
    op.create_check_constraint(
        "ck_batch_audit_from_status",
        "batch_audit_log",
        f"from_status IS NULL OR {_status_sql('from_status', _NEW_STATUSES)}",
        schema="finance",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_payment_batch_bank_failure",
        "payment_batch",
        schema="finance",
        type_="check",
    )
    for name in (
        "ck_payment_batch_status",
        "ck_payment_batch_approval_evidence",
        "ck_payment_batch_release_evidence",
        "ck_payment_batch_submission_evidence",
    ):
        op.drop_constraint(name, "payment_batch", schema="finance", type_="check")
    for name in ("ck_batch_audit_to_status", "ck_batch_audit_from_status"):
        op.drop_constraint(name, "batch_audit_log", schema="finance", type_="check")
    op.execute("UPDATE finance.payment_batch SET status = 'CANCELLED' WHERE status = 'FAILED'")
    op.execute("SET LOCAL erp.allow_treasury_audit_cleanup = 'on'")
    op.execute(
        "UPDATE finance.batch_audit_log SET to_status = 'CANCELLED' WHERE to_status = 'FAILED'"
    )
    op.execute(
        "UPDATE finance.batch_audit_log SET from_status = 'CANCELLED' WHERE from_status = 'FAILED'"
    )
    for column in (
        "bank_failure_reason",
        "bank_failed_at",
        "bank_failure_status",
        "bank_failure_protocol",
        "bank_failure_kind",
    ):
        op.drop_column("payment_batch", column, schema="finance")
    op.create_check_constraint(
        "ck_payment_batch_status",
        "payment_batch",
        _status_sql("status", _OLD_STATUSES),
        schema="finance",
    )
    op.create_check_constraint(
        "ck_payment_batch_approval_evidence",
        "payment_batch",
        "status NOT IN ('APPROVED', 'RELEASED', 'SUBMITTED', 'CONFIRMED') "
        "OR approved_by IS NOT NULL",
        schema="finance",
    )
    op.create_check_constraint(
        "ck_payment_batch_release_evidence",
        "payment_batch",
        "status NOT IN ('RELEASED', 'SUBMITTED', 'CONFIRMED') OR released_by IS NOT NULL",
        schema="finance",
    )
    op.create_check_constraint(
        "ck_payment_batch_submission_evidence",
        "payment_batch",
        "status NOT IN ('SUBMITTED', 'CONFIRMED') OR "
        "(submission_protocol IS NOT NULL AND submitted_at IS NOT NULL)",
        schema="finance",
    )
    op.create_check_constraint(
        "ck_batch_audit_to_status",
        "batch_audit_log",
        _status_sql("to_status", _OLD_STATUSES),
        schema="finance",
    )
    op.create_check_constraint(
        "ck_batch_audit_from_status",
        "batch_audit_log",
        f"from_status IS NULL OR {_status_sql('from_status', _OLD_STATUSES)}",
        schema="finance",
    )
