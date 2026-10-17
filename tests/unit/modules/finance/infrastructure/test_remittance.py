"""Deterministic tests for bank-neutral treasury remittance adapters."""

import json
from dataclasses import replace
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest

from erp.modules.finance.domain import (
    BankAccountType,
    BankRemittanceFormat,
    BeneficiaryBankAccount,
    InvalidTreasuryRuleError,
    MatchingGateStatus,
    PayableInstallmentPaymentSnapshot,
    PayableInstallmentStatus,
    PayableStatus,
    PaymentBatch,
    PaymentBatchItem,
    PaymentEligibilityPolicy,
    PaymentExecutionMode,
)
from erp.modules.finance.infrastructure import (
    Cnab240RemittanceAdapter,
    RemittanceAdapterRegistry,
)


def payment_batch(remittance_format: BankRemittanceFormat) -> PaymentBatch:
    batch_id = uuid4()
    company_id = uuid4()
    candidate = PayableInstallmentPaymentSnapshot(
        company_id=company_id,
        payable_id=uuid4(),
        installment_id=uuid4(),
        supplier_id=uuid4(),
        amount=Decimal("125.40"),
        currency="BRL",
        due_date=date(2026, 12, 10),
        payable_status=PayableStatus.APPROVED,
        installment_status=PayableInstallmentStatus.OPEN,
        matching_status=MatchingGateStatus.MATCHED,
        matching_session_id=uuid4(),
        payable_created_by=uuid4(),
        payable_approved_by=uuid4(),
        beneficiary=BeneficiaryBankAccount(
            bank_code="001",
            branch_number="1234",
            account_number="987654",
            account_digit="X",
            account_type=BankAccountType.CHECKING,
            holder_name="Fornecedor Forma Kids",
            holder_tax_id="12345678000195",
        ),
    )
    item = PaymentBatchItem.from_snapshot(
        item_id=uuid4(),
        batch_id=batch_id,
        snapshot=candidate,
        policy=PaymentEligibilityPolicy(),
    )
    return PaymentBatch(
        id=batch_id,
        company_id=company_id,
        code="PAY-174",
        treasury_account_id=uuid4(),
        scheduled_date=date(2026, 12, 9),
        created_by=uuid4(),
        remittance_format=remittance_format,
        execution_mode=PaymentExecutionMode.PRODUCTION,
        items=(item,),
    )


@pytest.mark.parametrize(
    ("remittance_format", "width"),
    [
        (BankRemittanceFormat.CNAB_240, 240),
        (BankRemittanceFormat.CNAB_400, 400),
    ],
)
def test_cnab_adapters_generate_fixed_width_header_detail_and_trailer(
    remittance_format: BankRemittanceFormat,
    width: int,
) -> None:
    artifact = RemittanceAdapterRegistry().generate(payment_batch(remittance_format), dry_run=True)

    assert artifact.filename == "DRYRUN-PAY-174.rem"
    assert artifact.record_count == 3
    assert artifact.total_amount == Decimal("125.40")
    assert len(artifact.checksum_sha256) == 64
    assert {len(line) for line in artifact.content.decode("ascii").splitlines()} == {width}


def test_pix_adapter_generates_canonical_payment_instruction() -> None:
    artifact = RemittanceAdapterRegistry().generate(
        payment_batch(BankRemittanceFormat.PIX_API), dry_run=False
    )
    payload = json.loads(artifact.content)

    assert artifact.filename == "REMESSA-PAY-174.json"
    assert artifact.media_type == "application/json"
    assert payload["dry_run"] is False
    assert payload["payments"][0]["holder_tax_id"] == "12345678000195"
    assert payload["total_amount"] == "125.40"


def test_adapter_rejects_wrong_format_and_non_brl_batch() -> None:
    batch = payment_batch(BankRemittanceFormat.CNAB_400)
    with pytest.raises(InvalidTreasuryRuleError, match="CNAB_240"):
        Cnab240RemittanceAdapter().generate(batch, dry_run=True)

    non_brl_item = replace(batch.items[0], currency="USD")
    non_brl = replace(
        batch,
        remittance_format=BankRemittanceFormat.CNAB_240,
        items=(non_brl_item,),
    )
    with pytest.raises(InvalidTreasuryRuleError, match="require BRL"):
        RemittanceAdapterRegistry().generate(non_brl, dry_run=False)
