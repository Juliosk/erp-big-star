"""Extend M23 with tenant-bound staging, preview and atomic commit receipts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _guard(*, extended: bool) -> None:
    transitions = "OLD.status = 'UPLOADED' AND NEW.status = 'CANCELLED'"
    if extended:
        transitions = """
            (OLD.status IN ('UPLOADED','REJECTED','VALIDATED','PREVIEWED','CONFIRMED')
                AND NEW.status IN ('VALIDATED','REJECTED','CANCELLED'))
            OR (OLD.status = 'VALIDATED' AND NEW.status = 'PREVIEWED')
            OR (OLD.status = 'PREVIEWED' AND NEW.status = 'CONFIRMED')
            OR (OLD.status = 'CONFIRMED' AND NEW.status = 'COMMITTED')
        """
    op.execute(f"""
        CREATE OR REPLACE FUNCTION governance.guard_import_job() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'UPLOADED' OR NEW.version <> 1 THEN
                    RAISE EXCEPTION 'New import jobs must be uploaded at version 1' USING ERRCODE = '23514';
                END IF;
                IF EXISTS (SELECT 1 FROM governance.import_template_version v
                    WHERE v.company_id = NEW.company_id AND v.template_id = NEW.template_id
                    AND v.number = NEW.template_version AND NOT (NEW.commit_mode = ANY(v.allowed_modes))) THEN
                    RAISE EXCEPTION 'Commit mode is not allowed by the template version' USING ERRCODE = '23514';
                END IF;
            ELSE
                IF ROW(NEW.id, NEW.company_id, NEW.template_id, NEW.template_version, NEW.commit_mode,
                    NEW.original_filename, NEW.source_sha256, NEW.source_size_bytes, NEW.storage_key,
                    NEW.created_at, NEW.created_by) IS DISTINCT FROM
                   ROW(OLD.id, OLD.company_id, OLD.template_id, OLD.template_version, OLD.commit_mode,
                    OLD.original_filename, OLD.source_sha256, OLD.source_size_bytes, OLD.storage_key,
                    OLD.created_at, OLD.created_by)
                   OR NOT ({transitions}) OR NEW.version <> OLD.version + 1 THEN
                    RAISE EXCEPTION 'Invalid import job transition or immutable metadata change' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_import_job_company_id", "import_job", ["company_id", "id"], schema="governance"
    )
    op.drop_constraint(
        op.f("ck_import_job_status"), "import_job", schema="governance", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_import_job_status"),
        "import_job",
        "status IN ('UPLOADED', 'CANCELLED', 'VALIDATED', 'REJECTED', 'PREVIEWED', 'CONFIRMED', 'COMMITTED')",
        schema="governance",
    )
    _guard(extended=True)
    for table, columns in (
        (
            "import_staging_row",
            (
                sa.Column("row_number", sa.Integer(), primary_key=True),
                sa.Column("values", postgresql.JSONB(), nullable=False),
                sa.Column("errors", postgresql.JSONB(), nullable=False),
            ),
        ),
        (
            "import_validation_result",
            (
                sa.Column("fingerprint", sa.String(64), nullable=False),
                sa.Column("plans", postgresql.JSONB(), nullable=False),
            ),
        ),
        (
            "import_commit_batch",
            (
                sa.Column("affected_count", sa.Integer(), nullable=False),
                sa.Column("fingerprint", sa.String(64), nullable=False),
            ),
        ),
    ):
        op.create_table(
            table,
            sa.Column("company_id", sa.Uuid(), primary_key=True),
            sa.Column("job_id", sa.Uuid(), primary_key=True),
            *columns,
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("created_by", sa.Uuid(), nullable=False),
            sa.ForeignKeyConstraint(
                ["company_id", "job_id"],
                ["governance.import_job.company_id", "governance.import_job.id"],
                ondelete="RESTRICT",
            ),
            schema="governance",
        )


def downgrade() -> None:
    # Refuse data loss if processed jobs cannot be represented by the foundation schema.
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM governance.import_job
        WHERE status NOT IN ('UPLOADED','CANCELLED')) THEN
        RAISE EXCEPTION 'Processed import jobs prevent downgrade'; END IF; END $$""")
    for table in ("import_commit_batch", "import_validation_result", "import_staging_row"):
        op.drop_table(table, schema="governance")
    _guard(extended=False)
    op.drop_constraint(
        op.f("ck_import_job_status"), "import_job", schema="governance", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_import_job_status"),
        "import_job",
        "status IN ('UPLOADED', 'CANCELLED')",
        schema="governance",
    )
    op.drop_constraint(
        "uq_import_job_company_id", "import_job", schema="governance", type_="unique"
    )
