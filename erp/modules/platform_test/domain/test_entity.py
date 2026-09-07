"""Technology-free temporary entity used by the Sprint 1 acceptance flow."""

from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import UUID, uuid4


class TestEntityStatus(StrEnum):
    """Minimal states needed to prove produced and consumed transitions."""

    CREATED = "CREATED"
    CONSUMED = "CONSUMED"


@dataclass(frozen=True, slots=True)
class TestEntity:
    """Versioned aggregate used only for platform integration validation."""

    id: UUID
    name: str
    status: TestEntityStatus
    version: int

    @classmethod
    def create(cls, name: str) -> TestEntity:
        """Create the first valid aggregate version."""
        normalized = name.strip()
        if not normalized:
            raise ValueError("Test entity name must not be blank.")
        return cls(
            id=uuid4(),
            name=normalized,
            status=TestEntityStatus.CREATED,
            version=1,
        )

    def mark_consumed(self) -> TestEntity:
        """Return the next domain state; persistence verifies the expected version."""
        if self.status is not TestEntityStatus.CREATED:
            return self
        return replace(self, status=TestEntityStatus.CONSUMED, version=self.version + 1)


__all__ = ["TestEntity", "TestEntityStatus"]
