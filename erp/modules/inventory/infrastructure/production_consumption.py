"""M5 adapter that converts production reservations into immutable stock issues."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from erp.modules.inventory.application.commands import CommandMetadata
from erp.modules.inventory.application.ledger import InventoryLedgerEntry
from erp.modules.inventory.contracts import (
    ConsumeProductionMaterialsContract,
    ProductionMaterialConsumptionGateway,
    ProductionMaterialConsumptionResultContract,
    ProductionMaterialConsumptionTraceContract,
)
from erp.modules.inventory.domain import (
    InventoryPosting,
    InventoryReservationStatus,
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
from erp.modules.inventory.infrastructure.reservation_effects import (
    InventoryReservationEffects,
)
from erp.modules.inventory.infrastructure.reservation_model import (
    InventoryReservationAllocationModel,
    InventoryReservationModel,
)
from erp.modules.inventory.infrastructure.reservations import (
    _reservation,
    _reservation_conflict,
)


class SessionProductionMaterialConsumptionGateway(
    ProductionMaterialConsumptionGateway
):
    """Consume locked HARD allocations in the caller-owned transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def consume_production_materials(
        self,
        command: ConsumeProductionMaterialsContract,
        actor_id: UUID,
    ) -> ProductionMaterialConsumptionResultContract:
        if not isinstance(actor_id, UUID) or actor_id.int == 0:
            raise ValueError("actor_id must be a non-zero UUID.")
        requested = _requested(command)
        model = await self._session.scalar(
            select(InventoryReservationModel)
            .options(selectinload(InventoryReservationModel.allocations))
            .where(
                InventoryReservationModel.company_id == command.company_id,
                InventoryReservationModel.reference_type == "PRODUCTION_ORDER",
                InventoryReservationModel.reference_id == command.production_order_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if model is None:
            raise _reservation_conflict(
                "No material reservation exists for this production order."
            )
        if model.status == InventoryReservationStatus.RELEASED:
            if command.finalize_reservation and not requested:
                return ProductionMaterialConsumptionResultContract(
                    model.id, None, True, ()
                )
            raise _reservation_conflict(
                "The production material reservation is already released."
            )
        if model.status != InventoryReservationStatus.ACTIVE:
            raise _reservation_conflict(
                "Only active production material reservations can be consumed."
            )
        allocations = tuple(
            await self._session.scalars(
                select(InventoryReservationAllocationModel)
                .where(
                    InventoryReservationAllocationModel.company_id
                    == command.company_id,
                    InventoryReservationAllocationModel.reservation_id == model.id,
                )
                .order_by(
                    InventoryReservationAllocationModel.product_id,
                    InventoryReservationAllocationModel.warehouse_id,
                    InventoryReservationAllocationModel.lot_id,
                    InventoryReservationAllocationModel.id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        available: dict[UUID, Decimal] = defaultdict(lambda: Decimal("0"))
        for allocation in allocations:
            available[allocation.product_id] += allocation.quantity
        for product_id, quantity in requested.items():
            if available[product_id] < quantity:
                raise _reservation_conflict(
                    "Actual consumption exceeds the remaining HARD reservation."
                )

        transaction = None
        postings: list[InventoryPosting] = []
        traces: list[ProductionMaterialConsumptionTraceContract] = []
        remaining_by_allocation = {value.id: value.quantity for value in allocations}
        if requested:
            transaction = InventoryTransaction.create(
                company_id=command.company_id,
                transaction_type=InventoryTransactionType.ISSUE,
                reference_type="PRODUCTION_CONSUMPTION",
                reference_id=command.production_order_id,
                created_by=actor_id,
                occurred_at=datetime.now(UTC),
            )
            sequence = 1
            for product_id, quantity in requested.items():
                remaining = quantity
                for allocation in allocations:
                    if allocation.product_id != product_id or remaining == 0:
                        continue
                    if allocation.lot_id is None:
                        raise _reservation_conflict(
                            "Production material consumption requires lot traceability."
                        )
                    consumed = min(allocation.quantity, remaining)
                    postings.append(
                        InventoryPosting.create(
                            company_id=command.company_id,
                            transaction_id=transaction.id,
                            sequence=sequence,
                            product_id=allocation.product_id,
                            warehouse_id=allocation.warehouse_id,
                            location_id=allocation.location_id,
                            lot_id=allocation.lot_id,
                            pool_id=allocation.pool_id,
                            state=InventoryState(allocation.state),
                            quantity_delta=-consumed,
                        )
                    )
                    traces.append(
                        ProductionMaterialConsumptionTraceContract(
                            allocation.product_id,
                            allocation.lot_id,
                            consumed,
                        )
                    )
                    remaining_by_allocation[allocation.id] -= consumed
                    remaining -= consumed
                    sequence += 1
            entry = InventoryLedgerEntry(transaction, tuple(postings))
            await InventoryLedgerRepository(
                self._session, company_id=command.company_id
            ).append(entry)
            balances = InventoryBalanceRepository(
                self._session, company_id=command.company_id
            )
            for posting in postings:
                await balances.apply(posting)

        all_consumed = bool(allocations) and all(
            quantity == 0 for quantity in remaining_by_allocation.values()
        )
        release = command.finalize_reservation or all_consumed
        before = _reservation(model)
        if release:
            model.status = InventoryReservationStatus.RELEASED
        else:
            for allocation in allocations:
                remaining = remaining_by_allocation[allocation.id]
                if remaining == 0:
                    await self._session.delete(allocation)
                elif remaining != allocation.quantity:
                    allocation.quantity = remaining
            model.updated_at = datetime.now(UTC)
        await self._session.flush()
        await InventoryReservationEffects().record(
            self._session,
            _reservation(model),
            event_type="ProductionMaterialsConsumed",
            actor_id=actor_id,
            metadata=CommandMetadata(
                request_id=command.request_id,
                correlation_id=command.correlation_id,
                source_ip=command.source_ip,
            ),
            before=before,
        )
        return ProductionMaterialConsumptionResultContract(
            model.id,
            None if transaction is None else transaction.id,
            release,
            tuple(traces),
        )


def _requested(
    command: ConsumeProductionMaterialsContract,
) -> dict[UUID, Decimal]:
    requested: dict[UUID, Decimal] = {}
    for line in command.lines:
        if not isinstance(line.product_id, UUID) or line.product_id.int == 0:
            raise _reservation_conflict("Production material product must be a UUID.")
        if (
            not isinstance(line.quantity, Decimal)
            or not line.quantity.is_finite()
            or line.quantity <= 0
        ):
            raise _reservation_conflict(
                "Production material consumption must be a positive Decimal."
            )
        if line.product_id in requested:
            raise _reservation_conflict(
                "Production material products must be unique per consumption."
            )
        requested[line.product_id] = line.quantity
    if not requested and not command.finalize_reservation:
        raise _reservation_conflict("A partial consumption cannot be empty.")
    return requested


__all__ = ["SessionProductionMaterialConsumptionGateway"]
