"""Structural contracts for database-backed application entry points."""

from typing import Protocol


class DatabaseHealthProbe(Protocol):
    """Minimal database capability required by readiness checks."""

    async def ping(self) -> None:
        """Raise when the database cannot answer a minimal query."""
        ...


class ManagedDatabase(DatabaseHealthProbe, Protocol):
    """Database capability whose resources follow the application lifecycle."""

    async def dispose(self) -> None:
        """Release all database resources."""
        ...


__all__ = ["DatabaseHealthProbe", "ManagedDatabase"]
