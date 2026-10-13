"""Pure ThreeWayMatchSession snapshots, invariants and lifecycle."""

from collections.abc import Callable
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import UUID, uuid4

import pytest

from erp.modules.procurement.domain import (
    FinancialMatchSnapshot,
    InvalidMatchingSessionError,
    InvalidMatchingSnapshotError,
    InvalidMatchingTransitionError,
    MatchingScopeError,
    MatchingTolerancePolicy,
    MatchStatus,
    PurchaseOrderMatchSnapshot,
    ReceivingFiscalMatchSnapshot,
    ThreeWayMatchLine,
    ThreeWayMatchSession,
    ThreeWayMatchSessionStatus,
    VersionedArtifactReference,
)

CAPTURED_AT = datetime(2026, 10, 13, 10, 0, tzinfo=UTC)
CREATED_AT = CAPTURED_AT + timedelta(minutes=1)
STARTED_AT = CREATED_AT + timedelta(minutes=1)
COMPLETED_AT = STARTED_AT + timedelta(minutes=1)
DECIDED_AT = COMPLETED_AT + timedelta(minutes=1)


def snapshots(
    *, company_id: UUID | None = None, supplier_id: UUID | None = None
) -> tuple[
    PurchaseOrderMatchSnapshot,
    ReceivingFiscalMatchSnapshot,
    FinancialMatchSnapshot,
]:
    company = company_id or uuid4()
    supplier = supplier_id or uuid4()
    purchase = PurchaseOrderMatchSnapshot.capture(
        company_id=company,
        purchase_order_id=uuid4(),
        purchase_order_version=4,
        supplier_id=supplier,
        currency="brl",
        total_amount="100.00",
        captured_at=CAPTURED_AT,
    )
    receiving = ReceivingFiscalMatchSnapshot.capture(
        company_id=company,
        goods_receipts=(VersionedArtifactReference(uuid4(), 3),),
        fiscal_documents=(VersionedArtifactReference(uuid4(), 2),),
        supplier_id=supplier,
        currency="BRL",
        invoiced_total_amount="100.00",
        captured_at=CAPTURED_AT,
    )
    finance = FinancialMatchSnapshot.capture(
        company_id=company,
        provisional_entry_id=uuid4(),
        provisional_entry_version=2,
        payable_id=uuid4(),
        payable_version=3,
        supplier_id=supplier,
        currency="BRL",
        obligation_amount="100.00",
        captured_at=CAPTURED_AT,
    )
    return purchase, receiving, finance


def match_line(
    *,
    company_id: UUID,
    received: str = "10",
    invoiced: str = "10",
    invoiced_price: str = "10",
    key: str = "SKU-001",
) -> ThreeWayMatchLine:
    return ThreeWayMatchLine.create(
        company_id=company_id,
        match_key=key,
        purchase_order_item_id=uuid4(),
        goods_receipt_item_id=uuid4(),
        fiscal_document_item_id=uuid4(),
        ordered_quantity="10",
        received_quantity=received,
        invoiced_quantity=invoiced,
        ordered_unit_price="10",
        invoiced_unit_price=invoiced_price,
        currency="BRL",
    )


def session(
    *,
    divergent: bool = False,
    company_id: UUID | None = None,
) -> ThreeWayMatchSession:
    purchase, receiving, finance = snapshots(company_id=company_id)
    line = match_line(
        company_id=purchase.company_id,
        received="9" if divergent else "10",
    )
    return ThreeWayMatchSession.create(
        company_id=purchase.company_id,
        purchase_order_snapshot=purchase,
        receiving_fiscal_snapshot=receiving,
        financial_snapshot=finance,
        tolerance_policy=MatchingTolerancePolicy.create(company_id=purchase.company_id),
        lines=(line,),
        created_by=uuid4(),
        created_at=CREATED_AT,
    )


def evaluated_session(*, divergent: bool) -> ThreeWayMatchSession:
    return (
        session(divergent=divergent)
        .start(occurred_at=STARTED_AT)
        .evaluate(occurred_at=COMPLETED_AT)
    )


def test_snapshots_freeze_source_versions_and_normalized_values() -> None:
    purchase, receiving, finance = snapshots()
    assert purchase.currency == "BRL"
    assert purchase.total_amount == Decimal("100.00")
    assert purchase.purchase_order.version == 4
    assert receiving.goods_receipts[0].version == 3
    assert receiving.fiscal_documents[0].version == 2
    assert finance.provisional_entry.version == 2
    assert finance.payable is not None
    assert finance.payable.version == 3
    with pytest.raises(FrozenInstanceError):
        purchase.total_amount = Decimal("200")  # type: ignore[misc]


def test_pending_running_and_matched_are_new_aggregate_versions() -> None:
    pending = session()
    running = pending.start(occurred_at=STARTED_AT)
    matched = running.evaluate(occurred_at=COMPLETED_AT)

    assert pending.status is ThreeWayMatchSessionStatus.PENDING
    assert pending.version == 1
    assert running.status is ThreeWayMatchSessionStatus.RUNNING
    assert running.started_at == STARTED_AT
    assert running.version == 2
    assert matched.status is ThreeWayMatchSessionStatus.MATCHED
    assert matched.completed_at == COMPLETED_AT
    assert matched.report is not None
    assert matched.report.matched
    assert matched.version == 3
    assert pending.started_at is None


def test_discrepancy_can_be_overridden_with_m22_decision() -> None:
    discrepancy = evaluated_session(divergent=True)
    actor_id = uuid4()
    workflow_id = uuid4()
    overridden = discrepancy.override(
        decided_by=actor_id,
        workflow_instance_id=workflow_id,
        reason="Aprovação excepcional registrada pela gerência financeira.",
        occurred_at=DECIDED_AT,
    )
    assert discrepancy.status is ThreeWayMatchSessionStatus.DISCREPANCY_DETECTED
    assert overridden.status is ThreeWayMatchSessionStatus.OVERRIDDEN
    assert overridden.decision_by == actor_id
    assert overridden.decision_workflow_instance_id == workflow_id
    assert overridden.decision_reason == (
        "Aprovação excepcional registrada pela gerência financeira."
    )
    assert overridden.decided_at == DECIDED_AT
    assert overridden.version == 4


def test_discrepancy_can_be_rejected_with_m22_decision() -> None:
    rejected = evaluated_session(divergent=True).reject(
        decided_by=uuid4(),
        workflow_instance_id=uuid4(),
        reason="Divergência comercial sem autorização para pagamento.",
        occurred_at=DECIDED_AT,
    )
    assert rejected.status is ThreeWayMatchSessionStatus.REJECTED
    assert rejected.decision_reason == ("Divergência comercial sem autorização para pagamento.")


def test_financial_snapshot_supports_provision_without_payable() -> None:
    company_id, supplier_id = uuid4(), uuid4()
    snapshot = FinancialMatchSnapshot.capture(
        company_id=company_id,
        provisional_entry_id=uuid4(),
        provisional_entry_version=1,
        payable_id=None,
        payable_version=None,
        supplier_id=supplier_id,
        currency="BRL",
        obligation_amount="1.005",
        captured_at=CAPTURED_AT,
    )
    assert snapshot.payable is None
    assert snapshot.obligation_amount == Decimal("1.01")


@pytest.mark.parametrize(
    ("action", "message"),
    [
        ("evaluate_pending", "running"),
        ("start_running", "pending"),
        ("override_matched", "discrepancy"),
        ("reject_pending", "discrepancy"),
        ("evaluate_completed", "running"),
    ],
)
def test_invalid_lifecycle_transitions_fail_closed(action: str, message: str) -> None:
    pending = session()
    running = pending.start(occurred_at=STARTED_AT)
    matched = running.evaluate(occurred_at=COMPLETED_AT)
    mutations: dict[str, Callable[[], object]] = {
        "evaluate_pending": lambda: pending.evaluate(occurred_at=COMPLETED_AT),
        "start_running": lambda: running.start(occurred_at=STARTED_AT),
        "override_matched": lambda: matched.override(
            decided_by=uuid4(),
            workflow_instance_id=uuid4(),
            reason="Decisão inválida sobre match sem divergência.",
        ),
        "reject_pending": lambda: pending.reject(
            decided_by=uuid4(),
            workflow_instance_id=uuid4(),
            reason="Decisão inválida antes da execução do match.",
        ),
        "evaluate_completed": lambda: matched.evaluate(),
    }
    with pytest.raises(InvalidMatchingTransitionError, match=message):
        mutations[action]()


@pytest.mark.parametrize(
    ("transition", "occurred_at", "message"),
    [
        ("start", CREATED_AT - timedelta(seconds=1), "prior transition"),
        ("start", CREATED_AT.replace(tzinfo=None), "timezone-aware"),
        ("evaluate", STARTED_AT - timedelta(seconds=1), "prior transition"),
        ("decide", COMPLETED_AT - timedelta(seconds=1), "prior transition"),
    ],
)
def test_transition_timestamps_are_monotonic(
    transition: str, occurred_at: datetime, message: str
) -> None:
    mutations: dict[str, Callable[[], object]] = {
        "start": lambda: session().start(occurred_at=occurred_at),
        "evaluate": lambda: (
            session().start(occurred_at=STARTED_AT).evaluate(occurred_at=occurred_at)
        ),
        "decide": lambda: evaluated_session(divergent=True).override(
            decided_by=uuid4(),
            workflow_instance_id=uuid4(),
            reason="Decisão com instante inválido para a sessão.",
            occurred_at=occurred_at,
        ),
    }
    with pytest.raises(InvalidMatchingTransitionError, match=message):
        mutations[transition]()


def test_session_rejects_cross_tenant_supplier_currency_and_future_snapshot() -> None:
    valid = session()
    with pytest.raises(MatchingScopeError, match="same company"):
        replace(
            valid,
            tolerance_policy=replace(valid.tolerance_policy, company_id=uuid4()),
        )
    with pytest.raises(MatchingScopeError, match="every match line"):
        replace(valid, lines=(replace(valid.lines[0], company_id=uuid4()),))
    with pytest.raises(InvalidMatchingSessionError, match="one supplier"):
        replace(
            valid,
            financial_snapshot=replace(valid.financial_snapshot, supplier_id=uuid4()),
        )
    with pytest.raises(InvalidMatchingSessionError, match="one currency"):
        replace(valid, financial_snapshot=replace(valid.financial_snapshot, currency="USD"))
    with pytest.raises(InvalidMatchingSessionError, match="cannot precede"):
        replace(valid, created_at=CAPTURED_AT - timedelta(seconds=1))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("id", "invalid", "session id"),
        ("company_id", "invalid", "company_id"),
        ("created_by", "invalid", "created_by"),
        ("version", 0, "positive integer"),
        ("version", True, "positive integer"),
        ("status", "PENDING", "ThreeWayMatchSessionStatus"),
        ("purchase_order_snapshot", "invalid", "PurchaseOrderMatchSnapshot"),
        ("receiving_fiscal_snapshot", "invalid", "ReceivingFiscalMatchSnapshot"),
        ("financial_snapshot", "invalid", "FinancialMatchSnapshot"),
        ("tolerance_policy", "invalid", "MatchingTolerancePolicy"),
        ("lines", (), "non-empty tuple"),
        ("lines", ["invalid"], "non-empty tuple"),
        ("lines", ("invalid",), "every line"),
        ("created_at", CREATED_AT.replace(tzinfo=None), "timezone-aware"),
    ],
)
def test_session_rejects_invalid_boundary_contracts(
    field: str, value: object, message: str
) -> None:
    with pytest.raises(InvalidMatchingSessionError, match=message):
        replace(session(), **{field: value})  # type: ignore[arg-type]


def test_session_rejects_duplicate_match_keys() -> None:
    valid = session()
    duplicate = replace(valid.lines[0], purchase_order_item_id=uuid4())
    with pytest.raises(InvalidMatchingSessionError, match="unique"):
        replace(valid, lines=(valid.lines[0], duplicate))


@pytest.mark.parametrize(
    ("value", "version", "message"),
    [
        ("invalid", 1, "UUID"),
        (uuid4(), 0, "positive integer"),
        (uuid4(), True, "positive integer"),
    ],
)
def test_versioned_reference_rejects_invalid_values(
    value: object, version: object, message: str
) -> None:
    with pytest.raises(InvalidMatchingSnapshotError, match=message):
        VersionedArtifactReference(cast(UUID, value), cast(int, version))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("company_id", "invalid", "company_id"),
        ("supplier_id", "invalid", "supplier_id"),
        ("currency", "REAL", "ISO 4217"),
        ("total_amount", "0", "positive"),
        ("total_amount", "NaN", "finite"),
        ("total_amount", "bad", "valid decimal"),
        ("total_amount", "1E+999999", "valid decimal"),
        ("captured_at", CAPTURED_AT.replace(tzinfo=None), "timezone-aware"),
        ("purchase_order", "invalid", "VersionedArtifactReference"),
    ],
)
def test_purchase_snapshot_rejects_invalid_contracts(
    field: str, value: object, message: str
) -> None:
    purchase = snapshots()[0]
    with pytest.raises(InvalidMatchingSnapshotError, match=message):
        replace(purchase, **{field: value})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("goods_receipts", (), "non-empty tuple"),
        ("goods_receipts", [VersionedArtifactReference(uuid4(), 1)], "non-empty tuple"),
        ("fiscal_documents", ("invalid",), "VersionedArtifactReference"),
    ],
)
def test_receiving_snapshot_rejects_invalid_reference_sets(
    field: str, value: object, message: str
) -> None:
    receiving = snapshots()[1]
    with pytest.raises(InvalidMatchingSnapshotError, match=message):
        replace(receiving, **{field: value})  # type: ignore[arg-type]


def test_receiving_snapshot_rejects_duplicate_references() -> None:
    receiving = snapshots()[1]
    duplicate = VersionedArtifactReference(uuid4(), 1)
    with pytest.raises(InvalidMatchingSnapshotError, match="unique"):
        replace(receiving, goods_receipts=(duplicate, duplicate))


def test_financial_snapshot_requires_consistent_payable_reference() -> None:
    company_id, supplier_id = uuid4(), uuid4()
    with pytest.raises(InvalidMatchingSnapshotError, match="both present or both absent"):
        FinancialMatchSnapshot.capture(
            company_id=company_id,
            provisional_entry_id=uuid4(),
            provisional_entry_version=1,
            payable_id=uuid4(),
            payable_version=None,
            supplier_id=supplier_id,
            currency="BRL",
            obligation_amount="10",
        )
    valid = snapshots()[2]
    with pytest.raises(InvalidMatchingSnapshotError, match="provisional_entry"):
        replace(valid, provisional_entry=cast(VersionedArtifactReference, "invalid"))
    with pytest.raises(InvalidMatchingSnapshotError, match="payable"):
        replace(valid, payable=cast(VersionedArtifactReference, "invalid"))


@pytest.mark.parametrize("reason", ["short", "x" * 501, cast(str, 1)])
def test_decision_requires_valid_reason(reason: str) -> None:
    discrepancy = evaluated_session(divergent=True)
    with pytest.raises(InvalidMatchingSessionError, match="decision reason"):
        discrepancy.override(
            decided_by=uuid4(),
            workflow_instance_id=uuid4(),
            reason=reason,
        )


def test_decision_requires_uuid_actor_and_workflow() -> None:
    discrepancy = evaluated_session(divergent=True)
    with pytest.raises(InvalidMatchingSessionError, match="decided_by"):
        discrepancy.override(
            decided_by=cast(UUID, "invalid"),
            workflow_instance_id=uuid4(),
            reason="Decisão com ator inválido para auditoria.",
        )
    with pytest.raises(InvalidMatchingSessionError, match="workflow"):
        discrepancy.reject(
            decided_by=uuid4(),
            workflow_instance_id=cast(UUID, "invalid"),
            reason="Decisão com workflow inválido para auditoria.",
        )


def test_direct_lifecycle_reconstruction_rejects_inconsistent_states() -> None:
    pending = session()
    running = pending.start(occurred_at=STARTED_AT)
    matched = running.evaluate(occurred_at=COMPLETED_AT)
    discrepancy = evaluated_session(divergent=True)
    overridden = discrepancy.override(
        decided_by=uuid4(),
        workflow_instance_id=uuid4(),
        reason="Exceção válida para testar reconstrução persistente.",
        occurred_at=DECIDED_AT,
    )
    assert matched.report is not None
    matched_report = matched.report
    assert overridden.report is not None
    matched_override_report = replace(overridden.report, status=MatchStatus.MATCHED)

    invalid_cases: tuple[tuple[Callable[[], object], type[ValueError], str], ...] = (
        (
            lambda: replace(pending, started_at=STARTED_AT),
            InvalidMatchingSessionError,
            "pending session",
        ),
        (
            lambda: replace(running, started_at=None),
            InvalidMatchingSessionError,
            "requires started_at",
        ),
        (
            lambda: replace(running, started_at=CREATED_AT - timedelta(seconds=1)),
            InvalidMatchingSessionError,
            "cannot precede created_at",
        ),
        (
            lambda: replace(running, completed_at=COMPLETED_AT),
            InvalidMatchingSessionError,
            "running session",
        ),
        (
            lambda: replace(matched, completed_at=None),
            InvalidMatchingSessionError,
            "requires completed_at",
        ),
        (
            lambda: replace(matched, completed_at=STARTED_AT - timedelta(seconds=1)),
            InvalidMatchingSessionError,
            "cannot precede",
        ),
        (
            lambda: replace(matched, report=replace(matched_report, company_id=uuid4())),
            MatchingScopeError,
            "session company",
        ),
        (
            lambda: replace(
                matched,
                tolerance_policy=replace(matched.tolerance_policy, version=2),
            ),
            InvalidMatchingSessionError,
            "frozen",
        ),
        (
            lambda: replace(
                matched,
                status=ThreeWayMatchSessionStatus.DISCREPANCY_DETECTED,
            ),
            InvalidMatchingSessionError,
            "does not match",
        ),
        (
            lambda: replace(matched, decision_by=uuid4()),
            InvalidMatchingSessionError,
            "cannot contain decision",
        ),
        (
            lambda: replace(overridden, report=matched_override_report),
            InvalidMatchingSessionError,
            "discrepancy report",
        ),
        (
            lambda: replace(overridden, decision_reason=None),
            InvalidMatchingSessionError,
            "requires actor",
        ),
        (
            lambda: replace(overridden, decided_at=COMPLETED_AT - timedelta(seconds=1)),
            InvalidMatchingSessionError,
            "cannot precede",
        ),
    )
    for mutation, error_type, message in invalid_cases:
        with pytest.raises(error_type, match=message):
            mutation()
