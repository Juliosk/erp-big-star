"""M23 persistence never commits implicitly or widens a company's scope."""

import asyncio
from dataclasses import replace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from erp.modules.governance.domain import ImportCommitMode, ImportJob, ImportJobStatus
from erp.modules.governance.infrastructure import (
    ImportJobModel,
    ImportJobRepository,
    ImportTemplateRepository,
    ImportTemplateVersionModel,
)
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError
from tests.integration.import_support import (
    import_fixture,
    new_job,
    new_template,
    new_version,
    seed_import,
)

pytestmark = pytest.mark.integration


def test_import_round_trip_versions_actors_and_cancellation() -> None:
    async def scenario() -> None:
        async with import_fixture() as data:
            template = new_template(data)
            version = new_version(template)
            job = new_job(template)
            actor = uuid4()
            async with data.database.session() as session, session.begin():
                templates = ImportTemplateRepository(session, company_id=data.company_id)
                jobs = ImportJobRepository(session, company_id=data.company_id)
                await templates.add(template, actor_id=data.actor_id)
                await templates.add_version(version, actor_id=data.actor_id)
                await jobs.add(job, actor_id=data.actor_id)
                assert await templates.get(template.id) == template
                assert await templates.get_version(template.id, 1) == version
                assert await templates.list() == (template,)
                assert await jobs.get(job.id) == job
                assert await jobs.list(status=ImportJobStatus.UPLOADED) == (job,)
                assert await jobs.save(job.cancel(), actor_id=actor) == job.cancel()
                assert await jobs.get(job.id) == job.cancel()
                assert await jobs.list(status=ImportJobStatus.UPLOADED) == ()
                assert await jobs.list(status=ImportJobStatus.CANCELLED) == (job.cancel(),)
                assert await jobs.list(offset=1) == ()
            async with data.database.session() as session:
                row = await session.get(ImportJobModel, job.id)
                assert row is not None
                assert row.created_by == data.actor_id
                assert row.updated_by == actor
                assert row.updated_at >= row.created_at
                assert row.version == 2

    asyncio.run(scenario())


def test_read_and_write_scope_and_forged_snapshot_are_denied() -> None:
    async def scenario() -> None:
        async with import_fixture() as data:
            template, version, job = await seed_import(data)
            async with data.database.session() as session:
                foreign_templates = ImportTemplateRepository(
                    session, company_id=data.other_company_id
                )
                foreign_jobs = ImportJobRepository(session, company_id=data.other_company_id)
                assert await foreign_templates.get(template.id) is None
                assert await foreign_templates.get_version(template.id, 1) is None
                assert await foreign_templates.list() == ()
                assert await foreign_jobs.get(job.id) is None
                assert await foreign_jobs.list() == ()
                with pytest.raises(ApplicationError, match="outside"):
                    await foreign_templates.add(template, actor_id=data.actor_id)
                with pytest.raises(ApplicationError, match="outside"):
                    await foreign_templates.add_version(version, actor_id=data.actor_id)
                with pytest.raises(ApplicationError, match="outside"):
                    await foreign_jobs.add(job, actor_id=data.actor_id)
                with pytest.raises(ApplicationError, match="outside"):
                    await foreign_jobs.save(job.cancel(), actor_id=data.actor_id)
                forged = replace(
                    job.cancel(),
                    company_id=data.other_company_id,
                    storage_key=ImportJob.expected_storage_key(data.other_company_id, job.id),
                )
                with pytest.raises(OptimisticLockError):
                    await foreign_jobs.save(forged, actor_id=data.actor_id)
                await session.rollback()
                assert (
                    await ImportJobRepository(session, company_id=data.company_id).get(job.id)
                    == job
                )

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["template", "version", "job"])
def test_duplicate_identifiers_fail_without_partial_commit(operation: str) -> None:
    async def scenario() -> None:
        async with import_fixture() as data:
            template, version, job = await seed_import(data)
            async with data.database.session() as session:
                templates = ImportTemplateRepository(session, company_id=data.company_id)
                if operation == "template":
                    command = templates.add(replace(template, id=uuid4()), actor_id=data.actor_id)
                elif operation == "version":
                    command = templates.add_version(
                        replace(version, id=uuid4()), actor_id=data.actor_id
                    )
                else:
                    command = ImportJobRepository(session, company_id=data.company_id).add(
                        job, actor_id=data.actor_id
                    )
                with pytest.raises(ApplicationError, match="already exists") as captured:
                    await command
                assert captured.value.status_code == 409
                await session.rollback()

    asyncio.run(scenario())


def test_repositories_leave_rollback_control_to_the_caller() -> None:
    async def scenario() -> None:
        async with import_fixture() as data:
            template = new_template(data)
            job = new_job(template)
            async with data.database.session() as session:
                templates = ImportTemplateRepository(session, company_id=data.company_id)
                jobs = ImportJobRepository(session, company_id=data.company_id)
                await templates.add(template, actor_id=data.actor_id)
                await templates.add_version(new_version(template), actor_id=data.actor_id)
                await jobs.add(job, actor_id=data.actor_id)
                await session.rollback()
                assert await templates.get(template.id) is None
                assert await templates.get_version(template.id, 1) is None
                assert await jobs.get(job.id) is None

    asyncio.run(scenario())


def test_concurrent_cancellations_have_exactly_one_winner() -> None:
    async def scenario() -> None:
        async with import_fixture() as data:
            _, _, job = await seed_import(data)
            barrier = asyncio.Barrier(2)

            async def cancel() -> str:
                try:
                    async with data.database.session() as session, session.begin():
                        repository = ImportJobRepository(session, company_id=data.company_id)
                        current = await repository.get(job.id)
                        assert current is not None
                        await barrier.wait()
                        await repository.save(current.cancel(), actor_id=data.actor_id)
                    return "saved"
                except OptimisticLockError:
                    return "conflict"

            assert sorted(await asyncio.gather(cancel(), cancel())) == ["conflict", "saved"]

    asyncio.run(scenario())


def test_concurrent_template_version_numbers_are_unique() -> None:
    async def scenario() -> None:
        async with import_fixture() as data:
            template, _, _ = await seed_import(data)

            async def publish() -> str:
                try:
                    async with data.database.session() as session, session.begin():
                        await ImportTemplateRepository(
                            session, company_id=data.company_id
                        ).add_version(new_version(template, number=2), actor_id=data.actor_id)
                    return "saved"
                except ApplicationError as error:
                    return error.code

            assert sorted(await asyncio.gather(publish(), publish())) == [
                "IMPORT_TEMPLATE_VERSION_CONFLICT",
                "saved",
            ]

    asyncio.run(scenario())


@pytest.mark.parametrize("repository_type", [ImportTemplateRepository, ImportJobRepository])
@pytest.mark.parametrize(
    "kwargs", [{"limit": 0}, {"limit": 101}, {"limit": True}, {"offset": -1}, {"offset": True}]
)
def test_directory_limits_are_strict(repository_type: Any, kwargs: dict[str, Any]) -> None:
    async def scenario() -> None:
        async with import_fixture() as data, data.database.session() as session:
            with pytest.raises(ValueError, match=r"limit|offset"):
                await repository_type(session, company_id=data.company_id).list(**kwargs)

    asyncio.run(scenario())


def test_missing_template_disallowed_mode_and_invalid_lifecycle_are_rejected() -> None:
    async def scenario() -> None:
        async with import_fixture() as data:
            template, _, job = await seed_import(data)
            async with data.database.session() as session:
                templates = ImportTemplateRepository(session, company_id=data.company_id)
                jobs = ImportJobRepository(session, company_id=data.company_id)
                with pytest.raises(ApplicationError, match="not found"):
                    await templates.add_version(
                        new_version(new_template(data)), actor_id=data.actor_id
                    )
                with pytest.raises(ApplicationError, match="not found"):
                    await jobs.add(
                        replace(new_job(template), template_version=999), actor_id=data.actor_id
                    )
                with pytest.raises(ApplicationError, match="not enabled"):
                    await jobs.add(
                        replace(new_job(template), commit_mode=ImportCommitMode.VALID_ROWS_ONLY),
                        actor_id=data.actor_id,
                    )
                with pytest.raises(ValueError, match="uploaded"):
                    await jobs.add(job.cancel(), actor_id=data.actor_id)
                with pytest.raises(ValueError, match="incremented"):
                    await jobs.save(job, actor_id=data.actor_id)
                with pytest.raises(ValueError, match="status"):
                    await jobs.list(status=cast(ImportJobStatus, "unknown"))
                with pytest.raises(ValueError, match="actor"):
                    await templates.add(new_template(data), actor_id=cast(UUID, None))
                with pytest.raises(ValueError, match="UUID"):
                    ImportTemplateRepository(session, company_id=cast(UUID, None))
                with pytest.raises(ValueError, match="UUID"):
                    ImportJobRepository(session, company_id=cast(UUID, None))

    asyncio.run(scenario())


def test_foreign_key_failure_is_not_mislabeled_as_unique_conflict() -> None:
    async def scenario() -> None:
        async with import_fixture() as data, data.database.session() as session:
            missing_company = uuid4()
            with pytest.raises(IntegrityError):
                await ImportTemplateRepository(session, company_id=missing_company).add(
                    replace(new_template(data), company_id=missing_company), actor_id=data.actor_id
                )
            await session.rollback()

    asyncio.run(scenario())


def test_corrupt_template_fingerprint_fails_closed_on_read() -> None:
    async def scenario() -> None:
        async with import_fixture() as data:
            template, _, _ = await seed_import(data)
            async with data.database.session() as session, session.begin():
                await session.execute(
                    insert(ImportTemplateVersionModel).values(
                        id=uuid4(),
                        company_id=data.company_id,
                        template_id=template.id,
                        number=2,
                        field_definitions=[{"name": "sku", "required": True}],
                        allowed_modes=["ALL_OR_NOTHING"],
                        schema_fingerprint="b" * 64,
                        created_by=data.actor_id,
                    )
                )
                with pytest.raises(ValueError, match="fingerprint mismatch"):
                    await ImportTemplateRepository(session, company_id=data.company_id).get_version(
                        template.id, 2
                    )

    asyncio.run(scenario())


def test_job_source_metadata_cannot_be_changed_through_a_forged_save() -> None:
    async def scenario() -> None:
        async with import_fixture() as data:
            _, _, job = await seed_import(data)
            async with data.database.session() as session:
                with pytest.raises(OptimisticLockError):
                    await ImportJobRepository(session, company_id=data.company_id).save(
                        replace(job.cancel(), source_sha256="b" * 64), actor_id=data.actor_id
                    )
                await session.rollback()
                assert (
                    await ImportJobRepository(session, company_id=data.company_id).get(job.id)
                    == job
                )

    asyncio.run(scenario())
