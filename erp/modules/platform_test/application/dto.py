"""Technology-neutral inputs and outputs for the acceptance workflow."""

from dataclasses import dataclass
from typing import Any, Self
from uuid import UUID

from erp.modules.platform_test.domain import TestEntityStatus


@dataclass(frozen=True, slots=True)
class CreateTestEntityCommand:
    """Input accepted from the HTTP boundary after validation."""

    name: str
    idempotency_key: str
    request_id: UUID
    correlation_id: UUID
    source_ip: str | None


@dataclass(frozen=True, slots=True)
class TestEntityCreation:
    """Committed creation state or a previously completed response."""

    entity_id: UUID | None
    event_id: UUID | None
    entity_version: int | None
    audit_event_id: UUID | None
    idempotency_record_id: UUID
    replayed_response: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class TestEntityProcessing:
    """Committed consumer result."""

    entity_id: UUID
    name: str
    status: TestEntityStatus
    version: int
    audit_event_id: UUID
    duplicate: bool


@dataclass(frozen=True, slots=True)
class CreateTestEntityResult:
    """Stable successful response from the full golden flow."""

    id: UUID
    name: str
    status: TestEntityStatus
    version: int
    event_id: UUID
    audit_event_ids: tuple[UUID, ...]
    idempotency_replayed: bool

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-ready shape persisted for later idempotency replay."""
        return {
            "id": str(self.id),
            "name": self.name,
            "status": self.status,
            "version": self.version,
            "event_id": str(self.event_id),
            "audit_event_ids": [str(item) for item in self.audit_event_ids],
            "idempotency_replayed": False,
        }

    @classmethod
    def from_replay(cls, payload: dict[str, Any]) -> Self:
        """Restore the original public result and mark this delivery as a replay."""
        audit_ids = payload.get("audit_event_ids")
        if not isinstance(audit_ids, list):
            raise ValueError("Stored idempotency response has invalid audit identifiers.")
        return cls(
            id=UUID(str(payload["id"])),
            name=str(payload["name"]),
            status=TestEntityStatus(str(payload["status"])),
            version=int(payload["version"]),
            event_id=UUID(str(payload["event_id"])),
            audit_event_ids=tuple(UUID(str(item)) for item in audit_ids),
            idempotency_replayed=True,
        )


__all__ = [
    "CreateTestEntityCommand",
    "CreateTestEntityResult",
    "TestEntityCreation",
    "TestEntityProcessing",
]
