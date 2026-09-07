"""Application-facing audit service."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.platform.audit.masking import JsonValue, mask_sensitive_values
from erp.platform.audit.models import AuditEventModel
from erp.platform.audit.repository import AuditRepository


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Technology-neutral command for one durable audit entry."""

    actor_user_id: UUID | None
    company_id: UUID | None
    branch_id: UUID | None
    module: str
    entity_type: str
    entity_id: UUID
    operation: str
    request_id: UUID
    correlation_id: UUID
    before_snapshot: dict[str, object] | None = None
    after_snapshot: dict[str, object] | None = None
    reason_code: str | None = None
    occurred_at: datetime | None = None
    source_ip: str | None = None
    device_metadata: dict[str, object] | None = None


class AuditService:
    """Mask and stage audit data inside an existing business transaction."""

    def __init__(self, repository: AuditRepository | None = None) -> None:
        self._repository = repository or AuditRepository()

    async def record(self, session: AsyncSession, event: AuditEvent) -> UUID:
        """Persist a masked event without committing the caller-owned transaction."""
        before = _masked_mapping(event.before_snapshot)
        after = _masked_mapping(event.after_snapshot)
        device = _masked_mapping(event.device_metadata)
        model = AuditEventModel(
            actor_user_id=event.actor_user_id,
            company_id=event.company_id,
            branch_id=event.branch_id,
            module=event.module,
            entity_type=event.entity_type,
            entity_id=event.entity_id,
            operation=event.operation,
            before_snapshot=before,
            after_snapshot=after,
            reason_code=event.reason_code,
            request_id=event.request_id,
            correlation_id=event.correlation_id,
            source_ip=event.source_ip,
            device_metadata=device,
        )
        if event.occurred_at is not None:
            model.occurred_at = event.occurred_at
        await self._repository.add(session, model)
        return model.id


def _masked_mapping(value: dict[str, object] | None) -> dict[str, JsonValue] | None:
    if value is None:
        return None
    masked = mask_sensitive_values(value)
    if not isinstance(masked, dict):
        raise TypeError("Audit snapshots must be JSON objects.")
    return masked


__all__ = ["AuditEvent", "AuditService"]
