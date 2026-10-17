"""Bank return adapters reject malformed evidence and normalize valid records."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from erp.modules.finance.application import BankReturnOutcome
from erp.modules.finance.domain import BankRemittanceFormat, InvalidTreasuryRuleError
from erp.modules.finance.infrastructure import (
    Cnab240ReturnParser,
    Cnab400ReturnParser,
    PixCallbackParser,
)


def _cnab(
    *,
    width: int,
    batch_id: UUID,
    status: str = "00",
    amount_cents: int = 12540,
    reason: str = "",
) -> bytes:
    header = ("0RETURN-175").ljust(width)
    detail = (
        f"3{batch_id.hex}{'PROTO-175':<40}{status:<2}{amount_cents:018d}20261210{reason:<80}"
    ).ljust(width)
    trailer = "9".ljust(width)
    return f"{header}\n{detail}\n{trailer}".encode("ascii")


@pytest.mark.parametrize(
    ("parser", "width", "expected_format"),
    [
        (Cnab240ReturnParser(), 240, BankRemittanceFormat.CNAB_240),
        (Cnab400ReturnParser(), 400, BankRemittanceFormat.CNAB_400),
    ],
)
def test_cnab_return_parses_confirmed_payment(
    parser: Cnab240ReturnParser | Cnab400ReturnParser,
    width: int,
    expected_format: BankRemittanceFormat,
) -> None:
    company_id = uuid4()
    batch_id = uuid4()

    document = parser.parse(_cnab(width=width, batch_id=batch_id), company_id=company_id)

    assert document.remittance_format is expected_format
    assert document.source_reference == "RETURN-175"
    assert document.records[0].payment_batch_id == batch_id
    assert document.records[0].outcome is BankReturnOutcome.CONFIRMED
    assert document.records[0].amount == Decimal("125.40")
    assert document.records[0].occurred_at == datetime(2026, 12, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    ("status", "outcome"),
    [("AG", BankReturnOutcome.REJECTED), ("99", BankReturnOutcome.FAILED)],
)
def test_cnab_return_classifies_failure(status: str, outcome: BankReturnOutcome) -> None:
    document = Cnab240ReturnParser().parse(
        _cnab(
            width=240,
            batch_id=uuid4(),
            status=status,
            amount_cents=0,
            reason="Bank rejected payment",
        ),
        company_id=uuid4(),
    )

    assert document.records[0].outcome is outcome
    assert document.records[0].reason == "Bank rejected payment"


def test_pix_callback_parses_confirmed_and_failed_outcomes() -> None:
    company_id = uuid4()
    batch_id = uuid4()
    base = {
        "event_id": "PIX-EVENT-175",
        "payment_batch_id": str(batch_id),
        "protocol": "PIX-PROTOCOL-175",
        "status_code": "SETTLED",
        "occurred_at": "2026-12-10T14:30:00+00:00",
        "amount": "125.40",
        "status": "CONFIRMED",
    }

    confirmed = PixCallbackParser().parse(json.dumps(base).encode(), company_id=company_id)
    failed_payload = {
        **base,
        "status": "FAILED",
        "status_code": "NO_BALANCE",
        "amount": None,
        "reason": "Insufficient balance",
    }
    failed = PixCallbackParser().parse(json.dumps(failed_payload).encode(), company_id=company_id)

    assert confirmed.records[0].outcome is BankReturnOutcome.CONFIRMED
    assert confirmed.records[0].amount == Decimal("125.40")
    assert failed.records[0].outcome is BankReturnOutcome.FAILED
    assert failed.records[0].reason == "Insufficient balance"


@pytest.mark.parametrize(
    "content",
    [b"", b"invalid", b"0\n3\n9", b"X" * 240],
)
def test_cnab_return_fails_closed_for_malformed_files(content: bytes) -> None:
    with pytest.raises(InvalidTreasuryRuleError):
        Cnab240ReturnParser().parse(content, company_id=uuid4())


def test_pix_callback_requires_trusted_typed_evidence() -> None:
    with pytest.raises(InvalidTreasuryRuleError):
        PixCallbackParser().parse(b"[]", company_id=uuid4())
    with pytest.raises(InvalidTreasuryRuleError):
        PixCallbackParser().parse(b"{}", company_id=uuid4())
    with pytest.raises(InvalidTreasuryRuleError):
        PixCallbackParser().parse(b"{}", company_id=UUID(int=0))
