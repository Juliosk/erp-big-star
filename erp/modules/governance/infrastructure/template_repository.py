"""Company-scoped templates and append-only layout versions; no implicit commit."""

from dataclasses import asdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.governance.domain import (
    ImportCommitMode,
    ImportField,
    ImportTemplate,
    ImportTemplateVersion,
)
from erp.modules.governance.domain.import_template import require_uuid
from erp.modules.governance.infrastructure.import_models import (
    ImportTemplateModel,
    ImportTemplateVersionModel,
)
from erp.modules.governance.infrastructure.repository_support import (
    flush_insert,
    require_page,
    require_write_scope,
)
from erp.platform.errors import ApplicationError


def _template(row: ImportTemplateModel) -> ImportTemplate:
    return ImportTemplate(row.id, row.company_id, row.code, row.name, row.target_domain)


class ImportTemplateRepository:
    def __init__(self, session: AsyncSession, *, company_id: UUID) -> None:
        require_uuid(company_id)
        self._session = session
        self._company_id = company_id

    async def add(self, template: ImportTemplate, *, actor_id: UUID) -> None:
        require_write_scope(template.company_id, self._company_id, actor_id)
        self._session.add(ImportTemplateModel(**asdict(template), created_by=actor_id))
        await flush_insert(self._session, conflict_code="IMPORT_TEMPLATE_CONFLICT")

    async def get(self, template_id: UUID) -> ImportTemplate | None:
        row = await self._session.scalar(
            select(ImportTemplateModel).where(
                ImportTemplateModel.company_id == self._company_id,
                ImportTemplateModel.id == template_id,
            )
        )
        return None if row is None else _template(row)

    async def list(self, *, limit: int = 50, offset: int = 0) -> tuple[ImportTemplate, ...]:
        require_page(limit, offset)
        rows = await self._session.scalars(
            select(ImportTemplateModel)
            .where(ImportTemplateModel.company_id == self._company_id)
            .order_by(ImportTemplateModel.code, ImportTemplateModel.id)
            .limit(limit)
            .offset(offset)
        )
        return tuple(_template(row) for row in rows)

    async def add_version(self, version: ImportTemplateVersion, *, actor_id: UUID) -> None:
        require_write_scope(version.company_id, self._company_id, actor_id)
        if await self.get(version.template_id) is None:
            raise ApplicationError(
                code="RESOURCE_NOT_FOUND", message="Import template not found.", status_code=404
            )
        self._session.add(
            ImportTemplateVersionModel(
                id=version.id,
                company_id=version.company_id,
                template_id=version.template_id,
                number=version.number,
                field_definitions=[asdict(field) for field in version.fields],
                allowed_modes=list(version.allowed_modes),
                schema_fingerprint=version.fingerprint,
                created_by=actor_id,
            )
        )
        await flush_insert(self._session, conflict_code="IMPORT_TEMPLATE_VERSION_CONFLICT")

    async def get_version(self, template_id: UUID, number: int) -> ImportTemplateVersion | None:
        row = await self._session.scalar(
            select(ImportTemplateVersionModel).where(
                ImportTemplateVersionModel.company_id == self._company_id,
                ImportTemplateVersionModel.template_id == template_id,
                ImportTemplateVersionModel.number == number,
            )
        )
        if row is None:
            return None
        version = ImportTemplateVersion(
            row.id,
            row.company_id,
            row.template_id,
            row.number,
            tuple(ImportField(field["name"], field["required"]) for field in row.field_definitions),
            tuple(ImportCommitMode(mode) for mode in row.allowed_modes),
        )
        if version.fingerprint != row.schema_fingerprint:
            raise ValueError("Persisted template fingerprint mismatch.")
        return version


__all__ = ["ImportTemplateRepository"]
