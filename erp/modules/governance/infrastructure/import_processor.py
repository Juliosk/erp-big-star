"""Locked job commands: snapshot validation, explicit confirmation and atomic owner commit."""

import asyncio
import hashlib
from dataclasses import asdict
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.admin.contracts import SecurityContext
from erp.modules.governance.domain import ImportJob, ImportJobStatus
from erp.modules.governance.domain.workflow import advance
from erp.modules.governance.infrastructure.import_effects import record_import_effect
from erp.modules.governance.infrastructure.import_models import ImportJobModel
from erp.modules.governance.infrastructure.processing_models import (
    ImportCommitBatchModel,
    ImportStagingRowModel,
    ImportValidationResultModel,
)
from erp.modules.governance.infrastructure.xlsx_parser import parse_xlsx
from erp.modules.product.contracts import CommandMetadata, ProductImportPlan, ProductImportRow
from erp.platform.concurrency import OptimisticLockError
from erp.platform.errors import ApplicationError
from erp.platform.idempotency.fingerprint import payload_fingerprint

if TYPE_CHECKING:
    from erp.modules.governance.infrastructure.import_store import PostgresImportStore


def conflict(message: str) -> ApplicationError:
    return ApplicationError(code="IMPORT_INVALID_STATE", message=message, status_code=409)


def plans_from_json(rows: list[dict[str, Any]]) -> tuple[ProductImportPlan, ...]:
    return tuple(
        ProductImportPlan(
            row["number"],
            row["action"],
            row["current"],
            row["proposed"],
            tuple(row["differences"]),
            tuple(row["errors"]),
        )
        for row in rows
    )


class ImportProcessor:
    def __init__(
        self,
        store: PostgresImportStore,
        session: AsyncSession,
        context: SecurityContext,
        metadata: CommandMetadata,
    ) -> None:
        self.store = store
        self.session = session
        self.context = context
        self.metadata = metadata

    async def _rows(self, job: ImportJob) -> tuple[ProductImportRow, ...]:
        content = await self.store.require_storage().get(job.storage_key)
        if (
            len(content) != job.source_size_bytes
            or hashlib.sha256(content).hexdigest() != job.source_sha256
        ):
            raise conflict("Source checksum differs from the uploaded object.")
        template = await self.store._template(
            self.session, job.company_id, job.template_id, job.template_version
        )
        parsed = await asyncio.to_thread(parse_xlsx, content, template)
        staging = tuple(
            await self.session.scalars(
                select(ImportStagingRowModel)
                .where(
                    ImportStagingRowModel.company_id == job.company_id,
                    ImportStagingRowModel.job_id == job.id,
                )
                .order_by(ImportStagingRowModel.row_number)
            )
        )
        rows = tuple(ProductImportRow(row.number, row.values, row.errors) for row in parsed)
        if rows != tuple(
            ProductImportRow(row.row_number, row.values, tuple(row.errors)) for row in staging
        ):
            raise conflict("Staging differs from the immutable source.")
        return rows

    async def execute(
        self,
        model: ImportJobModel,
        job: ImportJob,
        action: str,
        version: int,
        fingerprint: str,
        key: str,
    ) -> dict[str, Any]:
        actor = self.context.principal.user_id
        owner = self.store.owner(self.session, job.company_id, self.context, self.metadata)
        validation = await self.session.get(ImportValidationResultModel, (job.company_id, job.id))
        decision = None
        if action == "commit":
            if validation is None or any(row["errors"] for row in validation.plans):
                raise conflict("A valid confirmed preview is required.")
            await owner.authorize(plans_from_json(validation.plans))
            decision = await self.store.idempotency.begin(
                self.session,
                scope=f"governance:{job.company_id}:{actor}",
                operation="commit",
                key=key,
                payload={"job_id": str(job.id), "version": version, "fingerprint": fingerprint},
            )
            if decision.replayed:
                assert decision.response_body is not None
                return {**decision.response_body, "idempotency_replayed": True}
        if version != job.version:
            raise OptimisticLockError(expected_version=version)
        event = "ImportJobCancelled"
        details: dict[str, object] = {}
        if action == "validate":
            plans = await owner.validate(await self._rows(job))
            errors = sum(bool(plan.errors) for plan in plans)
            changed = advance(
                job, ImportJobStatus.REJECTED if errors else ImportJobStatus.VALIDATED
            )
            snapshot = [asdict(plan) for plan in plans]
            digest = payload_fingerprint(
                {
                    "source": job.source_sha256,
                    "template_id": str(job.template_id),
                    "template_version": job.template_version,
                    "company_id": str(job.company_id),
                    "rows": snapshot,
                }
            )
            await self.session.execute(
                delete(ImportValidationResultModel).where(
                    ImportValidationResultModel.company_id == job.company_id,
                    ImportValidationResultModel.job_id == job.id,
                )
            )
            self.session.add(
                ImportValidationResultModel(
                    company_id=job.company_id,
                    job_id=job.id,
                    fingerprint=digest,
                    plans=snapshot,
                    created_by=actor,
                )
            )
            event = "ImportValidationCompleted"
            details = {"valid_count": len(plans) - errors, "error_count": errors}
        elif action == "preview":
            if validation is None:
                raise conflict("Validate the uploaded rows first.")
            if job.status in {ImportJobStatus.REJECTED, ImportJobStatus.PREVIEWED}:
                return await self.store.view(self.session, job)
            changed = advance(job, ImportJobStatus.PREVIEWED)
            event = "ImportPreviewReady"
            details = {
                "fingerprint": validation.fingerprint,
                "change_summary": {"rows": len(validation.plans)},
            }
        elif action in {"confirm", "commit"}:
            if (
                validation is None
                or fingerprint != validation.fingerprint
                or any(row["errors"] for row in validation.plans)
            ):
                raise conflict("A valid matching preview fingerprint is required.")
            plans = plans_from_json(validation.plans)
            fresh = await owner.validate(await self._rows(job))
            if fresh != plans:
                raise ApplicationError(
                    code="IMPORT_PREVIEW_STALE",
                    message="Product data changed. Validate again.",
                    status_code=409,
                )
            target = ImportJobStatus.CONFIRMED if action == "confirm" else ImportJobStatus.COMMITTED
            changed = advance(job, target)
            event = "ImportJobConfirmed" if action == "confirm" else "ImportCommitted"
            details = {"fingerprint": fingerprint}
            if action == "commit":
                count = await owner.commit(plans)
                self.session.add(
                    ImportCommitBatchModel(
                        company_id=job.company_id,
                        job_id=job.id,
                        affected_count=count,
                        fingerprint=fingerprint,
                        created_by=actor,
                    )
                )
                details.update(count=count, affected_domain="product")
        elif action == "cancel":
            changed = advance(job, ImportJobStatus.CANCELLED)
        else:
            raise conflict("Unsupported import command.")
        model.status, model.version = changed.status.value, changed.version
        model.updated_by, model.updated_at = actor, datetime.now(UTC)
        await self.session.flush()
        await record_import_effect(self.session, changed, actor, self.metadata, event, details)
        result = await self.store.view(self.session, changed)
        result.update(details)
        if decision is not None:
            await self.store.idempotency.complete(
                self.session, decision, response_status=200, response_body=result
            )
        return result


__all__ = ["ImportProcessor"]
