"""Inbox-backed M12 provisioning consumer for M11 and M6 domain events."""

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from erp.modules.finance.domain import (
    Payable,
    PayableStatus,
    ProvisionalEntryOrigin,
    ProvisionalEntryStatus,
    ProvisionalFinancialEntry,
)
from erp.modules.finance.infrastructure.payable_repository import PayableRepository
from erp.modules.finance.infrastructure.provisional_repository import (
    ProvisionalEntryRepository,
)
from erp.platform.audit import AuditEvent, AuditService
from erp.platform.database import Database
from erp.platform.inbox import InboxProcessResult, InboxService
from erp.platform.messaging import MessageEnvelope, MessageKind

FISCAL_DOCUMENT_AUTHORIZED = "FiscalDocumentAuthorized"
FISCAL_DOCUMENT_CANCELLED = "FiscalDocumentCancelled"
PURCHASE_ORDER_APPROVED = "PurchaseOrderApproved"
FINANCE_PAYABLE_PROVISIONING_CONSUMER = "finance.payable-provisioning.v1"


class PayableProvisioningService:
    """Apply one translated upstream fact inside the caller-owned transaction."""

    async def apply(self, session: AsyncSession, envelope: MessageEnvelope) -> None:
        assert envelope.company_id is not None
        if envelope.message_type == PURCHASE_ORDER_APPROVED:
            await self._provision_purchase_order(session, envelope)
        elif envelope.message_type == FISCAL_DOCUMENT_AUTHORIZED:
            await self._provision_fiscal_document(session, envelope)
        else:
            await self._cancel_fiscal_document(session, envelope)

    async def _provision_purchase_order(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
    ) -> None:
        assert envelope.company_id is not None
        entries = ProvisionalEntryRepository(session, company_id=envelope.company_id)
        existing = await entries.get_by_source_id(
            origin=ProvisionalEntryOrigin.APPROVED_PURCHASE_ORDER,
            source_id=envelope.aggregate_id,
        )
        if existing is not None:
            return
        actor_id = _uuid_payload(envelope, "requested_by")
        amount = _money_payload(envelope, "amount")
        supplier_id = _uuid_payload(envelope, "supplier_id")
        entry = ProvisionalFinancialEntry.create(
            company_id=envelope.company_id,
            origin=ProvisionalEntryOrigin.APPROVED_PURCHASE_ORDER,
            source_id=envelope.aggregate_id,
            source_version=_aggregate_version(envelope),
            supplier_id=supplier_id,
            supplier_tax_id=_text_payload(envelope, "supplier_tax_id"),
            amount=amount,
            currency=_text_payload(envelope, "currency"),
            created_by=actor_id,
        )
        title = Payable.create(
            company_id=envelope.company_id,
            number=_text_payload(envelope, "document_number"),
            supplier_id=supplier_id,
            supplier_tax_id=entry.supplier_tax_id,
            created_by=actor_id,
            provisional_entry_id=entry.id,
            nominal_amount=amount,
            installment_plan=_purchase_order_plan(envelope, amount),
            currency=entry.currency,
        )
        await entries.add(entry, actor_id=actor_id)
        await PayableRepository(session, company_id=envelope.company_id).add(
            title, actor_id=actor_id
        )
        converted = entry.convert(title.id)
        await entries.save(converted, actor_id=actor_id)
        await _audit_provision(
            session,
            envelope=envelope,
            actor_id=actor_id,
            operation="PayableProvisionedFromPurchaseOrder",
            before=None,
            after=converted,
            payable=title,
        )

    async def _provision_fiscal_document(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
    ) -> None:
        assert envelope.company_id is not None
        entries = ProvisionalEntryRepository(session, company_id=envelope.company_id)
        existing = await entries.get_by_source_id(
            origin=ProvisionalEntryOrigin.AUTHORIZED_FISCAL_DOCUMENT,
            source_id=envelope.aggregate_id,
        )
        if existing is not None:
            return
        actor_id = _uuid_payload(envelope, "requested_by")
        amount = _money_payload(envelope, "total_amount")
        supplier_tax_id = _text_payload(envelope, "supplier_tax_id")
        purchase_match = await entries.find_purchase_order_match(
            supplier_tax_id=supplier_tax_id,
            amount=amount,
        )
        supplier_id = _optional_uuid_payload(envelope, "supplier_id")
        if supplier_id is None:
            if purchase_match is None:
                raise ValueError(
                    "Fiscal authorization requires supplier_id or one unique purchase provision."
                )
            supplier_id = purchase_match.supplier_id
        entry = ProvisionalFinancialEntry.create(
            company_id=envelope.company_id,
            origin=ProvisionalEntryOrigin.AUTHORIZED_FISCAL_DOCUMENT,
            source_id=envelope.aggregate_id,
            source_version=_aggregate_version(envelope),
            supplier_id=supplier_id,
            supplier_tax_id=supplier_tax_id,
            amount=amount,
            currency=_text_payload(envelope, "currency"),
            created_by=actor_id,
        )
        payable = None
        if (
            purchase_match is not None
            and purchase_match.status is ProvisionalEntryStatus.CONVERTED
            and purchase_match.payable_id is not None
        ):
            payable = await PayableRepository(session, company_id=envelope.company_id).get(
                purchase_match.payable_id
            )
            if payable is None:
                raise ValueError("Purchase provision references a missing payable.")
        if payable is None:
            payable = Payable.create(
                company_id=envelope.company_id,
                number=f"NFE-{_text_payload(envelope, 'document_number')}",
                supplier_id=supplier_id,
                supplier_tax_id=supplier_tax_id,
                created_by=actor_id,
                provisional_entry_id=entry.id,
                nominal_amount=amount,
                installment_plan=_fiscal_plan(envelope, amount),
                currency=entry.currency,
            )
        await entries.add(entry, actor_id=actor_id)
        if purchase_match is None or purchase_match.payable_id is None:
            await PayableRepository(session, company_id=envelope.company_id).add(
                payable, actor_id=actor_id
            )
        converted = entry.convert(payable.id)
        await entries.save(converted, actor_id=actor_id)
        await _audit_provision(
            session,
            envelope=envelope,
            actor_id=actor_id,
            operation="PayableProvisionedFromFiscalDocument",
            before=None,
            after=converted,
            payable=payable,
        )

    async def _cancel_fiscal_document(
        self,
        session: AsyncSession,
        envelope: MessageEnvelope,
    ) -> None:
        assert envelope.company_id is not None
        actor_id = _uuid_payload(envelope, "requested_by")
        entries = ProvisionalEntryRepository(session, company_id=envelope.company_id)
        current = await entries.get_by_source_id(
            origin=ProvisionalEntryOrigin.AUTHORIZED_FISCAL_DOCUMENT,
            source_id=envelope.aggregate_id,
        )
        if current is None:
            raise ValueError("Fiscal cancellation has no associated payable provision.")
        if current.status is ProvisionalEntryStatus.VOIDED:
            return
        payable = None
        if current.payable_id is not None:
            payables = PayableRepository(session, company_id=envelope.company_id)
            payable = await payables.get(current.payable_id)
            if payable is None:
                raise ValueError("Fiscal provision references a missing payable.")
            if payable.status is not PayableStatus.REJECTED:
                payable = payable.cancel_from_source(
                    cancelled_by=actor_id,
                    reason="Fiscal document cancelled before settlement.",
                )
                await payables.save(payable, actor_id=actor_id)
        voided = current.void("Fiscal document cancelled by M11.")
        await entries.save(voided, actor_id=actor_id)
        await _audit_provision(
            session,
            envelope=envelope,
            actor_id=actor_id,
            operation="PayableProvisionVoidedFromFiscalCancellation",
            before=current,
            after=voided,
            payable=payable,
        )


class FiscalEventConsumer:
    """Consume payable-relevant M11/M6 facts exactly once through Inbox."""

    def __init__(
        self,
        database: Database,
        inbox: InboxService | None = None,
        provisioning: PayableProvisioningService | None = None,
    ) -> None:
        self._database = database
        self._inbox = inbox or InboxService()
        self._provisioning = provisioning or PayableProvisioningService()

    async def consume(self, envelope: MessageEnvelope) -> InboxProcessResult:
        _validate_envelope(envelope)

        async def effect(session: AsyncSession, message: MessageEnvelope) -> None:
            await self._provisioning.apply(session, message)

        async with self._database.session() as session, session.begin():
            return await self._inbox.process(
                session,
                consumer_name=FINANCE_PAYABLE_PROVISIONING_CONSUMER,
                envelope=envelope,
                effect=effect,
            )


def _validate_envelope(envelope: MessageEnvelope) -> None:
    supported = {
        FISCAL_DOCUMENT_AUTHORIZED: ("fiscal", "fiscal", "fiscal_document"),
        FISCAL_DOCUMENT_CANCELLED: ("fiscal", "fiscal", "fiscal_document"),
        PURCHASE_ORDER_APPROVED: ("procurement", "procurement", "purchase_order"),
    }
    expected = supported.get(envelope.message_type)
    if (
        expected is None
        or envelope.message_kind is not MessageKind.DOMAIN_EVENT
        or envelope.event_version != 1
        or envelope.company_id is None
        or (
            envelope.producer_module,
            envelope.producer_domain,
            envelope.aggregate_type,
        )
        != expected
    ):
        raise ValueError("Unsupported payable provisioning event envelope.")
    payload_company = envelope.payload.get("company_id")
    if payload_company is not None and str(payload_company) != str(envelope.company_id):
        raise ValueError("Payable provisioning event crosses the company boundary.")
    source_id = envelope.payload.get("source_id")
    if source_id is not None and str(source_id) != str(envelope.aggregate_id):
        raise ValueError("Payable provisioning source identity does not match its envelope.")


def _purchase_order_plan(
    envelope: MessageEnvelope,
    amount: Decimal,
) -> tuple[tuple[date, Decimal], ...]:
    raw_days = envelope.payload.get("installment_days")
    if (
        not isinstance(raw_days, list)
        or not raw_days
        or any(type(day) is not int or day < 0 for day in raw_days)
        or sorted(set(raw_days)) != raw_days
    ):
        raise ValueError("Purchase order event requires ordered unique installment_days.")
    quotient, remainder = divmod(int(amount * 100), len(raw_days))
    return tuple(
        (
            envelope.occurred_at.date() + timedelta(days=day),
            Decimal(quotient + (1 if index < remainder else 0)) / 100,
        )
        for index, day in enumerate(raw_days)
    )


def _fiscal_plan(
    envelope: MessageEnvelope,
    amount: Decimal,
) -> tuple[tuple[date, Decimal], ...]:
    raw = envelope.payload.get("installments")
    if not isinstance(raw, list) or not raw:
        raise ValueError("Fiscal authorization requires a non-empty installment plan.")
    plan = []
    for installment in raw:
        if not isinstance(installment, dict):
            raise ValueError("Fiscal installment entries must be objects.")
        try:
            due_date = date.fromisoformat(str(installment.get("due_date")))
            installment_amount = Decimal(str(installment.get("amount"))).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError) as error:
            raise ValueError("Fiscal installment data is invalid.") from error
        plan.append((due_date, installment_amount))
    if sum((value for _, value in plan), Decimal("0.00")) != amount:
        raise ValueError("Fiscal installments do not reconcile with the authorized total.")
    return tuple(plan)


def _aggregate_version(envelope: MessageEnvelope) -> int:
    if envelope.aggregate_version is None:
        raise ValueError("Payable provisioning events require aggregate_version.")
    return envelope.aggregate_version


def _uuid_payload(envelope: MessageEnvelope, field: str) -> UUID:
    value = _optional_uuid_payload(envelope, field)
    if value is None:
        raise ValueError(f"Payable provisioning event requires a valid {field}.")
    return value


def _optional_uuid_payload(envelope: MessageEnvelope, field: str) -> UUID | None:
    value = envelope.payload.get(field)
    if value is None:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Payable provisioning event requires a valid {field}.") from error


def _text_payload(envelope: MessageEnvelope, field: str) -> str:
    value = envelope.payload.get(field)
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise ValueError(f"Payable provisioning event requires {field}.")
    return normalized


def _money_payload(envelope: MessageEnvelope, field: str) -> Decimal:
    try:
        value = Decimal(str(envelope.payload.get(field))).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"Payable provisioning event requires a valid {field}.") from error
    if value <= 0:
        raise ValueError(f"Payable provisioning event requires a positive {field}.")
    return value


async def _audit_provision(
    session: AsyncSession,
    *,
    envelope: MessageEnvelope,
    actor_id: UUID,
    operation: str,
    before: ProvisionalFinancialEntry | None,
    after: ProvisionalFinancialEntry,
    payable: Payable | None,
) -> None:
    await AuditService().record(
        session,
        AuditEvent(
            actor_user_id=actor_id,
            company_id=after.company_id,
            branch_id=None,
            module="finance",
            entity_type="provisional_financial_entry",
            entity_id=after.id,
            operation=operation,
            request_id=envelope.request_id,
            correlation_id=envelope.correlation_id,
            before_snapshot=None if before is None else _entry_snapshot(before),
            after_snapshot={
                **_entry_snapshot(after),
                "payable_status": None if payable is None else payable.status.value,
                "scheduled_installments": 0
                if payable is None
                else sum(item.status.value == "SCHEDULED" for item in payable.installments),
            },
            reason_code=envelope.message_type,
        ),
    )


def _entry_snapshot(entry: ProvisionalFinancialEntry) -> dict[str, Any]:
    return {
        "id": str(entry.id),
        "company_id": str(entry.company_id),
        "origin": entry.origin.value,
        "source_id": str(entry.source_id),
        "source_version": entry.source_version,
        "supplier_id": str(entry.supplier_id),
        "supplier_tax_id": entry.supplier_tax_id,
        "amount": str(entry.amount),
        "currency": entry.currency,
        "status": entry.status.value,
        "payable_id": None if entry.payable_id is None else str(entry.payable_id),
        "version": entry.version,
    }


PayableProvisioningConsumer = FiscalEventConsumer

__all__ = [
    "FINANCE_PAYABLE_PROVISIONING_CONSUMER",
    "FISCAL_DOCUMENT_AUTHORIZED",
    "FISCAL_DOCUMENT_CANCELLED",
    "PURCHASE_ORDER_APPROVED",
    "FiscalEventConsumer",
    "PayableProvisioningConsumer",
    "PayableProvisioningService",
]
