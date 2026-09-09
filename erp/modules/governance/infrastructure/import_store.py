"""M23 persistence orchestrator. Owner adapters are injected by the composition root."""

import asyncio
import hashlib
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.admin.contracts import SecurityContext
from erp.modules.governance.domain import (
    ImportCommitMode,
    ImportField,
    ImportJob,
    ImportTemplate,
    ImportTemplateVersion,
)
from erp.modules.governance.infrastructure.import_effects import record_import_effect
from erp.modules.governance.infrastructure.import_models import ImportJobModel, ImportTemplateModel
from erp.modules.governance.infrastructure.job_repository import ImportJobRepository, _job
from erp.modules.governance.infrastructure.processing_models import (
    ImportStagingRowModel,
    ImportValidationResultModel,
)
from erp.modules.governance.infrastructure.template_repository import ImportTemplateRepository
from erp.modules.governance.infrastructure.xlsx_parser import parse_xlsx
from erp.modules.governance.infrastructure.xlsx_template import template_xlsx
from erp.modules.product.contracts import CommandMetadata, ProductBulkDataAdapter
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import IdempotencyService
from erp.platform.storage import ObjectStorage

logger = logging.getLogger(__name__)
OwnerFactory = Callable[
    [AsyncSession, UUID, SecurityContext, CommandMetadata], ProductBulkDataAdapter
]
PRODUCT_FIELDS = ("code", "sku", "name", "product_type", "uom")


def missing() -> ApplicationError:
    return ApplicationError(
        code="RESOURCE_NOT_FOUND", message="Import resource not found.", status_code=404
    )


def job_view(job: ImportJob) -> dict[str, Any]:
    return {
        "id": str(job.id),
        "company_id": str(job.company_id),
        "template_id": str(job.template_id),
        "template_version": job.template_version,
        "filename": job.original_filename,
        "source_sha256": job.source_sha256,
        "status": job.status.value,
        "version": job.version,
        "commit_mode": job.commit_mode.value,
    }


class PostgresImportStore:
    def __init__(
        self,
        database: Database,
        storage: ObjectStorage | None,
        owner: OwnerFactory,
        *,
        ttl_seconds: int = 86400,
    ) -> None:
        self.database = database
        self.storage = storage
        self.owner = owner
        self.idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def _template(
        self,
        session: AsyncSession,
        company_id: UUID,
        template_id: UUID,
        version: int,
    ) -> ImportTemplateVersion:
        result = await ImportTemplateRepository(session, company_id=company_id).get_version(
            template_id, version
        )
        if result is None:
            raise missing()
        return result

    async def templates(self, company_id: UUID) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            templates = await ImportTemplateRepository(session, company_id=company_id).list()
            return [
                {"id": str(item.id), "name": item.name, "code": item.code} for item in templates
            ]

    async def provision(
        self, company_id: UUID, actor_id: UUID, metadata: CommandMetadata
    ) -> dict[str, Any]:
        # An explicit command installs the fixed product contract, never a GET side effect.
        async with self.database.session() as session, session.begin():
            repository = ImportTemplateRepository(session, company_id=company_id)
            existing = await session.scalar(
                select(ImportTemplateModel).where(
                    ImportTemplateModel.company_id == company_id,
                    ImportTemplateModel.code == "PRODUCTS_V1",
                )
            )
            if existing is not None:
                return {"id": str(existing.id), "version": 1}
            template = ImportTemplate.create(
                company_id=company_id, code="PRODUCTS_V1", name="Produtos por SKU"
            )
            await repository.add(template, actor_id=actor_id)
            version = ImportTemplateVersion(
                uuid4(),
                company_id,
                template.id,
                1,
                tuple(
                    ImportField(name, name not in {"code", "product_type"})
                    for name in PRODUCT_FIELDS
                ),
                (ImportCommitMode.ALL_OR_NOTHING,),
            )
            await repository.add_version(version, actor_id=actor_id)
            await AuditService().record(
                session,
                AuditEvent(
                    actor_user_id=actor_id,
                    company_id=company_id,
                    branch_id=None,
                    module="governance",
                    entity_type="import_template",
                    entity_id=template.id,
                    operation="ImportTemplateProvisioned",
                    request_id=metadata.request_id,
                    correlation_id=metadata.correlation_id,
                    source_ip=metadata.source_ip,
                    before_snapshot=None,
                    after_snapshot={
                        "code": template.code,
                        "version": 1,
                        "fingerprint": version.fingerprint,
                        "mode": "ALL_OR_NOTHING",
                    },
                ),
            )
            return {"id": str(template.id), "version": 1}

    async def download(self, company_id: UUID, template_id: UUID, version: int) -> bytes:
        async with self.database.session() as session:
            template = await self._template(session, company_id, template_id, version)
        return await asyncio.to_thread(template_xlsx, template)

    def require_storage(self) -> ObjectStorage:
        if self.storage is None:
            raise ApplicationError(
                code="IMPORT_STORAGE_UNAVAILABLE",
                message="Configure private import storage before uploading.",
                status_code=503,
            )
        return self.storage

    async def upload(
        self,
        context: SecurityContext,
        company_id: UUID,
        template_id: UUID,
        version: int,
        filename: str,
        content: bytes,
        key: str,
        metadata: CommandMetadata,
    ) -> dict[str, Any]:
        storage = self.require_storage()
        job = ImportJob.create(
            company_id=company_id,
            template_id=template_id,
            template_version=version,
            commit_mode=ImportCommitMode.ALL_OR_NOTHING,
            original_filename=filename,
            source_sha256=hashlib.sha256(content).hexdigest(),
            source_size_bytes=len(content),
        )
        uploaded = False
        try:
            async with self.database.session() as session, session.begin():
                template = await self._template(session, company_id, template_id, version)
                if tuple(field.name for field in template.fields) != PRODUCT_FIELDS:
                    raise ApplicationError(
                        code="IMPORT_TEMPLATE_UNSUPPORTED",
                        message="Use the operational product template.",
                        status_code=422,
                    )
                decision = await self.idempotency.begin(
                    session,
                    scope=f"governance:{company_id}:{context.principal.user_id}",
                    operation="upload",
                    key=key,
                    payload={
                        "template": str(template_id),
                        "version": version,
                        "filename": filename,
                        "sha256": job.source_sha256,
                    },
                )
                if decision.replayed:
                    assert decision.response_body is not None
                    return {**decision.response_body, "idempotency_replayed": True}
                rows = await asyncio.to_thread(parse_xlsx, content, template)
                # Unique random key: compensation can only remove this request's own object.
                await storage.put(job.storage_key, content)
                uploaded = True
                await ImportJobRepository(session, company_id=company_id).add(
                    job, actor_id=context.principal.user_id
                )
                session.add_all(
                    ImportStagingRowModel(
                        company_id=company_id,
                        job_id=job.id,
                        row_number=row.number,
                        values=row.values,
                        errors=list(row.errors),
                        created_by=context.principal.user_id,
                    )
                    for row in rows
                )
                await record_import_effect(
                    session,
                    job,
                    context.principal.user_id,
                    metadata,
                    "ImportJobCreated",
                    {"template_version": version, "row_count": len(rows)},
                )
                result = job_view(job)
                await self.idempotency.complete(
                    session, decision, response_status=201, response_body=result
                )
            return result
        except BaseException as error:
            if uploaded and isinstance(error, (ApplicationError, ValueError)):
                try:
                    await asyncio.shield(storage.delete(job.storage_key))
                except Exception:
                    logger.exception("import.orphan_cleanup_failed", extra={"job_id": str(job.id)})
            elif uploaded:
                # An interrupted DB commit may have succeeded. Preserve its source until reconciled.
                logger.warning("import.upload_outcome_uncertain", extra={"job_id": str(job.id)})
            raise

    async def history(self, company_id: UUID, page: int) -> list[dict[str, Any]]:
        async with self.database.session() as session:
            jobs = await ImportJobRepository(session, company_id=company_id).list(
                limit=20, offset=(page - 1) * 20
            )
            return [job_view(job) for job in jobs]

    async def get(self, company_id: UUID, job_id: UUID) -> dict[str, Any]:
        async with self.database.session() as session:
            job = await ImportJobRepository(session, company_id=company_id).get(job_id)
            if job is None:
                raise missing()
            return await self.view(session, job)

    async def view(self, session: AsyncSession, job: ImportJob) -> dict[str, Any]:
        result = job_view(job)
        validation = await session.get(ImportValidationResultModel, (job.company_id, job.id))
        if validation is not None:
            result.update(
                fingerprint=validation.fingerprint,
                rows=validation.plans,
                error_count=sum(bool(row["errors"]) for row in validation.plans),
            )
        return result

    async def command(
        self,
        context: SecurityContext,
        company_id: UUID,
        job_id: UUID,
        action: str,
        version: int,
        fingerprint: str,
        key: str,
        metadata: CommandMetadata,
    ) -> dict[str, Any]:
        # Separate collaborator keeps staging/storage concerns out of lifecycle processing.
        from erp.modules.governance.infrastructure.import_processor import ImportProcessor

        async with self.database.session() as session, session.begin():
            model = await session.scalar(
                select(ImportJobModel)
                .where(ImportJobModel.company_id == company_id, ImportJobModel.id == job_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if model is None:
                raise missing()
            processor = ImportProcessor(self, session, context, metadata)
            return await processor.execute(model, _job(model), action, version, fingerprint, key)


__all__ = ["OwnerFactory", "PostgresImportStore", "job_view"]
