"""Create tenant-owned M23 import templates, immutable versions and job metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.schema.CreateSchema("governance"))
    op.create_table(
        "import_template",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("admin.company.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("target_domain", sa.String(32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.UniqueConstraint("company_id", "id", name="uq_import_template_company_id"),
        sa.UniqueConstraint("company_id", "code", name="uq_import_template_company_code"),
        sa.CheckConstraint(
            "code ~ '^[A-Z0-9][A-Z0-9._-]{0,63}$'", name=op.f("ck_import_template_code_format")
        ),
        sa.CheckConstraint(
            "char_length(name) BETWEEN 1 AND 200 AND name = btrim(name)",
            name=op.f("ck_import_template_name"),
        ),
        sa.CheckConstraint(
            "target_domain = 'product'", name=op.f("ck_import_template_target_domain")
        ),
        schema="governance",
    )
    op.create_index(
        "ix_import_template_company_code",
        "import_template",
        ["company_id", "code", "id"],
        schema="governance",
    )
    op.create_table(
        "import_template_version",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("field_definitions", postgresql.JSONB(), nullable=False),
        sa.Column("allowed_modes", postgresql.ARRAY(sa.String(20)), nullable=False),
        sa.Column("schema_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.UniqueConstraint(
            "company_id", "template_id", "number", name="uq_import_version_company_template_number"
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "template_id"],
            ["governance.import_template.company_id", "governance.import_template.id"],
            name="fk_import_version_company_template",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("number >= 1", name=op.f("ck_import_template_version_number")),
        sa.CheckConstraint(
            "schema_fingerprint ~ '^[a-f0-9]{64}$'",
            name=op.f("ck_import_template_version_fingerprint"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(field_definitions) = 'array' AND jsonb_array_length(field_definitions) BETWEEN 1 AND 100",
            name=op.f("ck_import_template_version_fields"),
        ),
        sa.CheckConstraint(
            "cardinality(allowed_modes) BETWEEN 1 AND 3 AND array_position(allowed_modes, NULL) IS NULL AND allowed_modes <@ ARRAY['ALL_OR_NOTHING', 'VALID_ROWS_ONLY', 'BATCH_ATOMIC']::varchar[]",
            name=op.f("ck_import_template_version_modes"),
        ),
        schema="governance",
    )
    op.create_table(
        "import_job",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("commit_mode", sa.String(20), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("source_size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id", "template_id", "template_version"],
            [
                "governance.import_template_version.company_id",
                "governance.import_template_version.template_id",
                "governance.import_template_version.number",
            ],
            name="fk_import_job_company_template_version",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "template_version >= 1 AND version >= 1", name=op.f("ck_import_job_versions")
        ),
        sa.CheckConstraint(
            "commit_mode IN ('ALL_OR_NOTHING', 'VALID_ROWS_ONLY', 'BATCH_ATOMIC')",
            name=op.f("ck_import_job_mode"),
        ),
        sa.CheckConstraint(
            "status IN ('UPLOADED', 'CANCELLED')", name=op.f("ck_import_job_status")
        ),
        sa.CheckConstraint("source_sha256 ~ '^[a-f0-9]{64}$'", name=op.f("ck_import_job_checksum")),
        sa.CheckConstraint(
            "source_size_bytes BETWEEN 1 AND 10485760", name=op.f("ck_import_job_size")
        ),
        sa.CheckConstraint(
            "char_length(original_filename) BETWEEN 6 AND 255 AND original_filename = btrim(original_filename) AND lower(right(original_filename, 5)) = '.xlsx' AND original_filename !~ '[/:[:cntrl:]]' AND position(chr(92) in original_filename) = 0",
            name=op.f("ck_import_job_filename"),
        ),
        sa.CheckConstraint(
            "storage_key = 'governance/' || company_id::text || '/imports/' || id::text || '/source.xlsx'",
            name=op.f("ck_import_job_storage_scope"),
        ),
        schema="governance",
    )
    op.create_index(
        "ix_import_job_company_created",
        "import_job",
        ["company_id", "created_at", "id"],
        schema="governance",
    )
    op.create_index(
        "ix_import_job_company_status", "import_job", ["company_id", "status"], schema="governance"
    )
    op.execute("""
        CREATE FUNCTION governance.reject_import_version_update() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            RAISE EXCEPTION 'Import template versions are immutable; insert a new version'
                USING ERRCODE = '23514';
        END $$
    """)
    op.execute("""
        CREATE TRIGGER import_version_immutable BEFORE UPDATE ON governance.import_template_version
        FOR EACH ROW EXECUTE FUNCTION governance.reject_import_version_update()
    """)
    op.execute("""
        CREATE FUNCTION governance.guard_import_job() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.status <> 'UPLOADED' OR NEW.version <> 1 THEN
                    RAISE EXCEPTION 'New import jobs must be uploaded at version 1' USING ERRCODE = '23514';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM governance.import_template_version v
                    WHERE v.company_id = NEW.company_id AND v.template_id = NEW.template_id
                    AND v.number = NEW.template_version AND NOT (NEW.commit_mode = ANY(v.allowed_modes))
                ) THEN
                    RAISE EXCEPTION 'Commit mode is not allowed by the template version' USING ERRCODE = '23514';
                END IF;
            ELSE
                IF ROW(NEW.id, NEW.company_id, NEW.template_id, NEW.template_version, NEW.commit_mode,
                       NEW.original_filename, NEW.source_sha256, NEW.source_size_bytes, NEW.storage_key,
                       NEW.created_at, NEW.created_by)
                   IS DISTINCT FROM
                   ROW(OLD.id, OLD.company_id, OLD.template_id, OLD.template_version, OLD.commit_mode,
                       OLD.original_filename, OLD.source_sha256, OLD.source_size_bytes, OLD.storage_key,
                       OLD.created_at, OLD.created_by)
                   OR OLD.status <> 'UPLOADED' OR NEW.status <> 'CANCELLED' OR NEW.version <> OLD.version + 1
                THEN
                    RAISE EXCEPTION 'Invalid import job transition or immutable metadata change' USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER import_job_guard BEFORE INSERT OR UPDATE ON governance.import_job
        FOR EACH ROW EXECUTE FUNCTION governance.guard_import_job()
    """)


def downgrade() -> None:
    op.drop_table("import_job", schema="governance")
    op.execute("DROP FUNCTION governance.guard_import_job()")
    op.drop_table("import_template_version", schema="governance")
    op.execute("DROP FUNCTION governance.reject_import_version_update()")
    op.drop_table("import_template", schema="governance")
    op.execute(sa.schema.DropSchema("governance"))
