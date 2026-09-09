"""M23 fixtures reuse only the test harness for isolated M1 companies."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import delete

from erp.modules.governance.domain import (
    ImportCommitMode,
    ImportField,
    ImportJob,
    ImportTemplate,
    ImportTemplateVersion,
)
from erp.modules.governance.infrastructure import (
    ImportJobModel,
    ImportTemplateModel,
    ImportTemplateVersionModel,
)
from erp.modules.governance.infrastructure.processing_models import (
    ImportCommitBatchModel,
    ImportStagingRowModel,
    ImportValidationResultModel,
)
from tests.integration.test_product_persistence import Fixture, fixture


@asynccontextmanager
async def import_fixture() -> AsyncIterator[Fixture]:
    async with fixture() as data:
        try:
            yield data
        finally:
            async with data.database.session() as session, session.begin():
                for model in (
                    ImportCommitBatchModel,
                    ImportValidationResultModel,
                    ImportStagingRowModel,
                    ImportJobModel,
                    ImportTemplateVersionModel,
                    ImportTemplateModel,
                ):
                    await session.execute(
                        delete(model).where(
                            model.company_id.in_((data.company_id, data.other_company_id))
                        )
                    )


def new_template(data: Fixture, *, other: bool = False) -> ImportTemplate:
    return ImportTemplate.create(
        company_id=data.other_company_id if other else data.company_id,
        code="PRODUCTS",
        name="Product import fixture",
    )


def new_version(template: ImportTemplate, *, number: int = 1) -> ImportTemplateVersion:
    return ImportTemplateVersion(
        uuid4(),
        template.company_id,
        template.id,
        number,
        (ImportField("code", True), ImportField("sku", True)),
        (ImportCommitMode.ALL_OR_NOTHING,),
    )


def new_job(template: ImportTemplate) -> ImportJob:
    return ImportJob.create(
        company_id=template.company_id,
        template_id=template.id,
        template_version=1,
        commit_mode=ImportCommitMode.ALL_OR_NOTHING,
        original_filename="Fixture.xlsx",
        source_sha256="a" * 64,
        source_size_bytes=100,
    )


async def seed_import(data: Fixture) -> tuple[ImportTemplate, ImportTemplateVersion, ImportJob]:
    template = new_template(data)
    version = new_version(template)
    job = new_job(template)
    async with data.database.session() as session, session.begin():
        session.add(ImportTemplateModel(**asdict(template), created_by=data.actor_id))
        await session.flush()
        session.add(
            ImportTemplateVersionModel(
                id=version.id,
                company_id=version.company_id,
                template_id=version.template_id,
                number=version.number,
                field_definitions=[asdict(item) for item in version.fields],
                allowed_modes=list(version.allowed_modes),
                schema_fingerprint=version.fingerprint,
                created_by=data.actor_id,
            )
        )
        await session.flush()
        session.add(
            ImportJobModel(**asdict(job), created_by=data.actor_id, updated_by=data.actor_id)
        )
        await session.flush()
    return template, version, job
