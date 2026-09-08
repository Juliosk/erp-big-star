"""Scoped import job persistence with immutable source identity and atomic CAS."""

from dataclasses import asdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.governance.domain import ImportCommitMode, ImportJob, ImportJobStatus
from erp.modules.governance.domain.import_template import require_uuid
from erp.modules.governance.infrastructure.import_models import ImportJobModel
from erp.modules.governance.infrastructure.repository_support import (
    flush_insert,
    require_page,
    require_write_scope,
)
from erp.modules.governance.infrastructure.template_repository import ImportTemplateRepository
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError


def _job(row: ImportJobModel) -> ImportJob:
    return ImportJob(
        id=row.id,
        company_id=row.company_id,
        template_id=row.template_id,
        template_version=row.template_version,
        commit_mode=ImportCommitMode(row.commit_mode),
        original_filename=row.original_filename,
        source_sha256=row.source_sha256,
        source_size_bytes=row.source_size_bytes,
        storage_key=row.storage_key,
        status=ImportJobStatus(row.status),
        version=row.version,
    )


class ImportJobRepository:
    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        require_uuid(company_id)
        self._session = session
        self._company_id = company_id

    async def add(self, job: ImportJob, *, actor_id: UUID) -> None:
        require_write_scope(job.company_id, self._company_id, actor_id)
        if job.status is not ImportJobStatus.UPLOADED or job.version != 1:
            raise ValueError("A new job must be uploaded at version one.")
        version = await ImportTemplateRepository(
            self._session, company_id=self._company_id
        ).get_version(job.template_id, job.template_version)
        if version is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND",
                message="Import template version not found.",
                status_code=404,
            )
        if job.commit_mode not in version.allowed_modes:
            raise ApplicationError(
                code="IMPORT_MODE_NOT_ALLOWED",
                message="Commit mode not enabled for this template version.",
                status_code=422,
            )
        self._session.add(ImportJobModel(**asdict(job), created_by=actor_id, updated_by=actor_id))
        await flush_insert(self._session, conflict_code="IMPORT_JOB_CONFLICT")

    async def get(self, job_id: UUID) -> ImportJob | None:
        row = await self._session.scalar(
            select(ImportJobModel)
            .where(ImportJobModel.company_id == self._company_id, ImportJobModel.id == job_id)
            .execution_options(populate_existing=True)
        )
        return None if row is None else _job(row)

    async def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: ImportJobStatus | None = None,
    ) -> tuple[ImportJob, ...]:
        require_page(limit, offset)
        if status is not None and not isinstance(status, ImportJobStatus):
            raise ValueError("status must be an import job state.")
        statement = select(ImportJobModel).where(ImportJobModel.company_id == self._company_id)
        if status is not None:
            statement = statement.where(ImportJobModel.status == status)
        rows = await self._session.scalars(
            statement.order_by(ImportJobModel.created_at, ImportJobModel.id)
            .limit(limit)
            .offset(offset)
            .execution_options(populate_existing=True)
        )
        return tuple(_job(row) for row in rows)

    async def save(self, job: ImportJob, *, actor_id: UUID) -> ImportJob:
        require_write_scope(job.company_id, self._company_id, actor_id)
        if job.status is not ImportJobStatus.CANCELLED or job.version < 2:
            raise ValueError("save requires a cancelled job with an incremented version.")
        expected = job.version - 1
        row = await self._session.scalar(
            update(ImportJobModel)
            .where(
                ImportJobModel.company_id == self._company_id,
                ImportJobModel.id == job.id,
                ImportJobModel.version == expected,
                ImportJobModel.status == ImportJobStatus.UPLOADED,
                ImportJobModel.template_id == job.template_id,
                ImportJobModel.template_version == job.template_version,
                ImportJobModel.commit_mode == job.commit_mode,
                ImportJobModel.original_filename == job.original_filename,
                ImportJobModel.source_sha256 == job.source_sha256,
                ImportJobModel.source_size_bytes == job.source_size_bytes,
                ImportJobModel.storage_key == job.storage_key,
            )
            .values(
                status=job.status,
                version=job.version,
                updated_by=actor_id,
                updated_at=datetime.now(UTC),
            )
            .returning(ImportJobModel)
            .execution_options(synchronize_session=False, populate_existing=True)
        )
        if row is None:
            raise OptimisticLockError(expected_version=expected)
        return _job(row)


__all__ = ["ImportJobRepository"]
