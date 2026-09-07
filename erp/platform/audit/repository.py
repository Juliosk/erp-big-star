"""Write-only persistence adapter for append-only audit events."""

from sqlalchemy.ext.asyncio import AsyncSession

from erp.platform.audit.models import AuditEventModel


class AuditRepository:
    """Expose insertion only so application code cannot mutate audit history."""

    async def add(self, session: AsyncSession, model: AuditEventModel) -> None:
        """Stage one audit event in the caller-owned transaction."""
        session.add(model)
        await session.flush()


__all__ = ["AuditRepository"]
