"""Real PostgreSQL migration constraints and immutable version enforcement."""

import asyncio
from dataclasses import asdict
from typing import Any, cast
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, Table, insert, inspect, update
from sqlalchemy.exc import IntegrityError

from erp.modules.governance.domain import ImportJob
from erp.modules.governance.infrastructure import (
    ImportJobModel,
    ImportTemplateModel,
    ImportTemplateVersionModel,
)
from erp.platform.config import get_settings
from erp.platform.database import Base, Database
from tests.integration.import_support import import_fixture, new_job, new_template, seed_import

pytestmark = pytest.mark.integration


def _only_governance(
    obj: Any, name: str | None, kind: str, reflected: bool, compare_to: Any
) -> bool:
    return kind != "table" or obj.schema == "governance"


def test_import_migration_matches_models_and_tenant_foreign_keys() -> None:
    def verify(connection: Connection) -> None:
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema="governance")) == {
            "import_template",
            "import_template_version",
            "import_job",
            "import_staging_row",
            "import_validation_result",
            "import_commit_batch",
        }
        for model in (ImportTemplateModel, ImportTemplateVersionModel, ImportJobModel):
            columns = inspector.get_columns(model.__tablename__, schema="governance")
            assert {column["name"] for column in columns} == set(model.__table__.columns.keys())
            assert all(not column["nullable"] for column in columns)
        fk = inspector.get_foreign_keys("import_job", schema="governance")[0]
        assert fk["constrained_columns"] == ["company_id", "template_id", "template_version"]
        assert fk["options"]["ondelete"] == "RESTRICT"
        context = MigrationContext.configure(
            connection,
            opts={
                "include_schemas": True,
                "include_object": _only_governance,
                "compare_type": True,
                "compare_server_default": True,
            },
        )
        assert compare_metadata(context, Base.metadata) == []

    async def scenario() -> None:
        database = Database(get_settings())
        try:
            async with database.engine.connect() as connection:
                await connection.run_sync(verify)
        finally:
            await database.dispose()

    asyncio.run(scenario())


def test_published_template_version_cannot_be_updated() -> None:
    async def scenario() -> None:
        async with import_fixture() as data:
            _, version, _ = await seed_import(data)
            async with data.database.session() as session:
                with pytest.raises(IntegrityError, match="immutable"):
                    await session.execute(
                        update(ImportTemplateVersionModel)
                        .where(ImportTemplateVersionModel.id == version.id)
                        .values(schema_fingerprint="b" * 64)
                    )
                await session.rollback()
                unchanged = await session.get(ImportTemplateVersionModel, version.id)
                assert unchanged is not None
                assert unchanged.schema_fingerprint == version.fingerprint

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "changes",
    [
        {"source_size_bytes": 0},
        {"source_sha256": "BAD"},
        {"original_filename": "../test.xlsx"},
        {"original_filename": "C:\\test.xlsx"},
        {"storage_key": "foreign/source.xlsx"},
        {"commit_mode": "VALID_ROWS_ONLY"},
        {"version": 2},
        {"status": "CANCELLED"},
        {"template_version": 999},
    ],
)
def test_database_rejects_invalid_or_unapproved_job_metadata(changes: dict[str, Any]) -> None:
    async def scenario() -> None:
        async with import_fixture() as data:
            template, _, _ = await seed_import(data)
            values = {**asdict(new_job(template)), **changes}
            async with data.database.session() as session:
                with pytest.raises(IntegrityError):
                    # Core INSERT preserves the supplied version; the ORM's version generator
                    # intentionally starts mapped objects at 1 before sending SQL.
                    await session.execute(
                        insert(cast(Table, ImportJobModel.__table__)).values(
                            **values, created_by=data.actor_id, updated_by=data.actor_id
                        )
                    )
                await session.rollback()

    asyncio.run(scenario())


def test_company_template_code_uniqueness_and_cross_tenant_version_fk() -> None:
    async def scenario() -> None:
        async with import_fixture() as data:
            template, _, job = await seed_import(data)
            async with data.database.session() as session:
                session.add(
                    ImportTemplateModel(**asdict(new_template(data)), created_by=data.actor_id)
                )
                with pytest.raises(IntegrityError):
                    await session.flush()
                await session.rollback()
                other = new_template(data, other=True)
                session.add(ImportTemplateModel(**asdict(other), created_by=data.actor_id))
                await session.commit()
                forged = {**asdict(job), "id": uuid4(), "company_id": other.company_id}
                forged["storage_key"] = ImportJob.expected_storage_key(
                    other.company_id, forged["id"]
                )
                session.add(
                    ImportJobModel(**forged, created_by=data.actor_id, updated_by=data.actor_id)
                )
                with pytest.raises(IntegrityError):
                    await session.flush()
                await session.rollback()
                assert template.id != other.id

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "changes",
    [
        {"source_sha256": "b" * 64, "status": "CANCELLED", "version": 2},
        {"status": "UPLOADED", "version": 2},
        {"status": "CANCELLED", "version": 1},
    ],
)
def test_database_blocks_metadata_rewrites_and_invalid_transitions(changes: dict[str, Any]) -> None:
    async def scenario() -> None:
        async with import_fixture() as data:
            _, _, job = await seed_import(data)
            async with data.database.session() as session:
                with pytest.raises(IntegrityError, match="Invalid import job"):
                    await session.execute(
                        update(ImportJobModel).where(ImportJobModel.id == job.id).values(**changes)
                    )
                await session.rollback()

    asyncio.run(scenario())
