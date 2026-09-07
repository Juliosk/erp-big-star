"""Corporate message envelope independent from any transport."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class MessageKind(StrEnum):
    """Supported semantic message categories."""

    DOMAIN_EVENT = "DOMAIN_EVENT"
    ASYNC_REQUEST = "ASYNC_REQUEST"
    NOTIFICATION_EVENT = "NOTIFICATION_EVENT"


class MessageEnvelope(BaseModel):
    """Mandatory, versioned metadata carried by every corporate message."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: UUID
    message_kind: MessageKind
    message_type: str = Field(pattern=r"^[A-Z][A-Za-z0-9]+$")
    event_version: int = Field(ge=1)
    producer_module: str = Field(min_length=1, max_length=32)
    producer_domain: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    aggregate_type: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    aggregate_id: UUID
    aggregate_version: int | None = Field(default=None, ge=1)
    company_id: UUID | None = None
    branch_id: UUID | None = None
    occurred_at: datetime
    correlation_id: UUID
    causation_id: UUID | None = None
    request_id: UUID
    payload: dict[str, Any]

    @classmethod
    def new(
        cls,
        *,
        message_kind: MessageKind,
        message_type: str,
        event_version: int,
        producer_module: str,
        producer_domain: str,
        aggregate_type: str,
        aggregate_id: UUID,
        aggregate_version: int | None,
        company_id: UUID | None,
        branch_id: UUID | None,
        correlation_id: UUID,
        causation_id: UUID | None,
        request_id: UUID,
        payload: dict[str, Any],
    ) -> Self:
        """Create a new UTC-stamped envelope with a globally unique identity."""
        return cls(
            message_id=uuid4(),
            message_kind=message_kind,
            message_type=message_type,
            event_version=event_version,
            producer_module=producer_module,
            producer_domain=producer_domain,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_version=aggregate_version,
            company_id=company_id,
            branch_id=branch_id,
            occurred_at=datetime.now(UTC),
            correlation_id=correlation_id,
            causation_id=causation_id,
            request_id=request_id,
            payload=payload,
        )


__all__ = ["MessageEnvelope", "MessageKind"]
