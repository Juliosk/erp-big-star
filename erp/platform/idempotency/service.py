"""Application-facing idempotency semantics."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.platform.errors import ApplicationError
from erp.platform.idempotency.fingerprint import payload_fingerprint
from erp.platform.idempotency.models import IdempotencyStatus
from erp.platform.idempotency.repository import IdempotencyRepository


@dataclass(frozen=True, slots=True)
class IdempotencyDecision:
    """Either ownership of a new command or a completed response replay."""

    record_id: UUID
    replayed: bool
    response_status: int | None = None
    response_body: dict[str, Any] | None = None


class IdempotencyService:
    """Protect critical commands from accidental duplicate effects."""

    def __init__(
        self,
        *,
        ttl_seconds: int,
        repository: IdempotencyRepository | None = None,
    ) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._repository = repository or IdempotencyRepository()

    async def begin(
        self,
        session: AsyncSession,
        *,
        scope: str,
        operation: str,
        key: str,
        payload: dict[str, Any],
    ) -> IdempotencyDecision:
        """Claim the command or return/reject an existing scoped key."""
        normalized_key = key.strip()
        if not normalized_key or len(normalized_key) > 255:
            raise ApplicationError(
                code="INVALID_IDEMPOTENCY_KEY",
                message="Idempotency-Key must contain between 1 and 255 characters.",
                status_code=400,
            )
        request_hash = payload_fingerprint(payload)
        now = datetime.now(UTC)
        expires_at = now + self._ttl
        inserted = await self._repository.insert_processing(
            session,
            scope=scope,
            operation=operation,
            key=normalized_key,
            request_hash=request_hash,
            expires_at=expires_at,
        )
        if inserted is not None:
            return IdempotencyDecision(record_id=inserted, replayed=False)

        existing = await self._repository.get_locked(
            session,
            scope=scope,
            operation=operation,
            key=normalized_key,
        )
        if existing.expires_at <= now:
            existing.request_hash = request_hash
            existing.status = IdempotencyStatus.PROCESSING
            existing.response_status = None
            existing.response_body = None
            existing.completed_at = None
            existing.created_at = now
            existing.expires_at = expires_at
            await session.flush()
            return IdempotencyDecision(record_id=existing.id, replayed=False)
        if existing.request_hash != request_hash:
            raise ApplicationError(
                code="IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD",
                message="Idempotency-Key was already used with a different payload.",
                status_code=409,
            )
        if existing.status != IdempotencyStatus.COMPLETED:
            raise ApplicationError(
                code="IDEMPOTENCY_REQUEST_IN_PROGRESS",
                message="A request with this Idempotency-Key is still processing.",
                status_code=409,
                headers={"Retry-After": "1"},
            )
        return IdempotencyDecision(
            record_id=existing.id,
            replayed=True,
            response_status=existing.response_status,
            response_body=existing.response_body,
        )

    async def complete(
        self,
        session: AsyncSession,
        decision: IdempotencyDecision,
        *,
        response_status: int,
        response_body: dict[str, object],
    ) -> None:
        """Persist the reusable response in the caller's successful transaction."""
        if decision.replayed:
            raise ValueError("A replayed idempotency decision cannot be completed again.")
        await self._repository.complete(
            session,
            record_id=decision.record_id,
            response_status=response_status,
            response_body=response_body,
            completed_at=datetime.now(UTC),
        )


__all__ = ["IdempotencyDecision", "IdempotencyService"]
