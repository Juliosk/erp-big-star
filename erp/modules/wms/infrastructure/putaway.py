"""PostgreSQL transaction boundary for WMS putaway and M5 stock transfer."""

from decimal import Decimal
from uuid import UUID

from erp.modules.inventory.application.ledger import InventoryLedgerEntry
from erp.modules.inventory.contracts import InventoryBalanceReference
from erp.modules.inventory.domain import (
    InventoryBalance,
    InventoryPosting,
    InventoryState,
    InventoryTransaction,
    InventoryTransactionType,
)
from erp.modules.inventory.infrastructure.balance_repository import (
    InventoryBalanceRepository,
)
from erp.modules.inventory.infrastructure.ledger_repository import (
    InventoryLedgerRepository,
)
from erp.modules.wms.application.putaway import (
    ExecutePutaway,
    WmsPutawayResult,
    WmsPutawayStore,
)
from erp.modules.wms.domain import PutawayLoad, PutawayPolicy, StockCondition
from erp.modules.wms.infrastructure.location_repository import WMSLocationRepository
from erp.modules.wms.infrastructure.putaway_effects import WmsPutawayEffects
from erp.platform.concurrency import OptimisticLockError
from erp.platform.database import Database
from erp.platform.errors import ApplicationError
from erp.platform.idempotency import IdempotencyService


class PostgresWmsPutawayStore(WmsPutawayStore):
    """Move M5 stock and update WMS occupancy in one caller-visible command."""

    def __init__(self, database: Database, *, ttl_seconds: int = 86_400) -> None:
        self._database = database
        self._idempotency = IdempotencyService(ttl_seconds=ttl_seconds)

    async def putaway(
        self, command: ExecutePutaway, actor_id: UUID
    ) -> WmsPutawayResult:
        async with self._database.session() as session, session.begin():
            decision = await self._idempotency.begin(
                session,
                scope=f"wms:{command.company_id}:{actor_id}",
                operation="wms.putaway",
                key=command.idempotency_key,
                payload=command.payload(),
            )
            if decision.replayed:
                if decision.response_body is None:
                    raise RuntimeError("Stored WMS putaway replay has no response body.")
                return WmsPutawayResult.replay(decision.response_body)

            bins = WMSLocationRepository(session, company_id=command.company_id)
            target = await bins.get_for_update(command.target_bin_id)
            if target is None or target.address.warehouse_id != command.warehouse_id:
                raise ApplicationError(
                    code="RESOURCE_NOT_FOUND",
                    message="Target WMS bin not found.",
                    status_code=404,
                )
            if target.version != command.expected_bin_version:
                raise OptimisticLockError(
                    expected_version=command.expected_bin_version
                )
            placed = target.plan_putaway(
                PutawayLoad(
                    company_id=command.company_id,
                    warehouse_id=command.warehouse_id,
                    dimensions=command.dimensions,
                    unit_weight=command.unit_weight,
                    units=command.units,
                    condition=command.condition,
                ),
                PutawayPolicy(
                    company_id=command.company_id,
                    warehouse_id=command.warehouse_id,
                    allowed_zones=command.allowed_zones,
                ),
            )
            entry = _ledger_entry(command, actor_id=actor_id)
            await InventoryLedgerRepository(
                session, company_id=command.company_id
            ).append(entry)
            balances = InventoryBalanceRepository(
                session, company_id=command.company_id
            )
            source = await balances.apply(entry.postings[0])
            destination = await balances.apply(entry.postings[1])
            await bins.save(
                placed,
                actor_id=actor_id,
                expected_version=command.expected_bin_version,
            )
            source_reference = _balance_reference(source)
            destination_reference = _balance_reference(destination)
            event_id, audit_id = await WmsPutawayEffects().record(
                session,
                command,
                entry,
                target,
                placed,
                source_reference,
                destination_reference,
                actor_id=actor_id,
            )
            result = WmsPutawayResult(
                transaction_id=entry.transaction.id,
                target_bin=placed,
                source_balance=source_reference,
                destination_balance=destination_reference,
                event_id=event_id,
                audit_event_id=audit_id,
            )
            await self._idempotency.complete(
                session,
                decision,
                response_status=201,
                response_body=result.to_dict(),
            )
            return result


def _ledger_entry(command: ExecutePutaway, *, actor_id: UUID) -> InventoryLedgerEntry:
    transaction = InventoryTransaction.create(
        company_id=command.company_id,
        transaction_type=InventoryTransactionType.TRANSFER,
        reference_type=f"WMS_{command.source_type.value}",
        reference_id=command.source_id,
        created_by=actor_id,
    )
    destination_state = {
        StockCondition.AVAILABLE: InventoryState.AVAILABLE,
        StockCondition.DAMAGED: InventoryState.DAMAGED,
        StockCondition.QUARANTINE: InventoryState.QUARANTINE,
    }[command.condition]
    postings = (
        InventoryPosting.create(
            company_id=command.company_id,
            transaction_id=transaction.id,
            sequence=1,
            product_id=command.product_id,
            warehouse_id=command.warehouse_id,
            location_id=command.source_location_id,
            lot_id=command.lot_id,
            pool_id=command.pool_id,
            state=InventoryState.RECEIVING_STAGE,
            quantity_delta=-command.quantity,
        ),
        InventoryPosting.create(
            company_id=command.company_id,
            transaction_id=transaction.id,
            sequence=2,
            product_id=command.product_id,
            warehouse_id=command.warehouse_id,
            location_id=command.target_bin_id,
            lot_id=command.lot_id,
            pool_id=command.pool_id,
            state=destination_state,
            quantity_delta=command.quantity,
        ),
    )
    return InventoryLedgerEntry(transaction, postings)


def _balance_reference(balance: InventoryBalance) -> InventoryBalanceReference:
    quantity = balance.quantity.value
    available = quantity if balance.state is InventoryState.AVAILABLE else Decimal("0")
    return InventoryBalanceReference(
        company_id=balance.company_id,
        product_id=balance.product_id,
        warehouse_id=balance.warehouse_id,
        location_id=balance.location_id,
        lot_id=balance.lot_id,
        pool_id=balance.pool_id,
        state=balance.state,
        on_hand=quantity,
        reserved=Decimal("0"),
        available=available,
        version=balance.version,
    )


__all__ = ["PostgresWmsPutawayStore"]
