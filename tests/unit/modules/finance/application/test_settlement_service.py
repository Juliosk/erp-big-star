"""Framework-neutral settlement orchestration tests."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.application import (
    PAYMENT_BATCH_CONFIRMED,
    PAYMENT_BATCH_FAILED,
    PAYMENT_BATCH_SUBMITTED,
    BankReturnOutcome,
    BankSettlementNotification,
    PaymentBatchEvent,
    PaymentSettlementService,
    SubmitPaymentBatch,
    TreasuryCommandMetadata,
)
from erp.modules.finance.domain import (
    BankAccountType,
    BankRemittanceFormat,
    BeneficiaryBankAccount,
    MatchingGateStatus,
    Payable,
    PayableInstallmentPaymentSnapshot,
    PayableInstallmentStatus,
    PayableSegregationPolicy,
    PayableStatus,
    PaymentBatch,
    PaymentBatchItem,
    PaymentBatchStatus,
    PaymentEligibilityPolicy,
    PaymentExecutionMode,
    TreasurySegregationPolicy,
)
from erp.platform.errors import ApplicationError


class BatchStore:
    def __init__(self, value: PaymentBatch) -> None:
        self.value = value

    async def get_for_update(self, batch_id: UUID) -> PaymentBatch | None:
        return self.value if self.value.id == batch_id else None

    async def save(
        self,
        batch: PaymentBatch,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> PaymentBatch:
        del actor_id
        assert expected_version == self.value.version
        self.value = batch
        return batch


class PayableStore:
    def __init__(self, value: Payable) -> None:
        self.value = value

    async def get_for_update(self, payable_id: UUID) -> Payable | None:
        return self.value if self.value.id == payable_id else None

    async def save(
        self,
        payable: Payable,
        *,
        actor_id: UUID,
        expected_version: int | None = None,
    ) -> Payable:
        del actor_id
        assert expected_version == self.value.version
        self.value = payable
        return payable


class Events:
    def __init__(self) -> None:
        self.values: list[PaymentBatchEvent] = []

    async def publish(
        self,
        event: PaymentBatchEvent,
        *,
        metadata: TreasuryCommandMetadata,
    ) -> UUID:
        del metadata
        self.values.append(event)
        return uuid4()


def _fixture() -> tuple[PaymentBatch, Payable, UUID]:
    company_id = uuid4()
    creator = uuid4()
    approver = uuid4()
    payable = Payable.create(
        company_id=company_id,
        number="PAYABLE-175",
        supplier_id=uuid4(),
        supplier_tax_id="12345678000195",
        created_by=creator,
        provisional_entry_id=uuid4(),
        nominal_amount=Decimal("125.40"),
        installment_plan=((date(2026, 12, 10), Decimal("125.40")),),
    )
    payable = payable.submit_for_approval().approve(
        approver_id=approver,
        policy=PayableSegregationPolicy(Decimal("1.00")),
    )
    installment = payable.installments[0]
    batch_id = uuid4()
    snapshot = PayableInstallmentPaymentSnapshot(
        company_id=company_id,
        payable_id=payable.id,
        installment_id=installment.id,
        supplier_id=payable.supplier_id,
        amount=installment.amount,
        currency=payable.currency,
        due_date=installment.due_date,
        payable_status=payable.status,
        installment_status=installment.status,
        matching_status=MatchingGateStatus.MATCHED,
        matching_session_id=uuid4(),
        payable_created_by=creator,
        payable_approved_by=approver,
        beneficiary=BeneficiaryBankAccount(
            bank_code="001",
            branch_number="1234",
            account_number="987654",
            account_digit="X",
            account_type=BankAccountType.CHECKING,
            holder_name="Supplier",
            holder_tax_id="12345678000195",
        ),
    )
    batch = PaymentBatch(
        id=batch_id,
        company_id=company_id,
        code="BATCH-175",
        treasury_account_id=uuid4(),
        scheduled_date=date(2026, 12, 9),
        created_by=uuid4(),
        remittance_format=BankRemittanceFormat.CNAB_240,
        execution_mode=PaymentExecutionMode.PRODUCTION,
        items=(
            PaymentBatchItem.from_snapshot(
                item_id=uuid4(),
                batch_id=batch_id,
                snapshot=snapshot,
                policy=PaymentEligibilityPolicy(),
            ),
        ),
    )
    policy = TreasurySegregationPolicy()
    batch = batch.submit_for_approval().approve(actor_id=uuid4(), policy=policy)
    executor = uuid4()
    return batch.release(actor_id=executor, policy=policy), payable, executor


def test_bank_confirmation_settles_and_replay_is_idempotent() -> None:
    async def scenario() -> None:
        batch, payable, executor = _fixture()
        batches = BatchStore(batch)
        payables = PayableStore(payable)
        events = Events()
        service = PaymentSettlementService(batches, payables, events)
        metadata = TreasuryCommandMetadata.new()
        submitted = await service.record_submission(
            SubmitPaymentBatch(
                batch.company_id,
                batch.id,
                batch.version,
                "REM-175",
                datetime(2026, 12, 9, 12, 0, tzinfo=UTC),
                metadata,
            ),
            actor_id=executor,
        )
        notification = BankSettlementNotification(
            batch.company_id,
            batch.id,
            "BANK-175",
            "00",
            BankReturnOutcome.CONFIRMED,
            datetime(2026, 12, 10, 12, 0, tzinfo=UTC),
            Decimal("125.40"),
        )

        settled = await service.process(
            notification,
            actor_id=executor,
            metadata=metadata,
        )
        replay = await service.process(
            notification,
            actor_id=executor,
            metadata=metadata,
        )

        assert submitted.payables[0].status is PayableStatus.SCHEDULED
        assert settled.batch.status is PaymentBatchStatus.CONFIRMED
        assert settled.payables[0].status is PayableStatus.PAID
        assert replay.replayed is True
        assert [event.event_type for event in events.values] == [
            PAYMENT_BATCH_SUBMITTED,
            PAYMENT_BATCH_CONFIRMED,
        ]

    asyncio.run(scenario())


@pytest.mark.parametrize("outcome", [BankReturnOutcome.REJECTED, BankReturnOutcome.FAILED])
def test_bank_failure_releases_installment(outcome: BankReturnOutcome) -> None:
    async def scenario() -> None:
        batch, payable, executor = _fixture()
        batches = BatchStore(batch)
        payables = PayableStore(payable)
        events = Events()
        service = PaymentSettlementService(batches, payables, events)
        metadata = TreasuryCommandMetadata.new()
        await service.record_submission(
            SubmitPaymentBatch(
                batch.company_id,
                batch.id,
                batch.version,
                "REM-175",
                datetime(2026, 12, 9, 12, 0, tzinfo=UTC),
                metadata,
            ),
            actor_id=executor,
        )

        result = await service.process(
            BankSettlementNotification(
                batch.company_id,
                batch.id,
                "BANK-FAIL-175",
                "AG",
                outcome,
                datetime(2026, 12, 10, 12, 0, tzinfo=UTC),
                reason="Invalid beneficiary account",
            ),
            actor_id=executor,
            metadata=metadata,
        )

        assert result.batch.status is PaymentBatchStatus.FAILED
        assert result.payables[0].status is PayableStatus.APPROVED
        assert result.payables[0].installments[0].status is PayableInstallmentStatus.OPEN
        assert events.values[-1].event_type == PAYMENT_BATCH_FAILED
        assert events.values[-1].payload["bank_failure"] == {
            "kind": outcome.value,
            "protocol": "BANK-FAIL-175",
            "status_code": "AG",
            "failed_at": "2026-12-10T12:00:00+00:00",
            "reason": "Invalid beneficiary account",
        }

    asyncio.run(scenario())


def test_mismatched_bank_amount_does_not_mark_payable_paid() -> None:
    async def scenario() -> None:
        batch, payable, executor = _fixture()
        batches = BatchStore(batch)
        payables = PayableStore(payable)
        service = PaymentSettlementService(batches, payables, Events())
        metadata = TreasuryCommandMetadata.new()
        await service.record_submission(
            SubmitPaymentBatch(
                batch.company_id,
                batch.id,
                batch.version,
                "REM-175",
                datetime(2026, 12, 9, 12, 0, tzinfo=UTC),
                metadata,
            ),
            actor_id=executor,
        )

        with pytest.raises(ApplicationError) as error:
            await service.process(
                BankSettlementNotification(
                    batch.company_id,
                    batch.id,
                    "BANK-175",
                    "00",
                    BankReturnOutcome.CONFIRMED,
                    datetime(2026, 12, 10, 12, 0, tzinfo=UTC),
                    Decimal("1.00"),
                ),
                actor_id=executor,
                metadata=metadata,
            )
        assert error.value.code == "BANK_SETTLEMENT_AMOUNT_MISMATCH"
        assert batches.value.status is PaymentBatchStatus.SUBMITTED
        assert payables.value.status is PayableStatus.SCHEDULED

    asyncio.run(scenario())
