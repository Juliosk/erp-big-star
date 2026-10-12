"""Focused validation for M12 provisioning envelope translation."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from erp.modules.finance.infrastructure.provisioning_consumer import (
    FISCAL_DOCUMENT_AUTHORIZED,
    PURCHASE_ORDER_APPROVED,
    _aggregate_version,
    _fiscal_plan,
    _money_payload,
    _purchase_order_plan,
    _text_payload,
    _uuid_payload,
    _validate_envelope,
)
from erp.platform.messaging import MessageEnvelope, MessageKind


def _envelope(
    *,
    message_type: str = FISCAL_DOCUMENT_AUTHORIZED,
    payload: dict[str, object] | None = None,
) -> MessageEnvelope:
    fiscal = message_type == FISCAL_DOCUMENT_AUTHORIZED
    identity = uuid4()
    company_id = uuid4()
    return MessageEnvelope(
        message_id=uuid4(),
        message_kind=MessageKind.DOMAIN_EVENT,
        message_type=message_type,
        event_version=1,
        producer_module="fiscal" if fiscal else "procurement",
        producer_domain="fiscal" if fiscal else "procurement",
        aggregate_type="fiscal_document" if fiscal else "purchase_order",
        aggregate_id=identity,
        aggregate_version=3,
        company_id=company_id,
        branch_id=None,
        occurred_at=datetime(2026, 10, 11, tzinfo=UTC),
        correlation_id=uuid4(),
        causation_id=None,
        request_id=uuid4(),
        payload=payload or {},
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"message_type": "UnknownEvent"},
        {"message_kind": MessageKind.ASYNC_REQUEST},
        {"event_version": 2},
        {"company_id": None},
        {"producer_module": "sales"},
    ],
)
def test_envelope_validation_rejects_each_unsupported_dimension(
    changes: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        _validate_envelope(_envelope().model_copy(update=changes))


@pytest.mark.parametrize(
    "days",
    [None, [], [True], [-1], [30, 30], [60, 30]],
)
def test_purchase_plan_rejects_invalid_installment_days(days: object) -> None:
    envelope = _envelope(
        message_type=PURCHASE_ORDER_APPROVED,
        payload={"installment_days": days},
    )
    with pytest.raises(ValueError, match="installment_days"):
        _purchase_order_plan(envelope, Decimal("100.00"))


def test_purchase_plan_distributes_residual_cents_deterministically() -> None:
    envelope = _envelope(
        message_type=PURCHASE_ORDER_APPROVED,
        payload={"installment_days": [0, 30, 60]},
    )

    plan = _purchase_order_plan(envelope, Decimal("100.00"))

    assert [amount for _, amount in plan] == [
        Decimal("33.34"),
        Decimal("33.33"),
        Decimal("33.33"),
    ]


@pytest.mark.parametrize(
    ("installments", "message"),
    [
        (None, "non-empty"),
        ([], "non-empty"),
        (["bad"], "objects"),
        ([{"due_date": "bad", "amount": "10.00"}], "invalid"),
        ([{"due_date": "2026-11-10", "amount": "bad"}], "invalid"),
        ([{"due_date": "2026-11-10", "amount": "9.00"}], "reconcile"),
    ],
)
def test_fiscal_plan_rejects_invalid_or_unbalanced_installments(
    installments: object,
    message: str,
) -> None:
    envelope = _envelope(payload={"installments": installments})
    with pytest.raises(ValueError, match=message):
        _fiscal_plan(envelope, Decimal("10.00"))


def test_payload_primitives_fail_closed() -> None:
    envelope = _envelope(payload={"invalid_uuid": "bad", "zero": "0", "bad_money": "x"})
    with pytest.raises(ValueError, match="aggregate_version"):
        _aggregate_version(envelope.model_copy(update={"aggregate_version": None}))
    with pytest.raises(ValueError, match="valid missing"):
        _uuid_payload(envelope, "missing")
    with pytest.raises(ValueError, match="valid invalid_uuid"):
        _uuid_payload(envelope, "invalid_uuid")
    with pytest.raises(ValueError, match="requires missing"):
        _text_payload(envelope, "missing")
    with pytest.raises(ValueError, match="valid bad_money"):
        _money_payload(envelope, "bad_money")
    with pytest.raises(ValueError, match="positive zero"):
        _money_payload(envelope, "zero")
