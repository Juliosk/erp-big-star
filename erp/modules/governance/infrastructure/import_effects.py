"""M23 effects recorded in the caller's transaction."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.governance.domain import ImportJob
from erp.modules.product.contracts import CommandMetadata
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.messaging import MessageEnvelope, MessageKind
from erp.platform.outbox import OutboxService


async def record_import_effect(
    session: AsyncSession,
    job: ImportJob,
    actor_id: UUID,
    metadata: CommandMetadata,
    event: str,
    details: dict[str, object],
) -> None:
    await AuditService().record(
        session,
        AuditEvent(
            actor_user_id=actor_id,
            company_id=job.company_id,
            branch_id=None,
            module="governance",
            entity_type="import_job",
            entity_id=job.id,
            operation=event,
            request_id=metadata.request_id,
            correlation_id=metadata.correlation_id,
            source_ip=metadata.source_ip,
            before_snapshot=None,
            after_snapshot={"status": job.status, "version": job.version, **details},
        ),
    )
    await OutboxService().enqueue(
        session,
        MessageEnvelope.new(
            message_kind=MessageKind.DOMAIN_EVENT,
            message_type=event,
            event_version=1,
            producer_module="governance",
            producer_domain="data",
            aggregate_type="import_job",
            aggregate_id=job.id,
            aggregate_version=job.version,
            company_id=job.company_id,
            branch_id=None,
            correlation_id=metadata.correlation_id,
            request_id=metadata.request_id,
            causation_id=None,
            payload={"import_job_id": str(job.id), **details},
        ),
    )


__all__ = ["record_import_effect"]
