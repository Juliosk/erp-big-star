"""Transactional PostgreSQL adapter for inventory adjustment commands."""

from decimal import Decimal
from uuid import UUID, uuid4

from erp.modules.inventory.application.adjustments import (
    InventoryAdjustmentStore,
    build_adjustment_entry,
)
from erp.modules.inventory.application.commands import (
    CreateInventoryAdjustment,
    InventoryAdjustmentLine,
    InventoryAdjustmentResult,
    InventoryAdjustmentType,
)
from erp.modules.inventory.domain import InventoryPosting, InventoryState
from erp.modules.inventory.infrastructure.adjustment_effects import InventoryAdjustmentEffects
from erp.modules.inventory.infrastructure.balance_repository import InventoryBalanceRepository
from erp.modules.inventory.infrastructure.ledger_repository import InventoryLedgerRepository
from erp.platform.database import Database
from erp.platform.idempotency import IdempotencyService


class PostgresInventoryAdjustments(InventoryAdjustmentStore):
    """Apply adjustments, ledger, balances, audit and outbox in one transaction."""

    def __init__(self, database: Database, *, ttl_seconds: int) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def adjust(
        self, command: CreateInventoryAdjustment, actor_id: UUID
    ) -> InventoryAdjustmentResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"inventory:{command.company_id}:{actor_id}",
                operation="inventory.adjust",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                if decision.response_body is None:
                    raise RuntimeError("Stored inventory adjustment replay has no response body.")
                return InventoryAdjustmentResult.replay(decision.response_body)
            repository = InventoryBalanceRepository(session, company_id=command.company_id)
            current_quantities = await _current_quantities(repository, command)
            entry = build_adjustment_entry(
                command, actor_id=actor_id, current_quantities=current_quantities
            )
            await InventoryLedgerRepository(session, company_id=command.company_id).append(entry)
            balances = tuple([await repository.apply(posting) for posting in entry.postings])
            result = await InventoryAdjustmentEffects().record(
                session,
                entry,
                balances,
                actor_id=actor_id,
                metadata=command.metadata,
                reason=command.reason.strip(),
            )
            await self._idempotency.complete(
                session, decision, response_status=201, response_body=result.to_dict()
            )
            return result


async def _current_quantities(
    repository: InventoryBalanceRepository, command: CreateInventoryAdjustment
) -> list[Decimal] | None:
    if command.adjustment_type is not InventoryAdjustmentType.BALANCE:
        return None
    quantities: list[Decimal] = []
    for line in command.lines:
        balance = await repository.get_for_posting(_dimension_probe(command.company_id, line))
        quantities.append(Decimal("0") if balance is None else balance.quantity.value)
    return quantities


def _dimension_probe(company_id: UUID, line: InventoryAdjustmentLine) -> InventoryPosting:
    return InventoryPosting.create(
        company_id=company_id,
        transaction_id=uuid4(),
        sequence=1,
        product_id=line.product_id,
        warehouse_id=line.warehouse_id,
        location_id=line.location_id,
        lot_id=line.lot_id,
        pool_id=line.pool_id,
        state=InventoryState(line.state),
        quantity_delta=Decimal("1"),
    )


__all__ = ["PostgresInventoryAdjustments"]
